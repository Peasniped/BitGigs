"""Calendar sync views.

Phase 1 exposes one JSON endpoint, ``busy``, that the planning overlay polls for
the visible month. It stays thin — the fetch/parse/cache/aggregate work lives in
``services`` — and always answers with JSON, never a redirect or a 500, so a
broken feed degrades to an empty overlay.
"""
from datetime import timedelta

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from core.utils import parse_int_param, parse_iso_date_param

from . import services

# Upper bound on the busy window a client can ask for, so a crafted request
# can't force a huge RRULE expansion. The planning grid spans at most a couple
# of payroll periods (~7 weeks); this leaves generous headroom.
MAX_WINDOW_DAYS = 120


class BusyView(View):
    """``GET`` → JSON busy blocks for the planning overlay.

    Preferred call is ``?start=YYYY-MM-DD&end=YYYY-MM-DD`` — the exact span of
    days the planning grid is showing, which (with offset payroll periods) can
    reach well beyond the selected month. Falls back to ``?year=&month=`` (the
    padded month window) when a range isn't given.

    Own (``bitgigs-``) UIDs are filtered in ``parse_calendar`` so a shift we
    emitted as an invite never reads back as a collision with itself. ``refresh=1``
    busts the per-subscription cache (the overlay's manual refresh).
    """

    def get(self, request):
        refresh = request.GET.get("refresh") == "1"

        start = parse_iso_date_param(request.GET.get("start"))
        end = parse_iso_date_param(request.GET.get("end"))
        if start and end:
            if end < start:
                return JsonResponse({"error": "end is before start."}, status=400)
            # Clamp an over-wide range rather than reject it.
            end = min(end, start + timedelta(days=MAX_WINDOW_DAYS))
            window_start, window_end = start, end
        else:
            today = timezone.localdate()
            year = parse_int_param(request.GET.get("year"), today.year)
            month = parse_int_param(request.GET.get("month"), today.month)
            if not (1 <= month <= 12):
                return JsonResponse({"error": "Invalid month."}, status=400)
            window_start, window_end = services.month_window(year, month)

        blocks = services.busy_blocks(window_start, window_end, refresh=refresh)
        return JsonResponse({"busy": blocks})


