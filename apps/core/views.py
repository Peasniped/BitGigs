import logging
from decimal import Decimal

from django.contrib.auth.decorators import login_not_required
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LoginView
from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.utils import timezone

from .constants import APP_ACCENT_CHOICES, DEFAULT_ACCENT, DEFAULT_SECONDARY
from .models import EmailLog, EmailSettings, MailConnection, TaxProfile, UserSettings
from .forms import EmailSettingsForm, TaxProfileForm, UserSettingsForm
from .utils import client_ip, parse_int_param, prev_next_month
from .dashboard_service import DashboardDataService, get_pending_shifts, get_todays_banner
from . import onboarding as ob
from .about import about_context, slogan
from api.views import api_settings_context

logger = logging.getLogger(__name__)


def _safe_next(request, raw):
    """A same-origin relative redirect target, or None. Uses Django's checker,
    which also rejects the ``/\\evil.com`` form browsers treat as ``//``."""
    if raw and url_has_allowed_host_and_scheme(raw, allowed_hosts=None,
                                               require_https=request.is_secure()):
        return raw
    return None


class MediaView(View):
    """Serve MEDIA_ROOT (workplace icons) behind the site's login gate.

    WhiteNoise handles the static files, but it indexes them once at startup, so
    an icon uploaded after boot would 404 until the process restarted — media has
    to come from a live path instead. Deliberately *not* marked
    ``login_not_required``: uploads belong to the owner, like every other page.
    ``django.views.static.serve`` normalises the path and refuses to escape the
    document root."""

    def get(self, request, path):
        from django.conf import settings as django_settings
        from django.views.static import serve
        return serve(request, path, document_root=django_settings.MEDIA_ROOT)


class DashboardView(View):
    """Home page — calendar, pay counters, and workplace cards."""

    def get(self, request):
        from calendar_view.services import CalendarService
        from workplaces.services import maybe_prune_orphan_icons

        # Housekeeping: sweep orphaned workplace-icon files at most once a day.
        maybe_prune_orphan_icons()

        today = timezone.localdate()
        year = parse_int_param(request.GET.get("year"), today.year)
        month = parse_int_param(request.GET.get("month"), today.month)

        hour = timezone.localtime().hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 18:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        grid = CalendarService.month_calendar(year, month)
        grid.annotate_overlaps()
        prev_year, prev_month, next_year, next_month = prev_next_month(year, month)

        # Core stats + workplace cards
        dashboard = DashboardDataService.get_full(year, month)
        stats = dashboard.stats

        # Pending shifts for approval
        pending_shifts_json, pending_shifts_count = get_pending_shifts(today)

        # Today's banner
        todays_banner, todays_shifts_json, todays_banner_shifts_json = get_todays_banner(today)

        from workplaces.services import hidden_workplace_count

        return render(
            request,
            "dashboard.html",
            {
                "greeting": greeting,
                "grid": grid,
                "hidden_workplace_count": hidden_workplace_count(len(dashboard.workplace_data)),
                "year": year,
                "month": month,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
                "workplace_data": dashboard.workplace_data,
                "total_earned_gross": stats.total_earned_gross,
                "total_earned_net": stats.total_earned_net,
                "total_planned_gross": stats.total_planned_gross,
                "total_planned_net": stats.total_planned_net,
                "total_combined_gross": stats.combined_gross,
                "total_combined_net": stats.combined_net,
                "has_any_goal": stats.has_any_goal,
                "total_goal_min": stats.total_goal_min,
                "total_goal_max": stats.total_goal_max,
                "total_planned_hours": stats.total_planned_hours,
                "total_approved_hours": stats.total_approved_hours,
                "total_approved_shift_count": stats.total_approved_shift_count,
                "goal_bar_max": stats.total_goal_max if stats.total_goal_max else stats.total_goal_min,
                "goal_approved_pct": stats.goal_approved_pct,
                "goal_planned_pct": stats.goal_planned_pct,
                "cross_period_info": dashboard.cross_period_info,
                "today": today,
                "pending_shifts_json": pending_shifts_json,
                "pending_shifts_count": pending_shifts_count,
                "todays_banner": todays_banner,
                "todays_shifts_json": todays_shifts_json,
                "todays_banner_shifts_json": todays_banner_shifts_json,
                "email_failures_unseen": EmailLog.objects.failures_unseen().exists(),
            },
        )


class DashboardStatsAPIView(View):
    """Return dashboard stat card values as JSON for live updates."""

    def get(self, request):
        today = timezone.localdate()
        year = parse_int_param(request.GET.get("year"), today.year)
        month = parse_int_param(request.GET.get("month"), today.month)

        stats = DashboardDataService.get_stats(year, month)

        return JsonResponse({
            "ok": True,
            "planned_gross": int(stats.total_planned_gross.quantize(Decimal("0"))),
            "planned_net": int(stats.total_planned_net.quantize(Decimal("0"))),
            "earned_gross": int(stats.total_earned_gross.quantize(Decimal("0"))),
            "earned_net": int(stats.total_earned_net.quantize(Decimal("0"))),
            "combined_gross": int(stats.combined_gross.quantize(Decimal("0"))),
            "combined_net": int(stats.combined_net.quantize(Decimal("0"))),
            "has_any_goal": stats.has_any_goal,
            "total_planned_hours": str(stats.total_planned_hours.quantize(Decimal("0.01"))),
            "total_approved_hours": str(stats.total_approved_hours.quantize(Decimal("0.01"))),
            "total_approved_shift_count": stats.total_approved_shift_count,
            "total_goal_min": int(stats.total_goal_min.quantize(Decimal("0"))),
            "total_goal_max": int(stats.total_goal_max.quantize(Decimal("0"))) if stats.total_goal_max else None,
            "goal_approved_pct": stats.goal_approved_pct,
            "goal_planned_pct": stats.goal_planned_pct,
        })


class TaxProfileListView(View):
    def get(self, request):
        profiles = TaxProfile.objects.all()
        return render(request, "core/taxprofile_list.html", {"profiles": profiles})


class TaxProfileCreateView(View):
    def get(self, request):
        form = TaxProfileForm()
        return render(request, "core/taxprofile_form.html", {"form": form})

    def post(self, request):
        form = TaxProfileForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("core:taxprofile-list")
        return render(request, "core/taxprofile_form.html", {"form": form})


class TaxProfileUpdateView(View):
    def get(self, request, pk):
        profile = get_object_or_404(TaxProfile, pk=pk)
        form = TaxProfileForm(instance=profile)
        return render(
            request, "core/taxprofile_form.html", {"form": form, "profile": profile}
        )

    def post(self, request, pk):
        profile = get_object_or_404(TaxProfile, pk=pk)
        form = TaxProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            return redirect("core:taxprofile-list")
        return render(
            request, "core/taxprofile_form.html", {"form": form, "profile": profile}
        )


class TaxProfileDeleteView(View):
    def post(self, request, pk):
        profile = get_object_or_404(TaxProfile, pk=pk)
        profile.delete()
        return redirect("core:taxprofile-list")


