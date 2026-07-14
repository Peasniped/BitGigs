import calendar as _calendar
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.utils import timezone

from .models import TaxProfile, UserSettings
from .forms import TaxProfileForm, UserSettingsForm
from .utils import avatar_for_name, parse_int_param, prev_next_month
from .dashboard_service import DashboardDataService, get_pending_shifts, get_todays_banner


class DashboardView(View):
    """Home page — calendar, pay counters, and workplace cards."""

    def get(self, request):
        from calendar_view.services import CalendarService

        today = timezone.localdate()
        year = parse_int_param(request.GET.get("year"), today.year)
        month = parse_int_param(request.GET.get("month"), today.month)

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
    def _safe_next(self, request, raw):
        # Only allow same-origin relative redirects.
        if raw and raw.startswith("/") and not raw.startswith("//"):
            return raw
        return None

    def get(self, request):
        settings = UserSettings.load()
        form = UserSettingsForm(instance=settings)
        next_url = self._safe_next(request, request.GET.get("next"))
        return render(request, "core/settings.html", {
            "form": form, "next_url": next_url, **sign_in_context(request.user),
        })

    def post(self, request):
        settings = UserSettings.load()
        form = UserSettingsForm(request.POST, instance=settings)
        next_url = self._safe_next(request, request.POST.get("next"))
        if form.is_valid():
            form.save()
            return redirect(next_url or "core:settings")
        return render(request, "core/settings.html", {
            "form": form, "next_url": next_url, **sign_in_context(request.user),
        })


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
        context["owner_username"] = owner.get_username() if owner else ""
        return context


def sign_in_context(user):
    """Sign-in card state for the settings page: is an IdP identity linked, and is
    password sign-in still available."""
    from allauth.socialaccount.models import SocialAccount
    from django.contrib.auth.forms import SetPasswordForm
    linked = SocialAccount.objects.filter(user=user).first()
    return {
        "sso_account": linked,
        "sso_linked": linked is not None,
        "has_usable_password": user.has_usable_password(),
        "set_password_form": SetPasswordForm(user),  # drives the set/change modal
    }


@method_decorator(login_not_required, name="dispatch")
class SSOLaunchView(View):
    """Landing spot for Authentik's application tile (set it as the provider's
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
    registering in Authentik. It lands on Authentik's own signed-out page, which
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
                end_session_url = ""

        if not end_session_url:
            messages.error(request, "Could not reach Authentik to sign you out. Sign out there "
                                    "directly, then try again.")
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

    Without this, an already-signed-in Authentik session makes the round-trip
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

        ctx = sign_in_context(request.user)
        action = request.POST.get("action")

        if action == "unlink_sso":
            if not ctx["sso_linked"]:
                return redirect("core:settings")
            if not ctx["has_usable_password"]:
                messages.error(request, "Set a password before unlinking Authentik — "
                                        "otherwise you would have no way back in.")
                return redirect("core:settings")
            ctx["sso_account"].delete()
            messages.success(request, "Authentik is no longer linked. Sign in with your password.")
            return redirect("core:settings")

        if action == "disable":
            if not ctx["sso_linked"]:
                messages.error(request, "Link your Authentik account before turning off password sign-in — "
                                        "otherwise you would have no way back in.")
                return redirect("core:settings")
            request.user.set_unusable_password()
            request.user.save(update_fields=["password"])
            # Any change to the password rotates the session hash, which would log
            # the owner straight out of the session they're doing this from.
            update_session_auth_hash(request, request.user)
            messages.success(request, "Password sign-in is off. Use Authentik from now on.")
            return redirect("core:settings")

        if action == "set_password":
            form = SetPasswordForm(request.user, request.POST)
            if form.is_valid():
                had_one = ctx["has_usable_password"]
                form.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password changed." if had_one
                                 else "Password sign-in is on.")
                return redirect("core:settings")
            # Re-render with the modal open, so the errors are where the user is.
            return render(request, "core/settings.html", {
                "form": UserSettingsForm(instance=UserSettings.load()),
                "next_url": None,
                **ctx,
                "set_password_form": form,
                "open_password_modal": True,
            })

        return redirect("core:settings")


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding wizard
#
# The account is created immediately (step 1) — the whole site is behind a login,
# so there must be a logged-in user for the remaining steps. Tax → Workplace →
# Terms are then held in a durable per-user OnboardingDraft (a DB row, not the
# session, so logging out mid-onboarding doesn't lose the data) and written to
# the real tables together, atomically, only on the final "Finish" (the Terms
# step's submit), after which the draft is deleted. Each step's stored payload is
# the raw POST of a form that already passed is_valid(), so re-binding it on a
# later visit re-shows the input with no validation errors — that's what makes
# back-navigation keep its place.
#
# The contract has no step of its own: its only editable field is an optional
# label, so the Workplace step carries it as a prefixed "contract-name" field and
# a single payload holds both forms.
# ─────────────────────────────────────────────────────────────────────────────

_ONBOARDING_ORDER = ["tax", "workplace", "terms"]
_ONBOARDING_URLS = {
    "account": "core:onboarding-account",
    "tax": "core:onboarding-tax",
    "workplace": "core:onboarding-workplace",
    "terms": "core:onboarding-terms",
}
_ONBOARDING_MONTH_CHOICES = [(str(i), _calendar.month_abbr[i]) for i in range(1, 13)]


def _onboarding_data(request):
    """The current user's saved onboarding step payloads (empty dict if none)."""
    from .models import OnboardingDraft
    draft = OnboardingDraft.objects.filter(user=request.user).first()
    return draft.data if draft else {}


