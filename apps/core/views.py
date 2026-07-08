import calendar as _calendar
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_not_required
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
            "form": form, "next_url": next_url,
        })

    def post(self, request):
        settings = UserSettings.load()
        form = UserSettingsForm(request.POST, instance=settings)
        next_url = self._safe_next(request, request.POST.get("next"))
        if form.is_valid():
            form.save()
            return redirect(next_url or "core:settings")
        return render(request, "core/settings.html", {
            "form": form, "next_url": next_url,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding wizard
#
# The account is created immediately (step 1) — the whole site is behind a login,
# so there must be a logged-in user for the remaining steps. Tax → Workplace →
# Contract → Terms are then held in a durable per-user OnboardingDraft (a DB row,
# not the session, so logging out mid-onboarding doesn't lose the data) and
# written to the real tables together, atomically, only on the final "Finish"
# (the Terms step's submit), after which the draft is deleted. Each step's stored
# payload is the raw POST of a form that already passed is_valid(), so re-binding
# it on a later visit re-shows the input with no validation errors — that's what
# makes back-navigation keep its place.
# ─────────────────────────────────────────────────────────────────────────────

_ONBOARDING_ORDER = ["tax", "workplace", "contract", "terms"]
_ONBOARDING_URLS = {
    "account": "core:onboarding-account",
    "tax": "core:onboarding-tax",
    "workplace": "core:onboarding-workplace",
    "contract": "core:onboarding-contract",
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
    "contract": "Contract",
    "terms": "Pay terms",
}


def _build_step_form(key, payload):
    """The bound form for a stored step payload — used to check completeness and
    to commit. Terms is built without a contract (guards no-op until Finish)."""
    from workplaces.forms import WorkplaceForm, WorkplaceContractForm, ContractTermSetForm
    if key == "tax":
        return TaxProfileForm(data=payload)
    if key == "workplace":
        return WorkplaceForm(data=payload)
    if key == "contract":
        return WorkplaceContractForm(data=payload)
    return ContractTermSetForm(data=payload, contract=None)


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
    yet valid), or 'empty'. Step 1 (Account) is always valid here. Step 4 folds
    the contract + terms sub-steps: valid only when the pay terms validate."""
    def status(key):
        if key not in data:
            return "empty"
        return "valid" if _build_step_form(key, data[key]).is_valid() else "started"

    terms = status("terms")
    if terms == "valid":
        contract_terms = "valid"
    elif terms != "empty" or "contract" in data:
        contract_terms = "started"
    else:
        contract_terms = "empty"
    return {1: "valid", 2: status("tax"), 3: status("workplace"), 4: contract_terms}


def _onboarding_steps(current, data):
    """Step-indicator model for the given wizard page. A step is 'active' (the
    current page), 'done' (green check — saved and complete/valid), 'started'
    (yellow number — saved but not yet complete, e.g. reached then left partly
    filled), or 'upcoming' (grey — not started). 'done' and 'started' are both
    clickable so the user can jump back and forth."""
    active_num = {"account": 1, "tax": 2, "workplace": 3, "contract": 4, "terms": 4}[current]
    progress = _onboarding_progress(data)
    definitions = [
        (1, "Account", None),
        (2, "Tax Profile", reverse("core:onboarding-tax")),
        (3, "Workplace", reverse("core:onboarding-workplace")),
        (4, "Contract & Terms", reverse("core:onboarding-contract")),
    ]
    steps = []
    for num, label, url in definitions:
        if num == active_num:
            state, step_url = "active", None
        elif progress[num] == "valid":
            state, step_url = "done", url
        elif progress[num] == "started":
            state, step_url = "started", url
        else:
            state, step_url = "upcoming", None
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
    data = _onboarding_data(request).get("contract", {})
    return WorkplaceContract(name=data.get("name", ""))


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

    try:
        with transaction.atomic():
            forms["tax"].save()
            workplace = forms["workplace"].save()
            contract = forms["contract"].save(commit=False)
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


@method_decorator(login_not_required, name="dispatch")
class OnboardingAccountView(View):
    """Onboarding step 1 — create the single admin account (immediately, so the
    remaining logged-in steps can run). Gone for good once an account exists."""

    def dispatch(self, request, *args, **kwargs):
        from django.contrib.auth.models import User
        if User.objects.exists():
            return redirect("core:onboarding" if request.user.is_authenticated else "/accounts/login/")
        return super().dispatch(request, *args, **kwargs)

    def _context(self, request, form):
        return {
            "form": form,
            "onboarding": True,
            "onboarding_first_step": True,
            "steps": _steps_for(request, "account"),
        }

    def get(self, request):
        from .forms import OnboardingUserCreationForm
        return render(request, "core/onboarding_account.html", self._context(request, OnboardingUserCreationForm()))

    def post(self, request):
        from django.contrib.auth import login
        from .forms import OnboardingUserCreationForm
        form = OnboardingUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # Single-user app: the first (only) account is the admin/owner.
            user.is_staff = True
            user.is_superuser = True
            user.save()
            login(request, user)
            return redirect("core:onboarding")
        return render(request, "core/onboarding_account.html", self._context(request, form))


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
    def _context(self, request, form):
        return {"form": form, "onboarding": True, "steps": _steps_for(request, "workplace")}

    def get(self, request):
        from workplaces.forms import WorkplaceForm
        stored = _onboarding_data(request).get("workplace")
        form = WorkplaceForm(data=stored) if stored else WorkplaceForm()
        return render(request, "workplaces/workplace_form.html", self._context(request, form))

    def post(self, request):
        _store_onboarding(request, "workplace", request.POST)
        return redirect(_resolve_goto(request, "workplace"))


class OnboardingContractView(View):
    def _context(self, request, form):
        return {
            "form": form,
            "workplace": _transient_workplace(request),
            "is_first": True,
            "onboarding": True,
            "steps": _steps_for(request, "contract"),
        }

    def get(self, request):
        from workplaces.forms import WorkplaceContractForm
        stored = _onboarding_data(request).get("contract")
        form = WorkplaceContractForm(data=stored) if stored else WorkplaceContractForm()
        return render(request, "workplaces/contract_form.html", self._context(request, form))

    def post(self, request):
        _store_onboarding(request, "contract", request.POST)
        return redirect(_resolve_goto(request, "contract"))


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