class UserSettingsView(View):
    """Tabbed settings. The tabs are server-rendered (plain links carrying
    ``?tab=``) rather than Bootstrap's JS tabs: the Sign-in tab holds its own
    POST forms, which cannot legally nest inside the settings form, and links
    give deep-linking and a working back button for free."""

    def _context(self, request, form, next_url, tab):
        ctx = {
            "form": form, "next_url": next_url, "active_tab": tab,
            "accent_choices": APP_ACCENT_CHOICES, "default_accent": DEFAULT_ACCENT,
            "secondary_choices": APP_ACCENT_CHOICES, "default_secondary": DEFAULT_SECONDARY,
            **sign_in_context(request.user),
            # Only the Email tab touches the EmailSettings row.
            **(email_context() if tab == "email" else {}),
            **(api_settings_context(request) if tab == "api" else {}),
            **(about_context(request) if tab == "about" else {}),
        }
        if tab == "features":
            from . import features as feature_registry

            # The registry drives the pane, so a new feature needs no template
            # edit — each entry is paired with its bound form field here.
            ctx["feature_rows"] = [
                {"feature": f, "field": form[f.setting]} for f in feature_registry.FEATURES
            ]
        if tab == "jobs":
            from scheduler.views import jobs_settings_context
            ctx.update(jobs_settings_context())
        if tab == "calendar":
            from calendar_sync.views import calendar_settings_context
            ctx.update(calendar_settings_context())
        return ctx

    def get(self, request):
        settings = UserSettings.load()
        tab = active_settings_tab(request.GET.get("tab"))
        form = UserSettingsForm(instance=settings, tab=tab)
        next_url = _safe_next(request, request.GET.get("next"))
        return render(request, "core/settings.html",
                      self._context(request, form, next_url, tab))

    def post(self, request):
        from django.contrib import messages

        settings = UserSettings.load()
        # The tab is what scopes the form, so trust the POST's own marker — a
        # tab's Save must only ever write that tab's fields.
        tab = active_settings_tab(request.POST.get("tab"))
        form = UserSettingsForm(request.POST, instance=settings, tab=tab)
        next_url = _safe_next(request, request.POST.get("next"))
        if form.is_valid():
            form.save()
            label = {"display": "Display", "features": "Feature"}.get(tab, "Settings")
            messages.success(request, f"{label} settings saved.")
            return redirect(next_url or f"{reverse('core:settings')}?tab={tab}")
        return render(request, "core/settings.html",
                      self._context(request, form, next_url, tab))


class SettingsFieldView(View):
    """Save one settings control the moment it changes (the settings panes carry
    no Save button — see ``core.settings_fields``).

    JSON in the sense that the *answer* is JSON; the request is an ordinary form
    POST, so each field's own widget parses its value exactly as it would in a
    full submit. A validation failure answers 400 with the field's own message —
    the page shows it beside the control and puts the control back, so what's on
    screen never claims a setting that wasn't stored."""

    def post(self, request):
        from .settings_fields import SettingsFieldError, save_field

        scope = request.POST.get("scope", "")
        field = request.POST.get("field", "")
        try:
            form = save_field(scope, field, request.POST)
        except SettingsFieldError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)

        if form.errors:
            # Field errors first — they name the setting the owner just touched.
            # __all__ errors (EmailSettingsForm's "add a connection first") only
            # surface when the field itself validated.
            errors = form.errors.get(field) or form.non_field_errors()
            return JsonResponse(
                {"ok": False, "error": errors[0] if errors else "That didn't save."},
                status=400,
            )
        # Echo what was actually stored, so the control can correct itself when
        # the form normalised the input (a blank invite title becomes the
        # built-in default; a hex is lower-cased).
        value = form.cleaned_data.get(field)
        if hasattr(value, "pk"):          # a model choice — send its id
            value = value.pk
        return JsonResponse({"ok": True, "value": value}, encoder=DjangoJSONEncoder)


class SetThemeView(View):
    """Quick Light/Dark/Auto switch in the navbar's More dropdown. POST-only;
    persists to the UserSettings singleton and bounces back to the page the
    toggle was used on (same-origin only, via ``_safe_next``)."""

    def post(self, request):
        theme = request.POST.get("theme")
        if theme in {choice for choice, _ in UserSettings.THEME_CHOICES}:
            settings = UserSettings.load()
            settings.theme = theme
            settings.save()
        next_url = _safe_next(request, request.POST.get("next"))
        return redirect(next_url or f"{reverse('core:settings')}?tab=display")


# "signin" and "email" carry no UserSettings fields of their own, so the valid
# set is wider than UserSettingsForm.TABS. Sign-in is offered even without an IdP
# configured — that is where the password lives, and where we explain how to turn
# SSO on.
SETTINGS_TABS = ("display", "features", "email", "calendar", "api", "jobs", "signin", "about")


def active_settings_tab(raw):
    """Resolve a ``?tab=`` value, falling back to the first tab."""
    return raw if raw in SETTINGS_TABS else SETTINGS_TABS[0]


class BitGigsLoginView(LoginView):
    """Django's LoginView, plus one fact the template needs: whether the owner can
    sign in with a password at all. If they turned it off, showing the password
    box would just be a dead end — so the page offers the IdP and a way back in
    from the server console instead.

    (Not decorated: LoginView is already exempt from LoginRequiredMiddleware, and
    this doesn't override dispatch, so the exemption is inherited.)"""

    template_name = "registration/login.html"

    def get_context_data(self, **kwargs):
        from django.conf import settings as django_settings
        from django.contrib.auth.models import User
        context = super().get_context_data(**kwargs)
        owner = User.objects.order_by("pk").first()
        usable = owner.has_usable_password() if owner else True
        # Without an IdP the password form is the only door, so never hide it —
        # that would lock the owner out of their own app.
        context["show_password_form"] = usable or not django_settings.SSO_ENABLED
        context["password_login_disabled"] = not usable
        # NB: the login page is public, so it must never render the owner's
        # username — the console-recovery hint uses a generic placeholder instead.
        # Drives the recovery modal: an emailed reset link, or console-only.
        context["password_reset_enabled"] = password_reset_available()
        return context

    # Django logs nothing about sign-ins, which for a self-hosted app on the open
    # internet is the one trail worth having: a run of failures from an address
    # that isn't the owner is the whole signal. A failure is therefore WARNING —
    # it survives a deployment that raised the level to quieten the log — while a
    # success is routine INFO. The attempted username is recorded (as sshd does);
    # the submitted password never is.
    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info("Sign-in succeeded for %r from %s",
                    self.request.user.get_username(), client_ip(self.request))
        return response

    def form_invalid(self, form):
        # form.cleaned_data is unavailable on some failures; the raw field is not.
        attempted = (form.data.get("username") or "").strip()
        logger.warning("Sign-in failed for %r from %s", attempted, client_ip(self.request))
        return super().form_invalid(form)


def email_context(switch_form=None, roles_form=None, conn_form=None,
                  modal_open=False, edit_pk=None):
    """Email-tab state: the global mail settings split into two cards (the master
    switch and the role map), the list of stored connections shown as read-only
    summaries, the connection edit form that lives in a shared modal, and the
    provider presets.

    ``modal_open`` re-opens the connection modal (with ``conn_form``'s errors)
    after a save bounced on validation; ``edit_pk`` names the connection being
    edited so the modal posts back to the right row."""
    from .mail import PRESETS
    from .forms import MailConnectionForm

    config = EmailSettings.load()
    system_conn = config.connection_for(EmailSettings.ROLE_SYSTEM)
    return {
        "email_settings": config,
        "email_configured": config.is_configured,
        # The master arm's own state, so it can't be keyed on is_configured —
        # that folds the master switch in, and the box would then stay red
        # until the switch it reports on had already been saved.
        "email_has_connection": bool(system_conn and system_conn.is_configured),
        "email_switch_form": switch_form or EmailSettingsForm(
            instance=config, section=EmailSettingsForm.SECTION_SWITCHES),
        "email_roles_form": roles_form or EmailSettingsForm(
            instance=config, section=EmailSettingsForm.SECTION_ROLES),
        "email_conn_form": conn_form or MailConnectionForm(),
        "email_connections": list(MailConnection.objects.all()),
        "email_presets": PRESETS,
        "email_modal_open": modal_open,
        "email_edit_pk": edit_pk,
        "email_failures_unseen": EmailLog.objects.failures_unseen().exists(),
    }