def _store_onboarding(request, key, post):
    from .models import OnboardingDraft
    payload = {k: v for k, v in post.items() if k != "csrfmiddlewaretoken"}
    draft, _ = OnboardingDraft.objects.get_or_create(user=request.user)
    draft.data[key] = payload
    draft.save(update_fields=["data", "updated_at"])


def _clear_onboarding(request):
    from .models import OnboardingDraft
    OnboardingDraft.objects.filter(user=request.user).delete()
    request.session.pop("onboarding", None)  # clear any legacy session copy


_STEP_LABELS = {
    "tax": "Tax details",
    "workplace": "Workplace",
    "terms": "Pay terms",
}


def _build_step_form(key, payload):
    """The bound form for a stored step payload — used to check completeness and
    to commit. Terms is built without a contract (guards no-op until Finish)."""
    from workplaces.forms import WorkplaceForm, ContractTermSetForm
    if key == "tax":
        return TaxProfileForm(data=payload)
    if key == "workplace":
        return WorkplaceForm(data=payload)
    return ContractTermSetForm(data=payload, contract=None)


def _build_contract_form(payload=None):
    """The contract's optional label rides along on the Workplace step, prefixed
    so it can't collide with the workplace's own `name`."""
    from workplaces.forms import WorkplaceContractForm
    if payload is None:
        return WorkplaceContractForm(prefix="contract")
    return WorkplaceContractForm(data=payload, prefix="contract")


def _resolve_goto(request, current):
    """Destination after saving `current`: the ``onboarding_goto`` field is
    ``next`` (the following step) or a step key (jump there). Guards against
    arbitrary values."""
    goto = request.POST.get("onboarding_goto", "next")
    if goto in _ONBOARDING_ORDER:
        target = goto
    else:  # "next" (or anything unexpected)
        idx = _ONBOARDING_ORDER.index(current)
        target = _ONBOARDING_ORDER[min(idx + 1, len(_ONBOARDING_ORDER) - 1)]
    return reverse(_ONBOARDING_URLS[target])