class SendInvitesView(View):
    """``POST ?year=&month=`` → activate invites for the planned shifts that
    **belong to the viewed month's payroll period** for each workplace.

    Scoping is per-workplace by payroll period, **not** the padded visible grid:
    an offset job (e.g. a 20th→19th period) whose shifts fall after the 20th are
    in its *next* period, so they aren't swept into this month's send — they're
    offered when you view that next month. Conversely a late-of-previous-month
    day that belongs to *this* period is included, even though it's grid padding.
    Idempotent: a shift whose active invite still matches it is skipped, so
    pressing twice doesn't re-send. A shift that was **edited** after its invite
    went out is not "already synced" though — its recipients hold the old times —
    so those are re-sent (``invites.resync``, bumped SEQUENCE, an update rather
    than a duplicate for the calendar client). Each send is best-effort
    (``invites.activate``/``resync`` swallow send errors), so one bad send can't
    fail the whole batch.

    ``GET`` on the same URL answers with a **preview** of that same plan — what
    the confirm modal shows before the owner commits to mailing real people.
    Both come from ``invites.month_sweep``, so the dialog can't promise a send
    the POST would then skip.
    """

    def _month(self, request):
        """(year, month) from the query string, or None when the month is bad."""
        today = timezone.localdate()
        year = parse_int_param(request.GET.get("year"), today.year)
        month = parse_int_param(request.GET.get("month"), today.month)
        return (year, month) if 1 <= month <= 12 else None

    def get(self, request):
        """JSON preview: per workplace, how many invites and to whom."""
        from core.utils import avatar_for_name
        from scheduler.models import SchedulerHeartbeat

        from calendar_sync import invites

        parsed = self._month(request)
        if parsed is None:
            return JsonResponse({"error": "Invalid month."}, status=400)
        year, month = parsed

        groups = invites.month_sweep(year, month)
        rows = []
        for group in groups:
            initials, fallback = avatar_for_name(group.workplace.name)
            rows.append({
                "name": group.workplace.name,
                "initials": initials,
                "color": group.workplace.color or fallback,
                "icon": group.workplace.icon or "",
                "icon_url": (
                    group.workplace.custom_icon.url
                    if group.workplace.custom_icon else ""
                ),
                "new": len(group.new),
                "updates": len(group.updates),
                "recipients": group.recipients,
            })
        return JsonResponse({
            "workplaces": rows,
            "new": sum(len(g.new) for g in groups),
            "updates": sum(len(g.updates) for g in groups),
            "total": sum(g.total for g in groups),
            # Queued sends need something to drain the queue; say so *before* the
            # press rather than in a flash message after it.
            "scheduler_alive": SchedulerHeartbeat.is_alive(),
        })

    def post(self, request):
        from scheduler.models import SchedulerHeartbeat

        from calendar_sync import invites

        parsed = self._month(request)
        if parsed is None:
            return JsonResponse({"error": "Invalid month."}, status=400)
        year, month = parsed

        activated = 0
        resent = 0
        for group in invites.month_sweep(year, month):
            for shift in group.updates:
                invites.resync(shift)
                resent += 1
            for shift in group.new:
                if invites.activate(shift) is not None:
                    activated += 1

        # Sends are queued, not sent inline — warn (on the reload the JS triggers)
        # if nothing is there to drain the queue, else they'd silently never go.
        alive = SchedulerHeartbeat.is_alive()
        queued = activated + resent
        if queued and not alive:
            messages.warning(
                request,
                f"{queued} invite(s) queued, but the scheduler isn't running, "
                "so they won't send until it starts (Settings → Jobs).",
            )
        return JsonResponse({
            "activated": activated, "resent": resent, "scheduler_alive": alive,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Settings → Calendar tab (both directions). Each form has its own POST endpoint,
# like the Email/Sign-in tabs — their forms can't nest in the UserSettings form.
# ─────────────────────────────────────────────────────────────────────────────

def calendar_settings_context(*, sub_form=None, invite_form=None, open_modal="", sub_edit_id=""):
    """State for the Calendar settings tab: subscriptions (Direction 1), the
    global invite settings + per-workplace configs (Direction 2), and whether
    mail is configured (invites ride the SMTP channel)."""
    import json
    from urllib.parse import quote

    from core.constants import APP_ACCENT_CHOICES
    from core.models import EmailSettings
    from workplaces.models import Workplace

    from .forms import (
        CalendarInviteSettingsForm,
        CalendarSubscriptionForm,
    )
    from .models import CalendarInviteSettings, CalendarSubscription

    from . import reconcile

    invite_settings = CalendarInviteSettings.load()
    email_settings = EmailSettings.load()
    subscriptions = list(CalendarSubscription.objects.all())
    drift_items = reconcile.drift_details()
    # Every link out to a contract editor carries this back, so saving there
    # returns to the tab rather than dropping the owner on the workplace page.
    back_here = reverse("core:settings") + "?tab=calendar"

    # Read-only overview grouped workplace → contract (item 9). Editing lives on
    # the contract page, so each contract row links there rather than embedding a
    # form here.
    workplaces = (
        Workplace.objects.all().order_by("name")
        .prefetch_related("contracts__calendar_config", "contracts__term_sets")
    )
    workplace_rows = []
    # Contracts that are armed to send but resolve no work address: with the
    # personal copy on they're fine (the shift lands in the owner's own calendar),
    # with it off their invites reach nobody at all. The list doesn't depend on
    # that switch, so it's rendered once and the switch reveals the warning.
    no_recipient = []
    for wp in workplaces:
        contracts = []
        for contract in wp.contracts.all():
            config = getattr(contract, "calendar_config", None)
            recipient = config.resolved_recipient(invite_settings) if config else ""
            contracts.append({
                "contract": contract,
                "config": config,
                "recipient": recipient,
            })
            if config is not None and config.send_invites and not recipient:
                no_recipient.append({
                    "label": f"{wp.name} — {contract.name}" if contract.name else wp.name,
                    "url": reverse(
                        "workplaces:contract-update", args=[wp.slug, contract.pk]
                    ) + f"?next={quote(back_here, safe='')}",
                })
        workplace_rows.append({"workplace": wp, "contracts": contracts})
    return {
        "cal_subscriptions": subscriptions,
        "cal_sub_form": sub_form or CalendarSubscriptionForm(),
        "cal_invite_settings": invite_settings,
        "cal_invite_form": invite_form or CalendarInviteSettingsForm(instance=invite_settings),
        "cal_workplace_rows": workplace_rows,
        "cal_no_recipient_contracts": no_recipient,
        "cal_back_here": back_here,
        "cal_mail_configured": email_settings.is_configured_for(
            EmailSettings.ROLE_CALENDAR
        ),
        # is_configured_for() folds two separate things together — the mail
        # master switch and whether the calendar role resolves to a usable
        # connection. The master arm's warning has to name which one is
        # missing, so it needs them apart. Connection first: with none at all,
        # sending the owner off to flip the mail switch is a dead end, because
        # EmailSettingsForm refuses to enable mail until one exists.
        "cal_mail_has_connection": bool(
            cal_conn := email_settings.connection_for(EmailSettings.ROLE_CALENDAR)
        ) and cal_conn.is_configured,
        # Explicit-sync banner + review modal: active invites whose recipients
        # drifted from what they were last sent to (e.g. after a work/personal
        # e-mail change). ``items`` are grouped by change; ``count`` stays the
        # number of affected invites (shifts) for the banner text.
        "cal_invite_drift": {
            "items": drift_items,
            "count": sum(g["count"] for g in drift_items),
        },
        "cal_open_modal": open_modal,
        "cal_sub_edit_id": sub_edit_id,
        # Swatch picker (Direction 1 add/edit modal): the shared app accent
        # family, already minus both brand colours, plus the colours already in
        # use so a new calendar auto-picks a distinct one (see the modal script).
        "cal_color_choices": APP_ACCENT_CHOICES,
        "cal_used_colors_json": json.dumps([s.color.lower() for s in subscriptions]),
    }


def _calendar_redirect():
    return redirect(f"{reverse('core:settings')}?tab=calendar")


def _render_calendar(request, **overrides):
    """Re-render the settings page on the Calendar tab (used on form errors)."""
    from core.forms import UserSettingsForm
    from core.models import UserSettings

    return render(request, "core/settings.html", {
        "form": UserSettingsForm(instance=UserSettings.load(), tab="display"),
        "next_url": None,
        "active_tab": "calendar",
        **calendar_settings_context(**overrides),
    })


class CalendarSubscriptionSaveView(View):
    """Create or edit a subscription (Direction 1)."""

    def post(self, request):
        from .forms import CalendarSubscriptionForm
        from .models import CalendarSubscription

        pk = request.POST.get("id")
        instance = get_object_or_404(CalendarSubscription, pk=pk) if pk else None
        form = CalendarSubscriptionForm(request.POST, instance=instance)
        if form.is_valid():
            sub = form.save()
            services.refresh_subscription(sub)  # a changed URL takes effect now
            messages.success(request, f"Saved calendar “{sub.label}”.")
            return _calendar_redirect()
        messages.error(request, "Please fix the highlighted problems.")
        return _render_calendar(
            request, sub_form=form, open_modal="subscription", sub_edit_id=pk or "",
        )


class CalendarSubscriptionDeleteView(View):
    def post(self, request):
        from .models import CalendarSubscription

        sub = get_object_or_404(CalendarSubscription, pk=request.POST.get("id"))
        services.refresh_subscription(sub)
        label = sub.label
        sub.delete()
        messages.success(request, f"Removed calendar “{label}”.")
        return _calendar_redirect()


class CalendarSubscriptionTestView(View):
    """Fetch a subscription now and report the event count or the first error."""

    def post(self, request):
        from .models import CalendarSubscription

        sub = get_object_or_404(CalendarSubscription, pk=request.POST.get("id"))
        today = timezone.localdate()
        events = services.subscription_busy(
            sub, today, today + timedelta(days=31), refresh=True
        )
        sub.refresh_from_db()
        if sub.last_fetch_ok:
            messages.success(
                request,
                f"“{sub.label}” fetched OK — {len(events)} event(s) in the next month.",
            )
        else:
            messages.error(
                request, f"“{sub.label}” could not be fetched: {sub.last_error}"
            )
        return _calendar_redirect()


class CalendarSubscriptionToggleView(View):
    """AJAX enable/disable of one subscription (Direction 1).

    Drives the planning page's per-calendar sliders: flipping one writes
    ``CalendarSubscription.enabled`` — a **permanent** change, the same switch as
    Settings → Calendar — and returns the fresh ``busy_config_token`` so the
    overlay's session cache stays coherent.
    """

    def post(self, request):
        from .models import CalendarSubscription

        sub = get_object_or_404(CalendarSubscription, pk=request.POST.get("id"))
        sub.enabled = request.POST.get("enabled") == "1"
        sub.save(update_fields=["enabled", "updated_at"])
        return JsonResponse({
            "ok": True,
            "enabled": sub.enabled,
            "token": services.busy_config_token(),
        })


class CalendarSubscriptionCheckView(View):
    """AJAX sibling of ``subscription-test``: fetch a subscription now and report
    the result as JSON. Drives the Calendar tab's on-load auto-check of calendars
    that have never been fetched (a freshly added one), so a bad URL surfaces
    without the operator pressing anything or the page reloading."""

    def post(self, request):
        from django.utils import formats

        from .models import CalendarSubscription

        sub = get_object_or_404(CalendarSubscription, pk=request.POST.get("id"))
        today = timezone.localdate()
        events = services.subscription_busy(
            sub, today, today + timedelta(days=31), refresh=True
        )
        sub.refresh_from_db()
        last = timezone.localtime(sub.last_fetch_at) if sub.last_fetch_at else None
        return JsonResponse({
            "ok": bool(sub.last_fetch_ok),
            "count": len(events),
            "error": sub.last_error or "",
            "last_checked": formats.date_format(last, "DATETIME_FORMAT") if last else "",
        })


class CalendarInviteSettingsSaveView(View):
    """Save the global invite settings (Direction 2)."""

    def post(self, request):
        from .forms import CalendarInviteSettingsForm
        from .models import CalendarInviteSettings

        form = CalendarInviteSettingsForm(request.POST, instance=CalendarInviteSettings.load())
        if form.is_valid():
            form.save()
            messages.success(request, "Calendar invite settings saved.")
            return _calendar_redirect()
        messages.error(request, "Please fix the highlighted problems.")
        return _render_calendar(request, invite_form=form)


class InviteTestView(View):
    """Queue a one-off test invite to the owner address (the "invite myself"
    button). The send is two SMTP round-trips (REQUEST + immediate CANCEL), so it
    runs off-request via the scheduler queue — the page returns instantly and the
    result lands on the "Last test" badge once the scheduler picks it up."""

    def post(self, request):
        from core.models import EmailSettings
        from scheduler.models import SchedulerHeartbeat
        from scheduler.tasks import enqueue

        from .models import CalendarInviteSettings
        from .tasks import TEST_INVITE

        to_address = (
            request.POST.get("to")
            or CalendarInviteSettings.load().personal_address()
        )
        if not to_address:
            messages.error(request, "Set an address to invite first.")
            return _calendar_redirect()
        # Fail fast on the one thing we can check synchronously, so the user
        # isn't left waiting on a badge that will never turn green.
        if not EmailSettings.load().is_configured_for(EmailSettings.ROLE_CALENDAR):
            messages.error(
                request,
                "Email isn't configured for calendar invites yet — set it up on "
                "the Email tab first.",
            )
            return _calendar_redirect()

        enqueue(TEST_INVITE, {"to": to_address})
        if SchedulerHeartbeat.is_alive():
            messages.success(
                request,
                f"Test invite queued for {to_address} — it'll arrive shortly and "
                "withdraw itself, so you don't need to respond.",
            )
        else:
            messages.warning(
                request,
                f"Test invite queued for {to_address}, but the scheduler doesn't "
                "appear to be running, so it won't send until it's started. See "
                "Settings → Jobs.",
            )
        return _calendar_redirect()


class InviteSyncView(View):
    """The explicit "Sync now" — reconcile active invites to their current
    recipients: withdraw dropped addresses, re-request the current set. Runs the
    whole active set (each in-sync invite is a cheap no-op)."""

    def post(self, request):
        from django.utils.http import url_has_allowed_host_and_scheme

        from . import reconcile

        counts = reconcile.sync_all()
        moved, withdrew, failed = (
            counts["moved"], counts["withdrawn"], counts["failed"]
        )

        # The review modal drives this over fetch and renders its own live status,
        # so answer JSON there instead of a redirect + flash it would never show.
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"moved": moved, "withdrawn": withdrew, "failed": failed}
            )

        if moved or withdrew:
            messages.success(
                request,
                f"Synced calendar invites — moved {moved} to the current "
                f"address, withdrew {withdrew}.",
            )
        else:
            messages.info(request, "Calendar invites are already up to date.")

        nxt = request.POST.get("next") or request.GET.get("next")
        if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(nxt)
        return _calendar_redirect()