def _validated_send_to(request):
    """Read the optional ``send_to`` off a mail-test POST.

    Returns ``(address, error_response)`` — blank is legal and means "test the
    connection but don't actually send anything", so only a *malformed* address
    produces the 400.
    """
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    send_to = (request.POST.get("send_to") or "").strip()
    if send_to:
        try:
            validate_email(send_to)
        except ValidationError:
            return "", JsonResponse(
                {"error": f"'{send_to}' is not a valid email address."}, status=400
            )
    return send_to, None


def _signin_invalid_render(request, ctx, **extra):
    """Re-render the settings page on the Sign-in tab with a bounced form.

    *extra* carries the form plus its ``open_*_modal`` flag, so the errors land
    where the user is instead of on a closed modal.
    """
    return render(request, "core/settings.html", {
        "form": UserSettingsForm(instance=UserSettings.load(), tab="display"),
        "next_url": None,
        "active_tab": "signin",
        **ctx,
        **extra,
    })


def _email_invalid_render(request, *, switch_form=None, roles_form=None,
                          conn_form=None, modal_open=False, edit_pk=None):
    """Re-render the settings page on the Email tab with a bounced form."""
    return render(request, "core/settings.html", {
        "form": UserSettingsForm(instance=UserSettings.load(), tab="display"),
        "next_url": None,
        "active_tab": "email",
        **sign_in_context(request.user),
        **email_context(switch_form=switch_form, roles_form=roles_form,
                        conn_form=conn_form, modal_open=modal_open, edit_pk=edit_pk),
    })


class EmailSettingsView(View):
    """Save the Email tab's global settings — the master switch, password-reset
    toggle and the role→connection map. Its own POST endpoint for the same reason
    the Sign-in tab is: its form can't nest inside the UserSettings form. The two
    cards post with a ``section`` marker so each saves only its own fields."""

    def post(self, request):
        from django.contrib import messages

        config = EmailSettings.load()
        section = request.POST.get("section")
        form = EmailSettingsForm(request.POST, instance=config, section=section)
        if form.is_valid():
            form.save()
            messages.success(request, "Email settings saved.")
            return redirect(f"{reverse('core:settings')}?tab=email")
        if section == EmailSettingsForm.SECTION_ROLES:
            return _email_invalid_render(request, roles_form=form)
        return _email_invalid_render(request, switch_form=form)


class MailConnectionSaveView(View):
    """Create or update one mail connection. A blank ``pk`` creates; otherwise the
    named connection is edited in place. On the first connection, mark it default
    so an unassigned role has something to fall back to."""

    def post(self, request):
        from django.contrib import messages
        from .forms import MailConnectionForm

        pk = parse_int_param(request.POST.get("pk"))
        instance = MailConnection.objects.filter(pk=pk).first() if pk else None
        is_new = instance is None
        form = MailConnectionForm(request.POST, instance=instance or MailConnection())
        if form.is_valid():
            conn = form.save(commit=False)
            if is_new and not MailConnection.objects.exists():
                conn.is_default = True
            # A changed connection invalidates its stored test result.
            if form.has_changed():
                conn.last_test_at = None
                conn.last_test_ok = None
            conn.save()
            messages.success(request, f"Connection “{conn.name}” saved.")
            target = f"{reverse('core:settings')}?tab=email"
            if request.POST.get("run_test"):
                target += f"&test={conn.pk}"
            return redirect(target)
        return _email_invalid_render(request, conn_form=form, modal_open=True,
                                     edit_pk=pk or "")


class MailConnectionDeleteView(View):
    """Delete a mail connection. Any role still pointing at it falls back to the
    default (the FK is ``SET_NULL``)."""

    def post(self, request):
        from django.contrib import messages

        pk = parse_int_param(request.POST.get("pk"))
        conn = MailConnection.objects.filter(pk=pk).first()
        if conn:
            name, was_default = conn.name, conn.is_default
            conn.delete()
            # Keep a default alive: promote another connection if the deleted one
            # was it, so unassigned roles still resolve.
            if was_default:
                nxt = MailConnection.objects.order_by("pk").first()
                if nxt:
                    nxt.is_default = True
                    nxt.save(update_fields=["is_default", "updated_at"])
            messages.success(request, f"Connection “{name}” deleted.")
        return redirect(f"{reverse('core:settings')}?tab=email")


class MailConnectionDefaultView(View):
    """Flag a connection as the default one (used by any role not pointed
    elsewhere). ``MailConnection.save`` demotes the previous default."""

    def post(self, request):
        from django.contrib import messages

        pk = parse_int_param(request.POST.get("pk"))
        conn = MailConnection.objects.filter(pk=pk).first()
        if conn:
            conn.is_default = True
            conn.save(update_fields=["is_default", "updated_at"])
            messages.success(request, f"“{conn.name}” is now the default connection.")
        return redirect(f"{reverse('core:settings')}?tab=email")


class EmailClearView(View):
    """Reset all mail configuration to a fresh, disabled state — master switch
    off, role map cleared, every stored connection dropped. A one-click way out of
    a broken setup, behind a JS confirm since it discards data."""

    def post(self, request):
        from django.contrib import messages

        EmailSettings.load().reset_to_fresh()
        messages.success(request, "Email configuration cleared.")
        return redirect(f"{reverse('core:settings')}?tab=email")


class EmailLogView(View):
    """The email activity log: every send attempt, most recent first, with the
    reason a failure failed. Read-only; the only mutation reachable from here is
    the Dismiss control, which posts to ``EmailLogAckView``."""

    def get(self, request):
        entries = EmailLog.objects.all()[:EmailLog.PRUNE_KEEP]
        return render(request, "core/email_log.html", {
            "entries": entries,
            "has_unseen_failures": EmailLog.objects.failures_unseen().exists(),
        })


class EmailLogAckView(View):
    """Dismiss the outstanding failures — stamps ``acknowledged_at`` on every
    unseen failure, which is what clears the dashboard banner. Reachable from
    both the banner and the log page; honours a same-origin ``next``."""

    def post(self, request):
        EmailLog.objects.failures_unseen().update(acknowledged_at=timezone.now())
        target = _safe_next(request, request.POST.get("next"))
        return redirect(target or reverse("core:email-log"))


class EmailTestView(View):
    """Run the staged connection test and return the per-stage results as JSON.

    POST-only and behind the site-wide login gate, because it reaches out to an
    arbitrary host:port with the stored credentials — exactly the kind of thing
    that should not be reachable by following a link.
    """

    def post(self, request):
        from .mail import run_and_record

        send_to, invalid = _validated_send_to(request)
        if invalid:
            return invalid
        # Which connection to test: the named one, else the system default.
        pk = parse_int_param(request.POST.get("connection"))
        config = MailConnection.objects.filter(pk=pk).first() if pk else None
        if pk and config is None:
            return JsonResponse({"error": "That connection no longer exists."}, status=400)
        result = run_and_record(config=config, send_to=send_to or None)
        # Report the live unseen-failure state too, so the tab's "Email log"
        # alert dot can flip the moment a test send fails, without a reload.
        return JsonResponse({
            **result.as_dict(),
            "connection_pk": config.pk if config else None,
            "failures_unseen": EmailLog.objects.failures_unseen().exists(),
        })