def _onboarding_progress(data):
    """Per indicator-step status: 'valid' (complete), 'started' (has data but not
    yet valid), or 'empty'. Step 1 (Account) is always valid here."""
    def status(key):
        if key not in data:
            return "empty"
        return "valid" if _build_step_form(key, data[key]).is_valid() else "started"

    return {1: "valid", 2: status("tax"), 3: status("workplace"), 4: status("terms")}


def _onboarding_steps(current, data):
    """Step-indicator model for the given wizard page. A step is 'active' (the
    current page), 'done' (green check — an earlier step, filled and valid),
    'started' (yellow number — filled but ahead of the current page because the
    user navigated back, or filled yet incomplete), or 'upcoming' (grey — not
    started). 'done' and 'started' are both clickable so the user can jump back
    and forth."""
    active_num = {"account": 1, "tax": 2, "workplace": 3, "terms": 4}[current]
    progress = _onboarding_progress(data)
    definitions = [
        (1, "Account", None),
        (2, "Tax Profile", reverse("core:onboarding-tax")),
        (3, "Workplace", reverse("core:onboarding-workplace")),
        (4, "Pay Terms", reverse("core:onboarding-terms")),
    ]
    steps = []
    for num, label, url in definitions:
        if num == active_num:
            state, step_url = "active", None
        elif progress[num] == "empty":
            state, step_url = "upcoming", None
        elif progress[num] == "valid" and num < active_num:
            state, step_url = "done", url
        else:
            # Filled but ahead of the current page (the user navigated back), or
            # filled yet incomplete → yellow.
            state, step_url = "started", url
        steps.append({"num": num, "label": label, "state": state, "url": step_url})
    return steps


def _steps_for(request, current):
    """`_onboarding_steps` for a request — the account step runs before login, so
    it has no draft to read."""
    data = _onboarding_data(request) if request.user.is_authenticated else {}
    return _onboarding_steps(current, data)


def _transient_workplace(request):
    """Unsaved Workplace built from the stored workplace step — for display only
    (name) on the later onboarding pages, since nothing is saved yet."""
    from workplaces.models import Workplace
    data = _onboarding_data(request).get("workplace", {})
    return Workplace(name=data.get("name", ""), slug=data.get("slug", "") or "")


def _transient_contract(request):
    from workplaces.models import WorkplaceContract
    data = _onboarding_data(request).get("workplace", {})
    return WorkplaceContract(name=data.get("contract-name", ""))


def _onboarding_tax_profile_json(request):
    """Tax card JSON for the Terms page's live gross-pay estimate, built from the
    stored (not-yet-saved) tax step. Mirrors workplaces.views._tax_profile_json."""
    tax = _onboarding_data(request).get("tax")
    if not tax:
        return ""
    form = TaxProfileForm(data=tax)
    if not form.is_valid():
        return ""
    cd = form.cleaned_data
    percent = cd["tax_percent"] + (cd.get("church_tax_percent") or Decimal("0"))
    return json.dumps({"deduction": str(cd["monthly_deduction"]), "percent": str(percent)})


def _commit_onboarding(request):
    """Validate every saved step and, if all complete, write the wizard to the
    database atomically. Returns True on success, or (step_key, message) naming
    the first incomplete step to send the user back to (with its fields flagged)."""
    from django.core.exceptions import ValidationError
    from workplaces.forms import ContractTermSetForm

    ob = _onboarding_data(request)
    forms = {}
    for key in _ONBOARDING_ORDER:
        if key not in ob:
            return (key, f"Please fill in the {_STEP_LABELS[key]} step before you can submit.")
        form = _build_step_form(key, ob[key])
        if not form.is_valid():
            return (key, f"Please finish the {_STEP_LABELS[key]} step before you can submit.")
        forms[key] = form

    contract_form = _build_contract_form(ob["workplace"])
    contract_form.is_valid()  # only an optional label — never fails

    try:
        with transaction.atomic():
            forms["tax"].save()
            workplace = forms["workplace"].save()
            contract = contract_form.save(commit=False)
            contract.workplace = workplace
            contract.save()
            # Re-bind the terms to the real contract so it's linked + fully validated.
            terms_form = ContractTermSetForm(data=ob["terms"], contract=contract)
            if not terms_form.is_valid():
                raise ValidationError("terms")
            terms_form.save()
    except ValidationError:
        return ("terms", f"Please finish the {_STEP_LABELS['terms']} step before you can submit.")
    return True