class ShiftInviteView(View):
    """Send (or re-send) the invite for a single planned shift — the explicit
    per-shift control in the edit-shift modal. Invites are sent once and only
    re-sent on request, so this is the one place an edited shift's invite gets
    refreshed. Best-effort JSON; never raises."""

    def post(self, request, pk):
        from shifts.models import PlannedShift

        from . import invites

        shift = get_object_or_404(
            PlannedShift, pk=pk, status=PlannedShift.Status.PLANNED
        )
        if invites._is_past(shift):
            return JsonResponse(
                {"ok": False, "error": "This shift has already happened."}, status=400
            )
        # An active invite already exists → re-send (bumped SEQUENCE); otherwise
        # this is the first send.
        if invites._active_invite(shift) is not None:
            invites.resync(shift)
            action = "resent"
        elif invites.eligible(shift) and invites.recipients_for(shift):
            invites.activate(shift)
            action = "sent"
        else:
            return JsonResponse(
                {"ok": False, "error": "This shift can't be invited."}, status=400
            )

        active = invites._active_invite(shift) is not None
        return JsonResponse({
            "ok": True,
            "active": active,
            "action": action,
            # Queued, not sent: the SMTP round-trip happens in the scheduler
            # process, and saying "sent" here is exactly the claim that left a
            # rejected invite looking delivered.
            "message": (
                "Invite queued to re-send." if action == "resent"
                else "Invite queued to send."
            ),
        })