class EmailProbeView(View):
    """Live host/port check for the Email settings modal.

    Fired (debounced) as the operator types the server hostname: it resolves the
    host and — when a port is given — checks that something is listening. It is
    the fast, field-level half of the full staged test, sharing its helpers so
    the words match; like EmailTestView it reaches out to an arbitrary host:port,
    so it is POST-only behind the login gate. It sends nothing and holds no
    connection open.
    """

    def post(self, request):
        from core.utils import parse_int_param

        from .mail import check_port, resolve_host

        host = (request.POST.get("host") or "").strip()
        port = parse_int_param(request.POST.get("port"))
        if not (port and 1 <= port <= 65535):
            port = None

        if not host:
            return JsonResponse({"host": None, "port": None})

        dns = resolve_host(host, port)
        result = {"host": {"status": "ok" if dns.ok else "failed",
                           "detail": dns.detail, "hint": dns.hint},
                  "port": None}
        if dns.ok and port:
            # Cap the wait low — this is interactive, not the full test.
            tcp = check_port(host, port, 5)
            result["port"] = {"status": "ok" if tcp.ok else "failed",
                              "detail": tcp.detail, "hint": tcp.hint, "port": port}
        return JsonResponse(result)


# ─────────────────────────────────────────────────────────────────────────────
# Password reset
#
# Django already routes /accounts/password_reset/ (contrib.auth.urls is included
# in config/urls.py), so these subclasses exist for three reasons the stock
# views can't cover: the flow must disappear entirely when mail isn't configured,
# the From header comes from EmailSettings rather than DEFAULT_FROM_EMAIL, and
# the request form is unauthenticated and therefore needs a rate limit.
# ─────────────────────────────────────────────────────────────────────────────

def password_reset_available():
    """Reset is only offered when mail actually works *and* the operator left it
    on. Otherwise the login page points at ``manage.py changepassword``."""
    config = EmailSettings.load()
    return config.is_configured and config.allow_password_reset


# Per-IP budget for reset requests. The form is public and each submit sends
# mail, so an unbounded one is both a mail-bomb and a user-enumeration oracle.
RESET_RATE_LIMIT = 5
RESET_RATE_WINDOW = 60 * 60  # seconds


def _reset_rate_key(request):
    """Cache key for the per-IP reset budget. See ``core.utils.client_ip`` for
    why the proxy header is only honoured when the operator asks for it."""
    return f"pwreset:{client_ip(request)}"


@method_decorator(login_not_required, name="dispatch")
class BitGigsPasswordResetView(auth_views.PasswordResetView):
    """The 'email me a reset link' form."""

    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    html_email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = "/accounts/password_reset/done/"

    def dispatch(self, request, *args, **kwargs):
        if not password_reset_available():
            return redirect("login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        from django.contrib import messages
        from django.core.cache import cache

        key = _reset_rate_key(self.request)
        used = cache.get(key, 0)
        if used >= RESET_RATE_LIMIT:
            messages.error(
                self.request,
                "Too many reset requests from this address. Wait an hour and try "
                "again, or reset from the server console.",
            )
            return redirect("login")
        # add() only sets the TTL on the first request, so the window is fixed
        # from the first attempt rather than sliding with each one.
        cache.add(key, 0, RESET_RATE_WINDOW)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, RESET_RATE_WINDOW)

        # The From header belongs to the operator's mail configuration, not to
        # DEFAULT_FROM_EMAIL, which BitGigs never sets.
        from .mail import from_address
        self.from_email = from_address()
        self.extra_email_context = {
            # Mail clients don't support CSS variables, so the HTML email needs
            # the accent as a literal rather than a token.
            "accent_color": UserSettings.load().accent_color,
            # django.contrib.sites is installed (allauth requires it), so Django
            # would otherwise build the link from the Site row — which nobody
            # edits, leaving every reset link pointing at example.com. The real
            # host is the right answer, and get_host() is already validated
            # against ALLOWED_HOSTS, so it can't be spoofed into a phishing link.
            "domain": self.request.get_host(),
            "site_name": "BitGigs",
            "protocol": "https" if self.request.is_secure() else "http",
        }
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["minimal_chrome"] = True
        return context


@method_decorator(login_not_required, name="dispatch")
class BitGigsPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["minimal_chrome"] = True
        return context