# ── Onboarding step 1: claim the instance, then create the owner ─────────────
# Three pages, because the setup key gates everything that follows:
#   /onboarding/account/         the key, and nothing else
#   /onboarding/account/method/  Authentik or email+password (only when SSO is on)
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
            "steps": _steps_for(request, "account"),
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
    """Authentik, or a plain email + password account."""

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
    """Entry point — resume at the first step still lacking data, else the last."""

    def get(self, request):
        ob = _onboarding_data(request)
        for key in _ONBOARDING_ORDER:
            if key not in ob:
                return redirect(_ONBOARDING_URLS[key])
        return redirect(_ONBOARDING_URLS["terms"])


class OnboardingTaxView(View):
    def _context(self, request, form):
        return {"tax_form": form, "onboarding": True, "steps": _steps_for(request, "tax")}

    def get(self, request):
        stored = _onboarding_data(request).get("tax")
        form = TaxProfileForm(data=stored) if stored else TaxProfileForm()
        return render(request, "core/onboarding_tax.html", self._context(request, form))

    def post(self, request):
        # Save whatever's entered (even partial) and navigate — validation is
        # deferred to Finish, so the user can fill steps in any order.
        _store_onboarding(request, "tax", request.POST)
        return redirect(_resolve_goto(request, "tax"))


class OnboardingWorkplaceView(View):
    """Onboarding step 3 — the workplace, plus the contract's optional label as a
    field that the page reveals once the workplace is named."""

    def _context(self, request, form, contract_form):
        return {
            "form": form,
            "contract_form": contract_form,
            "onboarding": True,
            "steps": _steps_for(request, "workplace"),
        }

    def get(self, request):
        from workplaces.forms import WorkplaceForm
        stored = _onboarding_data(request).get("workplace")
        form = WorkplaceForm(data=stored) if stored else WorkplaceForm()
        contract_form = _build_contract_form(stored)
        return render(request, "workplaces/workplace_form.html", self._context(request, form, contract_form))

    def post(self, request):
        _store_onboarding(request, "workplace", request.POST)
        return redirect(_resolve_goto(request, "workplace"))


class OnboardingTermsView(View):
    def _context(self, request, form):
        return {
            "form": form,
            "workplace": _transient_workplace(request),
            "contract": _transient_contract(request),
            "onboarding": True,
            "steps": _steps_for(request, "terms"),
            "tax_profile_json": _onboarding_tax_profile_json(request),
            "month_choices": _ONBOARDING_MONTH_CHOICES,
            "existing_terms_json": "[]",
        }

    def get(self, request):
        from workplaces.forms import ContractTermSetForm
        stored = _onboarding_data(request).get("terms")
        form = ContractTermSetForm(data=stored, contract=None) if stored else ContractTermSetForm(contract=None)
        return render(request, "workplaces/termset_form.html", self._context(request, form))

    def post(self, request):
        from django.contrib import messages
        _store_onboarding(request, "terms", request.POST)

        goto = request.POST.get("onboarding_goto", "next")
        if goto not in ("next", "finish"):
            # Back / step-jump: just save and navigate, don't try to finish.
            return redirect(_resolve_goto(request, "terms"))

        result = _commit_onboarding(request)
        if result is True:
            request.session["onboarding_complete"] = True
            _clear_onboarding(request)
            messages.success(request, "You're all set up — welcome to BitGigs!")
            return redirect("core:dashboard")
        step_key, msg = result
        messages.error(request, msg)
        return redirect(_ONBOARDING_URLS[step_key])
