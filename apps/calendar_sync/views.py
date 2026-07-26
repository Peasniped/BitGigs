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
    """``POST ?start=&end=`` → activate invites for the planned shifts shown.

    Bulk-activates every PLANNED shift in the range whose workplace has invites
    enabled and that isn't already synced. Idempotent: an already-active shift is
    skipped, so pressing the button twice doesn't re-send. Each activation is
    best-effort (``invites.activate`` swallows send errors), so one bad send can't
    fail the whole batch or the request.
    """

    def post(self, request):
        from calendar_sync.models import ShiftInvite
        from calendar_sync import invites
        from shifts.models import PlannedShift

        start = parse_iso_date_param(request.GET.get("start"))
        end = parse_iso_date_param(request.GET.get("end"))
        if not (start and end):
            today = timezone.localdate()
            year = parse_int_param(request.GET.get("year"), today.year)
            month = parse_int_param(request.GET.get("month"), today.month)
            if not (1 <= month <= 12):
                return JsonResponse({"error": "Invalid month."}, status=400)
            start, end = services.month_window(year, month, pad_days=0)
        if end < start:
            return JsonResponse({"error": "end is before start."}, status=400)

        active_uids = set(
            ShiftInvite.objects.filter(status=ShiftInvite.STATUS_ACTIVE)
            .values_list("invite_uid", flat=True)
        )
        planned = (
            PlannedShift.objects.filter(
                status=PlannedShift.Status.PLANNED, date__gte=start, date__lte=end,
            )
            .select_related("workplace")
            .prefetch_related("workplace__contracts__calendar_config")
        )

        activated = 0
        for shift in planned:
            if shift.invite_uid and shift.invite_uid in active_uids:
                continue  # already synced
            if not invites.eligible(shift):
                continue
            if invites.activate(shift) is not None:
                activated += 1

        return JsonResponse({"activated": activated})


# ─────────────────────────────────────────────────────────────────────────────
# Settings → Calendar tab (both directions). Each form has its own POST endpoint,
# like the Email/Sign-in tabs — their forms can't nest in the UserSettings form.
# ─────────────────────────────────────────────────────────────────────────────

def calendar_settings_context(*, sub_form=None, invite_form=None, open_modal="", sub_edit_id=""):
    """State for the Calendar settings tab: subscriptions (Direction 1), the
    global invite settings + per-workplace configs (Direction 2), and whether
    mail is configured (invites ride the SMTP channel)."""
    import json

    from core.constants import APP_ACCENT_CHOICES
    from core.models import EmailSettings
    from workplaces.models import Workplace

    from .forms import (
        CalendarInviteSettingsForm,
        CalendarSubscriptionForm,
    )
    from .models import CalendarInviteSettings, CalendarSubscription

    invite_settings = CalendarInviteSettings.load()
    subscriptions = list(CalendarSubscription.objects.all())

    # Read-only overview grouped workplace → contract (item 9). Editing lives on
    # the contract page, so each contract row links there rather than embedding a
    # form here.
    workplaces = (
        Workplace.objects.all().order_by("name")
        .prefetch_related("contracts__calendar_config", "contracts__term_sets")
    )
    workplace_rows = []
    for wp in workplaces:
        contracts = []
        for contract in wp.contracts.all():
            config = getattr(contract, "calendar_config", None)
            contracts.append({
                "contract": contract,
                "config": config,
                "recipient": config.resolved_recipient(invite_settings) if config else "",
            })
        workplace_rows.append({"workplace": wp, "contracts": contracts})
    return {
        "cal_subscriptions": subscriptions,
        "cal_sub_form": sub_form or CalendarSubscriptionForm(),
        "cal_invite_settings": invite_settings,
        "cal_invite_form": invite_form or CalendarInviteSettingsForm(instance=invite_settings),
        "cal_workplace_rows": workplace_rows,
        "cal_mail_configured": EmailSettings.load().is_configured_for(
            EmailSettings.ROLE_CALENDAR
        ),
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
    """Send a one-off test invite to the owner address (the "invite myself" button)."""

    def post(self, request):
        from . import invites
        from .models import CalendarInviteSettings

        to_address = (
            request.POST.get("to")
            or CalendarInviteSettings.load().personal_address()
        )
        if not to_address:
            messages.error(request, "Set an address to invite first.")
            return _calendar_redirect()
        ok, error = invites.send_test_invite(to_address)
        if ok:
            messages.success(request, f"Test invite sent to {to_address}.")
        else:
            messages.error(request, f"Test invite failed: {error}")
        return _calendar_redirect()