@method_decorator(login_not_required, name="dispatch")
class BitGigsPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Where the emailed link lands. Deliberately *not* gated on
    ``password_reset_available()``: a link already in someone's inbox should
    still work if the operator turned mail off in the meantime."""

    template_name = "registration/password_reset_confirm.html"
    success_url = "/accounts/reset/done/"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["minimal_chrome"] = True
        return context


@method_decorator(login_not_required, name="dispatch")
class BitGigsPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["minimal_chrome"] = True
        return context


def sign_in_context(user):
    """Sign-in card state for the settings page: is an IdP identity linked, and is
    password sign-in still available."""
    from allauth.socialaccount.models import SocialAccount
    from django.contrib.auth.forms import SetPasswordForm
    from .forms import AccountDetailsForm
    linked = SocialAccount.objects.filter(user=user).first()
    email_config = EmailSettings.load()
    return {
        "sso_account": linked,
        "sso_linked": linked is not None,
        "has_usable_password": user.has_usable_password(),
        "set_password_form": SetPasswordForm(user),  # drives the set/change modal
        "account_details_form": AccountDetailsForm(instance=user),
        "password_reset_enabled": password_reset_available(),
        # Split out so the Sign-in tab can mirror the Email tab's reset state
        # precisely — "allowed but no mail server yet" reads differently from "off".
        "password_reset_allowed": email_config.allow_password_reset,
        "email_configured": email_config.is_configured,
    }


@method_decorator(login_not_required, name="dispatch")
class SSOLaunchView(View):
    """Landing spot for the IdP's application tile (set it as the provider's
    Launch URL). Opening BitGigs from the IdP dashboard should *sign you in*, not
    dump you on a login page — the IdP already knows who you are.

    Starts allauth's login for you. allauth wants that as a POST (a GET provider
    login is open to login-CSRF), so this page submits itself."""

    def get(self, request):
        from allauth.socialaccount.models import SocialAccount
        from django.conf import settings as django_settings

        if not django_settings.SSO_ENABLED:
            return redirect("/accounts/login/")

        if request.user.is_authenticated:
            if SocialAccount.objects.filter(user=request.user).exists():
                return redirect("core:dashboard")  # already linked — just open the app
            # Signed in locally but never linked: this is the natural moment to
            # offer it, since the IdP just vouched for who you are.
            return render(request, "core/sso_launch.html",
                          {"process": "connect", "minimal_chrome": True})

        return render(request, "core/sso_launch.html",
                      {"process": "login", "minimal_chrome": True})


@method_decorator(login_not_required, name="dispatch")
class SSOEndIdPSessionView(View):
    """"Not you?" — end the session at the IdP.

    RP-initiated logout with no post_logout_redirect_uri, so nothing needs
    registering at the provider. It lands on the IdP's own signed-out page, which
    already offers everything needed from there: switch user, or launch BitGigs
    again (which re-opens the link prompt via SSOLaunchView).

    Asking the IdP to re-authenticate instead (prompt=login) is the tidier OIDC
    move, but authentik ignores it on repeat attempts — so just log out."""

    def post(self, request):
        from django.conf import settings as django_settings
        from django.contrib import messages
        from allauth.socialaccount.adapter import get_adapter
        from core.adapters import PENDING_SSO_SESSION_KEY

        request.session.pop(PENDING_SSO_SESSION_KEY, None)

        end_session_url = ""
        if django_settings.SSO_ENABLED:
            try:
                provider = get_adapter().get_provider(request, django_settings.SSO_PROVIDER_ID)
                end_session_url = provider.get_oauth2_adapter(request).openid_config.get(
                    "end_session_endpoint") or ""
            except Exception:  # discovery is a network call — never 500 over it
                # The owner is told the IdP was unreachable; only the log says why.
                logger.warning("SSO: OIDC discovery failed, cannot resolve "
                               "end_session_endpoint", exc_info=True)
                end_session_url = ""

        if not end_session_url:
            from .sso import get_brand
            messages.error(request, f"Could not reach {get_brand().name} to sign you out. Sign out "
                                    "there directly, then try again.")
            return redirect("core:settings" if request.user.is_authenticated else "/accounts/login/")
        return redirect(end_session_url)


def _pending_sso_identity(request):
    """The identity parked by the adapter, ready to display. Reads the claims the
    IdP actually sent rather than sociallogin.user — see core.adapters.claim."""
    from allauth.socialaccount.models import SocialLogin
    from core.adapters import PENDING_SSO_SESSION_KEY, claim

    data = request.session.get(PENDING_SSO_SESSION_KEY)
    if not data:
        return None, {}
    sociallogin = SocialLogin.deserialize(data)
    return sociallogin, {
        "sso_email": sociallogin.user.email,
        "sso_uid": sociallogin.account.uid,
        "sso_name": (claim(sociallogin, "name") or "").strip(),
    }


class SSOLinkConfirmView(View):
    """Confirm which IdP identity is about to be linked to this account.

    Without this, an already-signed-in IdP session makes the round-trip
    instant: you click Link and it binds whatever account the IdP had, with no
    chance to see which one."""

    def get(self, request):
        sociallogin, identity = _pending_sso_identity(request)
        if sociallogin is None:
            return redirect("core:settings")
        # Mid-flow: no navigation, so the round-trip can't be abandoned by accident.
        return render(request, "core/sso_link_confirm.html",
                      dict(identity, minimal_chrome=True))

    def post(self, request):
        from allauth.socialaccount.helpers import complete_social_login
        from core.adapters import LINK_CONFIRMED_SESSION_KEY, PENDING_SSO_SESSION_KEY

        sociallogin, _ = _pending_sso_identity(request)
        if sociallogin is None:
            return redirect("core:settings")

        request.session[LINK_CONFIRMED_SESSION_KEY] = True
        request.session.pop(PENDING_SSO_SESSION_KEY, None)
        return complete_social_login(request, sociallogin)


def _signin_tab_url(request=None):
    """Where a sign-in action returns to.

    Normally the Sign-in tab that hosts it, but the onboarding Review step reuses
    the same modals, so a same-origin ``next`` wins — otherwise saving a password
    mid-setup would bounce the user to a settings page the wizard funnel then
    redirects away from."""
    if request is not None:
        target = _safe_next(request, request.POST.get("next"))
        if target:
            return target
    return f"{reverse('core:settings')}?tab=signin"


class PasswordSignInView(View):
    """The settings page's sign-in actions: set/change the password, turn password
    sign-in off, or unlink the IdP.

    One invariant runs through all of them — **at least one way in must survive**.
    So the password can only be turned off while an IdP identity is linked, and the
    IdP can only be unlinked while a usable password exists. Turning the password
    off sets an unusable password, which is what makes ModelBackend refuse it; the
    account itself stays fully active."""

    def post(self, request):
        from django.contrib import messages
        from django.contrib.auth import update_session_auth_hash
        from django.contrib.auth.forms import SetPasswordForm

        from .sso import get_brand

        ctx = sign_in_context(request.user)
        action = request.POST.get("action")

        # The provider is whatever the operator configured, so every message names
        # it from the resolved branding rather than hardcoding one.
        provider = get_brand().name

        if action == "unlink_sso":
            if not ctx["sso_linked"]:
                return redirect(_signin_tab_url(request))
            if not ctx["has_usable_password"]:
                messages.error(request, f"Set a password before unlinking {provider} — "
                                        "otherwise you would have no way back in.")
                return redirect(_signin_tab_url(request))
            ctx["sso_account"].delete()
            messages.success(request, f"{provider} is no longer linked. Sign in with your password.")
            return redirect(_signin_tab_url(request))

        if action == "disable":
            if not ctx["sso_linked"]:
                messages.error(request, f"Link your {provider} account before turning off password "
                                        "sign-in — otherwise you would have no way back in.")
                return redirect(_signin_tab_url(request))
            request.user.set_unusable_password()
            request.user.save(update_fields=["password"])
            # Any change to the password rotates the session hash, which would log
            # the owner straight out of the session they're doing this from.
            update_session_auth_hash(request, request.user)
            messages.success(request, f"Password sign-in is off. Use {provider} from now on.")
            return redirect(_signin_tab_url(request))

        if action == "password_reset":
            # The same EmailSettings.allow_password_reset the Email tab owns.
            # It's a mail concern to configure and a sign-in concern to use, so
            # it's settable from both rather than read-only here with a link.
            config = EmailSettings.load()
            config.allow_password_reset = "allow_password_reset" in request.POST
            config.save(update_fields=["allow_password_reset"])
            messages.success(request, "Password reset by email is now on."
                             if config.allow_password_reset
                             else "Password reset by email is now off.")
            return redirect(_signin_tab_url(request))

        if action == "account_details":
            from .forms import AccountDetailsForm
            form = AccountDetailsForm(request.POST, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, "Account details updated.")
                return redirect(_signin_tab_url(request))
            return _signin_invalid_render(
                request, ctx, account_details_form=form, open_account_modal=True
            )

        if action == "set_password":
            form = SetPasswordForm(request.user, request.POST)
            if form.is_valid():
                had_one = ctx["has_usable_password"]
                form.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password changed." if had_one
                                 else "Password sign-in is on.")
                return redirect(_signin_tab_url(request))
            return _signin_invalid_render(
                request, ctx, set_password_form=form, open_password_modal=True
            )

        return redirect(_signin_tab_url(request))


# ── Onboarding step 1: claim the instance, then create the owner ─────────────
# Three pages, because the setup key gates everything that follows:
#   /onboarding/account/         the key, and nothing else
#   /onboarding/account/method/  the IdP or email+password (only when SSO is on)
#   /onboarding/account/email/   the email+password form
# The key is verified once and recorded in the session (setup_key.SESSION_FLAG);
# the later pages — and the SSO bootstrap in core.adapters — refuse to act
# without that flag, so nobody can skip straight to creating the owner.

@method_decorator(login_not_required, name="dispatch")
class _AccountStepView(View):
    """Shared guards: this whole step is gone once an owner exists.

    Only this class may define dispatch(). `login_not_required` is attached to the
    dispatch *method*, so a subclass that overrides it silently drops the marker —
    and LoginRequiredMiddleware would then bounce anonymous visitors out of the very
    pages that exist to be used while logged out. Vary behaviour with the two class
    attributes below instead.
    """

    requires_key = True   # must have cleared the setup-key gate
    requires_sso = False  # meaningless unless an IdP is configured

    def dispatch(self, request, *args, **kwargs):
        from django.conf import settings as django_settings
        from django.contrib.auth.models import User
        from core import setup_key
        if User.objects.exists():
            return redirect("core:onboarding" if request.user.is_authenticated else "/accounts/login/")
        if self.requires_sso and not django_settings.SSO_ENABLED:
            return redirect("core:onboarding-account-email")
        if self.requires_key and not request.session.get(setup_key.SESSION_FLAG):
            return redirect("core:onboarding-account")
        return super().dispatch(request, *args, **kwargs)

    def _context(self, request, **extra):
        return {
            "onboarding": True,
            "onboarding_first_step": True,
            "steps": ob.steps_for(request, "account"),
            "app_slogan": slogan(),
            **extra,
        }

    def _after_key(self, request):
        """Where to go once the key is accepted."""
        from django.conf import settings as django_settings
        return redirect("core:onboarding-account-method" if django_settings.SSO_ENABLED
                        else "core:onboarding-account-email")


class OnboardingAccountView(_AccountStepView):
    """The setup key — proof that whoever claims this install runs the server."""

    requires_key = False

    def get(self, request):
        from core import setup_key
        if request.session.get(setup_key.SESSION_FLAG):
            return self._after_key(request)
        setup_key.get_or_create_key()  # generates + prints it on the first visit
        return render(request, "core/onboarding_key.html", self._context(request))

    def post(self, request):
        from core import setup_key
        if not setup_key.check_key(request.POST.get("setup_key", "")):
            # Flagged on the field itself, like every other form in the app —
            # not as a page-level banner.
            return render(request, "core/onboarding_key.html", self._context(
                request,
                key_error="That setup key is not correct.",
                key_value=request.POST.get("setup_key", ""),
            ))
        request.session[setup_key.SESSION_FLAG] = True
        return self._after_key(request)


class OnboardingAccountMethodView(_AccountStepView):
    """The configured IdP, or a plain email + password account."""

    requires_sso = True

    def get(self, request):
        return render(request, "core/onboarding_method.html", self._context(request))


class OnboardingAccountEmailView(_AccountStepView):
    """Create the single admin account immediately, so the remaining logged-in
    steps can run."""

    def get(self, request):
        from .forms import OnboardingUserCreationForm
        return render(request, "core/onboarding_account.html",
                      self._context(request, form=OnboardingUserCreationForm()))

    def post(self, request):
        from django.contrib.auth import login
        from core import setup_key
        from .forms import OnboardingUserCreationForm
        form = OnboardingUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # Single-user app: the first (only) account is the admin/owner.
            user.is_staff = True
            user.is_superuser = True
            user.save()
            setup_key.clear_key()  # claimed — the key has done its job
            request.session.pop(setup_key.SESSION_FLAG, None)
            # Two backends are configured (password + allauth's), so the one to
            # log in with has to be named explicitly.
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("core:onboarding")
        return render(request, "core/onboarding_account.html", self._context(request, form=form))


class OnboardingAccountConfirmView(_AccountStepView):
    """Second leg of the SSO bootstrap: the IdP has told us who you are, but no
    account exists yet. Show the identity and let the operator approve it before
    it becomes the owner — claiming an instance shouldn't happen by accident."""

    requires_sso = True

    def get(self, request):
        sociallogin, identity = _pending_sso_identity(request)
        if sociallogin is None:
            return redirect("core:onboarding-account-method")
        return render(request, "core/onboarding_sso_confirm.html",
                      self._context(request, **identity))

    def post(self, request):
        from allauth.socialaccount.helpers import complete_social_login
        from core.adapters import BOOTSTRAP_CONFIRMED_SESSION_KEY

        sociallogin, _ = _pending_sso_identity(request)
        if sociallogin is None:
            return redirect("core:onboarding-account-method")

        # Re-enter allauth's login flow. The adapter runs again, sees the flag,
        # and this time creates the owner instead of bouncing back here.
        request.session[BOOTSTRAP_CONFIRMED_SESSION_KEY] = True
        return complete_social_login(request, sociallogin)


class OnboardingRootView(View):
    """Entry point — resume wherever the user actually is on their chosen path."""

    def get(self, request):
        draft = ob.draft_data(request)
        cov = ob.coverage(request)
        # Not chosen a path yet. The `imported_anything` guard matters when a
        # session was lost mid-import: don't send someone whose database is
        # already half-populated back to a choice they made.
        if "start" not in draft and not cov.imported_anything:
            return redirect(ob.URLS["start"])
        if cov.can_finish:
            return redirect(ob.URLS["review"])
        if cov.method == "import" and not cov.imported_anything:
            return redirect("core:onboarding-import")
        for key in ob.DRAFT_KEYS:
            if key not in draft and not getattr(cov, key).covered:
                return redirect(ob.URLS[key])
        # Everything's been touched but gaps remain — Review names them.
        return redirect(ob.URLS["review"])


class OnboardingStartView(View):
    """Onboarding step 2 — restore an export, or set everything up by hand.

    The choice is advisory, not a lock: it decides where Continue goes and how
    Review words itself, but either path stays reachable throughout."""

    METHODS = ("import", "scratch")

    def _context(self, request, error=""):
        return {
            "onboarding": True,
            "steps": ob.steps_for(request, "start"),
            "chosen": ob.draft_data(request).get("start", {}).get("method", ""),
            "error": error,
        }

    def get(self, request):
        return render(request, "core/onboarding_start.html", self._context(request))

    def post(self, request):
        method = request.POST.get("setup_method", "")
        if method not in self.METHODS:
            return render(request, "core/onboarding_start.html",
                          self._context(request, error="Please choose how you'd like to start."))
        ob.store_step(request, "start", {"method": method})
        if method == "import":
            return redirect("core:onboarding-import")
        return redirect(ob.URLS["tax"])


class OnboardingTaxView(View):
    def _context(self, request, form):
        return {"tax_form": form, "onboarding": True, "steps": ob.steps_for(request, "tax")}

    def get(self, request):
        stored = ob.draft_data(request).get("tax")
        form = TaxProfileForm(data=stored) if stored else TaxProfileForm()
        return render(request, "core/onboarding_tax.html", self._context(request, form))

    def post(self, request):
        # Save whatever's entered (even partial) and navigate — validation is
        # deferred to Finish, so the user can fill steps in any order.
        ob.store_step(request, "tax", request.POST)
        return redirect(ob.resolve_goto(request, "tax"))


class OnboardingWorkplaceView(View):
    """Onboarding step 3 — the workplace, plus the contract's optional label as a
    field that the page reveals once the workplace is named."""

    def _context(self, request, form, contract_form, cal_form):
        return {
            "form": form,
            "contract_form": contract_form,
            "cal_form": cal_form,
            "onboarding": True,
            "steps": ob.steps_for(request, "workplace"),
            **ob.calendar_readiness(),
        }

    def get(self, request):
        from workplaces.forms import WorkplaceForm
        stored = ob.draft_data(request).get("workplace")
        form = WorkplaceForm(data=stored) if stored else WorkplaceForm()
        contract_form = ob._build_contract_form(stored)
        cal_form = ob._build_calendar_config_form(stored)
        return render(request, "workplaces/workplace_form.html",
                      self._context(request, form, contract_form, cal_form))

    def post(self, request):
        ob.store_step(request, "workplace", request.POST)
        # When advancing to the next step and the user opted into calendar invites
        # without a mail server yet, detour through the hidden email step first.
        # An explicit jump (onboarding_goto=<step>) is honoured as-is.
        if request.POST.get("onboarding_goto", "next") == "next" and ob.wants_email_step(request):
            return redirect("core:onboarding-email")
        return redirect(ob.resolve_goto(request, "workplace"))


class OnboardingEmailView(View):
    """Hidden step slotted between Workplace and Pay Terms when the user opts into
    calendar invites without a mail server yet. Routed under /onboarding/ so the
    funnel exempts it, and reuses Settings → Email's form, presets, live probe and
    staged test verbatim (via the shared `_email_form_body.html`). Always skippable
    — email can be finished later on Settings → Email; invites just won't send
    until it is."""

    def _context(self, request, form=None, form_invalid=False):
        from .forms import MailConnectionForm
        from .mail import PRESETS
        return {
            "onboarding": True,
            # A hidden step, so the indicator keeps Workplace as the active context.
            "steps": ob.steps_for(request, "workplace"),
            "email_conn_form": form or MailConnectionForm(
                instance=MailConnection.default(), require_name=False,
                initial={"name": "Default"},
            ),
            "email_presets": PRESETS,
            "email_form_invalid": form_invalid,
        }

    def get(self, request):
        # Only meaningful as part of the invite opt-in; otherwise fall through.
        if not ob.invites_opted_in(request):
            return redirect("core:onboarding-terms")
        return render(request, "core/onboarding_email.html", self._context(request))

    def post(self, request):
        from django.contrib import messages
        from .forms import MailConnectionForm

        conn = MailConnection.default()
        form = MailConnectionForm(request.POST, instance=conn or MailConnection(),
                                  require_name=False)
        if not form.is_valid():
            return render(request, "core/onboarding_email.html",
                          self._context(request, form, form_invalid=True))
        connection = form.save(commit=False)
        if conn is None:
            connection.is_default = True
        if form.has_changed():
            connection.last_test_at = None
            connection.last_test_ok = None
        connection.save()
        # Turn mail on so invites can send; the roles fall back to this default.
        config = EmailSettings.load()
        if not config.enabled:
            config.enabled = True
            config.save(update_fields=["enabled", "updated_at"])
        messages.success(request, "Email settings saved.")
        return redirect("core:onboarding-terms")


class OnboardingEmailTestView(View):
    """Dry-run staged test against the **typed** values, without saving them — so
    the user can verify the server before committing, with no reload. Builds a
    transient MailConnection from the posted form and runs the same staged
    diagnosis; nothing is persisted (no config write, no EmailLog row). Under
    /onboarding/ so the AJAX escapes the funnel."""

    def post(self, request):
        from .forms import MailConnectionForm

        from .mail import diagnose

        form = MailConnectionForm(request.POST, instance=MailConnection(),
                                  require_name=False)
        if not form.is_valid():
            return JsonResponse(
                {"error": "Fill in the server details above before testing."}, status=400
            )
        config = form.save(commit=False)  # transient — never persisted

        send_to, invalid = _validated_send_to(request)
        if invalid:
            return invalid
        return JsonResponse(diagnose(config, send_to=send_to or None).as_dict())


class OnboardingEmailProbeView(EmailProbeView):
    """The live host/port probe, under /onboarding/ so it's reachable mid-wizard
    (the /settings/ endpoint is behind the onboarding funnel)."""


class OnboardingContractEditView(View):
    """Edit an already-created contract's **label + calendar invites** from the
    Review screen. Every workplace Review lists is a real DB row (an import made
    it — defined or blank), so its contract can be edited here directly; the
    from-scratch workplace isn't listed (it's edited on the Workplace step). Saves
    immediately — like the placeholder-terms repair — and returns to Review. Reuses
    the contract form + shared invite partial with an ``onboarding`` flag. Pay
    terms keep their own repair flow; this touches only label + invites.
    Funnel-exempt via the /onboarding/ prefix."""

    def _get_contract(self, cpk):
        from django.shortcuts import get_object_or_404
        from workplaces.models import WorkplaceContract
        return get_object_or_404(WorkplaceContract, pk=cpk)

    def _forms(self, contract, data=None):
        from workplaces.forms import WorkplaceContractForm
        from workplaces.views import _contract_calendar_form
        form = WorkplaceContractForm(data, instance=contract, workplace=contract.workplace)
        return form, _contract_calendar_form(contract, data)

    def _context(self, request, contract, form, cal_form):
        from workplaces.views import _calendar_readiness
        return {
            "form": form, "cal_form": cal_form,
            "workplace": contract.workplace, "contract": contract,
            "onboarding": True,
            "steps": ob.steps_for(request, "review"),
            **_calendar_readiness(),
        }

    def get(self, request, cpk):
        contract = self._get_contract(cpk)
        form, cal_form = self._forms(contract)
        return render(request, "workplaces/contract_form.html",
                      self._context(request, contract, form, cal_form))

    def post(self, request, cpk):
        from workplaces.views import _save_contract_calendar
        contract = self._get_contract(cpk)
        form, cal_form = self._forms(contract, request.POST)
        if form.is_valid() and cal_form.is_valid():
            updated = form.save(commit=False)
            updated.workplace = contract.workplace
            updated.save()
            _save_contract_calendar(updated, cal_form)
            return redirect("core:onboarding-review")
        return render(request, "workplaces/contract_form.html",
                      self._context(request, contract, form, cal_form))


class OnboardingTermsView(View):
    """Onboarding step 5 — how the workplace pays.

    Two modes. Normally it stores into the draft like every other step and Review
    commits. But when an import left a stub term set — written so a file's shifts
    had a contract to attach to — this step overwrites that real row **in place
    and immediately**: it already exists in the database, and replacing it is the
    only way the imported shifts stop pricing at zero.

    The stub is an implementation detail the user never needs to hear about, so
    the form is presented blank, exactly like entering terms for any new job."""

    def _stub(self, request):
        """The placeholder term set this step should repair, if any."""
        return ob.placeholder_termsets().first()

    def _context(self, request, form, stub=None):
        return {
            "form": form,
            "workplace": stub.contract.workplace if stub else ob.transient_workplace(request),
            "contract": stub.contract if stub else ob.transient_contract(request),
            "onboarding": True,
            "fixing_placeholder": bool(stub),
            "steps": ob.steps_for(request, "terms"),
            "tax_profile_json": ob.tax_profile_json(request),
            "month_choices": ob.MONTH_CHOICES,
            "existing_terms_json": "[]",
        }

    def get(self, request):
        from workplaces.forms import ContractTermSetForm
        stub = self._stub(request)
        if stub:
            # Unbound: a blank form with the normal defaults. Binding it to the
            # stub would prefill the placeholder's 0 kr and year-2000 date, which
            # is worse than useless as a starting point.
            form = ContractTermSetForm(contract=stub.contract)
            return render(request, "workplaces/termset_form.html",
                          self._context(request, form, stub))

        stored = ob.draft_data(request).get("terms")
        form = ContractTermSetForm(data=stored, contract=None) if stored else ContractTermSetForm(contract=None)
        return render(request, "workplaces/termset_form.html", self._context(request, form))

    def post(self, request):
        from workplaces.forms import ContractTermSetForm
        stub = self._stub(request)
        if stub:
            form = ContractTermSetForm(data=request.POST, contract=stub.contract, instance=stub)
            if not form.is_valid():
                return render(request, "workplaces/termset_form.html",
                              self._context(request, form, stub))
            form.save()
            # Another workplace may still be waiting; Review routes to the next.
            return redirect(ob.URLS["review"])

        # Terms deliberately does NOT finish: it stores and navigates like every
        # other data step, and Review is the only page that commits.
        ob.store_step(request, "terms", request.POST)
        return redirect(ob.resolve_goto(request, "terms"))


class OnboardingResetView(View):
    """Start over: discard everything the wizard has gathered and return to step 2.

    Steps 3-5 are only a draft, but the import path writes as it goes — so a
    genuine restart has to clear the imported rows too, or "start over" would
    leave the workplaces and shifts it was meant to discard. Deliberately scoped
    to setup: once onboarding is finished this refuses, so it can never become a
    wipe button for a live install."""

    def post(self, request):
        from django.contrib import messages
        from django.db import transaction as db_transaction
        from core.models import EmailSettings, TaxProfile
        from shifts.models import PlannedShift, Shift
        from workplaces.models import Workplace

        # Guard on having *left* the wizard, not on the database completion
        # signal: a full import satisfies that signal while the user is still on
        # Review, and undoing an import they didn't want is the main reason this
        # button exists. OnboardingReviewView turns finished users away, so the
        # form that posts here is unreachable once setup is done.
        if request.session.get("onboarding_complete"):
            messages.error(request, "Setup is already finished, so there's nothing to restart.")
            return redirect("core:dashboard")

        with db_transaction.atomic():
            Shift.objects.all().delete()
            PlannedShift.objects.all().delete()
            Workplace.objects.all().delete()   # cascades contracts + term sets
            TaxProfile.objects.all().delete()
            # The hidden email step writes the mail server as it goes (like the
            # import path), so a genuine restart has to clear it too.
            EmailSettings.load().reset_to_fresh()
            ob.clear_draft(request)

        request.session.pop("import_data", None)
        messages.success(request, "Cleared — let's start again.")
        return redirect(ob.URLS["start"])


class OnboardingReviewView(View):
    """Onboarding step 6 — what setup has, what it still needs, and Finish.

    The single exit for both paths. On the scratch path this previews a draft
    that Finish then writes; after an import it reports rows already saved. Only
    tax details and pay terms gate Finish — shift counts are shown because they
    reassure, never because they block."""

    def _context(self, request):
        cov = ob.coverage(request)
        return {
            "onboarding": True,
            "steps": ob.steps_for(request, "review"),
            "cov": cov,
            "missing": cov.missing(),
            "urls": {key: reverse(ob.URLS[key]) for key in ("tax", "workplace", "terms")},
            "import_url": reverse("core:onboarding-import"),
            "reset_url": reverse("core:onboarding-reset"),
            # The account modals are the settings page's, reused verbatim; they
            # post to core:password-signin and come back here via `next`.
            "signin_return": reverse(ob.URLS["review"]),
            **sign_in_context(request.user),
        }

    def get(self, request):
        # Finished users have no business back here — and this is the only page
        # that renders the Start over form, so turning them away keeps that out of
        # reach too. Keyed on the session flag (set by mark_complete when they
        # pressed Finish), not on the database signal: a full import satisfies that
        # signal while the user is legitimately still standing here.
        if request.session.get("onboarding_complete"):
            return redirect("core:dashboard")
        return render(request, "core/onboarding_review.html", self._context(request))

    def post(self, request):
        from django.contrib import messages

        result = ob.commit_setup(request)
        if result is True:
            ob.mark_complete(request)
            messages.success(request, "You're all set up — welcome to BitGigs!")
            return redirect("core:dashboard")
        # Defence in depth: Finish is disabled in the template when gaps remain.
        step_key, msg = result
        messages.error(request, msg)
        return redirect(ob.URLS[step_key])


# ── Onboarding: restore a BitGigs export instead of typing it in ─────────────
# Entered from the Start step (2), and again from Review when one file didn't
# cover everything — importing is repeatable, and each run sees the workplaces
# the previous one created. These views are thin wrappers over data_io.services,
# the same code path Settings → Import uses; only the entry/exit URLs differ.
# They live under /onboarding/ so the middleware exemption already covers them.
#
# Unlike the wizard's own steps this writes immediately, so it always exits to
# Review rather than deciding anything about completion itself.

def _import_error_config():
    from data_io.views import IMPORT_ERRORS, MAX_IMPORT_SIZE
    return IMPORT_ERRORS, MAX_IMPORT_SIZE


class OnboardingImportView(View):
    """Upload step: take the export file and show the same review page the
    Settings → Import flow uses."""

    def _context(self, request):
        return {"onboarding": True, "steps": ob.steps_for(request, "start")}

    def get(self, request):
        return render(request, "core/onboarding_import.html", self._context(request))

    def post(self, request):
        from django.contrib import messages
        from data_io import services as io_services
        from workplaces.models import Workplace
        IMPORT_ERRORS, MAX_IMPORT_SIZE = _import_error_config()

        uploaded = request.FILES.get("import_file")
        if not uploaded:
            messages.error(request, "Please choose a BitGigs export file to import.")
            return redirect("core:onboarding-import")
        if uploaded.size > MAX_IMPORT_SIZE:
            messages.error(request, "Import failed: the file is larger than 10 MB.")
            return redirect("core:onboarding-import")

        try:
            content = uploaded.read().decode("utf-8")
            data = io_services.parse_import_file(content)
            conflicts = io_services.detect_workplace_conflicts(data)
            contract_overlaps = {
                name: clashes
                for name, clashes in io_services.detect_contract_overlaps(data).items()
                if name in conflicts
            }
            summary = io_services.import_summary(data)
        except (UnicodeDecodeError, *IMPORT_ERRORS) as e:
            messages.error(request, f"Import failed: {e}")
            return redirect("core:onboarding-import")

        request.session["import_data"] = content
        return render(request, "data_io/import_confirm.html", {
            "conflicts": conflicts,
            "conflict_rows": io_services.describe_conflicts(data, conflicts),
            # Must be the real list, not []: a second import (offered from Review)
            # runs against workplaces the first one created, and the user needs the
            # "map to existing" option for them.
            "existing_workplaces": Workplace.objects.all(),
            "contract_overlaps": contract_overlaps,
            "summary": summary,
            "data": data,
            "onboarding": True,
            "steps": ob.steps_for(request, "start"),
            "confirm_url": reverse("core:onboarding-import-confirm"),
            # Back out to whichever page the user came from.
            "cancel_url": reverse(ob.URLS["review"] if ob.coverage(request).imported_anything
                                  else ob.URLS["start"]),
        })


class OnboardingImportConfirmView(View):
    """Write the reviewed import, then hand off to Review.

    Never decides completion itself: Review is the single exit, so importing a
    file that covers everything still shows the user what landed."""

    def post(self, request):
        from django.contrib import messages
        from django.core.exceptions import ValidationError
        from data_io import services as io_services
        IMPORT_ERRORS, _ = _import_error_config()

        content = request.session.get("import_data")
        if not content:
            messages.error(request, "No import data found. Please upload the file again.")
            return redirect("core:onboarding-import")

        try:
            data = io_services.parse_import_file(content)
            conflicts = io_services.detect_workplace_conflicts(data)
        except IMPORT_ERRORS as e:
            del request.session["import_data"]
            messages.error(request, f"Import failed: {e}")
            return redirect("core:onboarding-import")

        mapping = io_services.build_workplace_mapping(request.POST, conflicts)
        overlapping_created = io_services.overlapping_created_workplaces(data, mapping)
        skip_workplaces = set()
        if overlapping_created:
            if request.POST.get("overlap_action") == "discard_all":
                del request.session["import_data"]
                messages.error(request, io_services.OVERLAP_DISCARD_MESSAGE)
                return redirect("core:onboarding-import")
            skip_workplaces = overlapping_created

        try:
            counts = io_services.perform_import(
                data, mapping, skip_workplaces=skip_workplaces
            )
        except (ValidationError, *IMPORT_ERRORS) as e:
            # perform_import is atomic — nothing was written.
            del request.session["import_data"]
            messages.error(request, f"Import failed, nothing was imported: {e}")
            return redirect("core:onboarding-import")

        del request.session["import_data"]
        messages.success(request, io_services.describe_import(counts))
        if skip_workplaces:
            messages.warning(
                request,
                "Skipped {} workplace(s) with overlapping contracts: {}.".format(
                    len(skip_workplaces), ", ".join(sorted(skip_workplaces))
                ),
            )

        return redirect(ob.URLS["review"])
