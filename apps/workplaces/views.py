from datetime import date
from decimal import Decimal
import json
import os

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.views import View
from django.utils import timezone

from .models import Workplace, WorkplaceContract, ContractTermSet
from .forms import WorkplaceForm, WorkplaceContractForm, ContractTermSetForm
from .services import (
    ALLOWED_ICON_CONTENT_TYPES, ALLOWED_ICON_EXTS, MAX_ICON_SIZE,
    valid_hex_color, valid_icon_class,
)
from core.utils import (
    avatar_for_name, month_bounds, parse_int_param, prev_next_month,
    WEEKS_PER_MONTH, sanitize_svg,
)
from core.views import _safe_next

# Curated icon choices for the workplace icon picker
ICON_CHOICES = [
    "bi-briefcase", "bi-building", "bi-shop", "bi-laptop", "bi-pc-display",
    "bi-code-slash", "bi-tools", "bi-truck", "bi-cup-hot", "bi-basket",
    "bi-camera", "bi-music-note", "bi-mortarboard", "bi-heart-pulse",
    "bi-scissors", "bi-palette", "bi-wrench", "bi-gear", "bi-headset",
    "bi-house", "bi-graph-up", "bi-people", "bi-book", "bi-star",
]

from core.constants import BG_COLOR_CHOICES, ACCENT_COLOR_CHOICES

import calendar as _cal_mod
MONTH_CHOICES = [(str(i), _cal_mod.month_abbr[i]) for i in range(1, 13)]


def _tax_profile_json():
    from tax.services import TaxCalculationService
    profile = TaxCalculationService.get_active_profile()
    if profile:
        return json.dumps({
            "deduction": str(profile.monthly_deduction),
            "percent": str(profile.tax_percent + profile.church_tax_percent),
        })
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Workplace CRUD
# ─────────────────────────────────────────────────────────────────────────────

class WorkplaceListView(View):
    def get(self, request):
        today = timezone.localdate()
        # active_termset_on walks contracts/term sets in Python — prefetch both
        # so the list issues 3 queries total instead of 2 per workplace.
        workplaces = Workplace.objects.prefetch_related("contracts__term_sets")
        wp_data = [
            {"workplace": wp, "termset": wp.active_termset_on(today)}
            for wp in workplaces
        ]
        return render(
            request, "workplaces/workplace_list.html", {"wp_data": wp_data}
        )


class WorkplaceDetailView(View):
    """Workplace detail with payroll-period calendar and session panel."""

    def get(self, request, slug):
        from calendar_view.services import CalendarService
        from payroll.services import PayrollPeriodService, SalaryEstimateService
        from tax.services import TaxCalculationService
        from shifts.models import Shift, PlannedShift

        workplace = get_object_or_404(Workplace, slug=slug)
        today = timezone.localdate()

        # Resolve active termset for today (may be None if no contract active)
        active_termset = workplace.active_termset_on(today)

        # Payroll month depends on payroll_period_start_day from active termset
        if active_termset:
            today_payroll_year, today_payroll_month = PayrollPeriodService.get_payroll_month(
                active_termset, today
            )
        else:
            today_payroll_year, today_payroll_month = today.year, today.month

        year = parse_int_param(request.GET.get("year"), today_payroll_year)
        month = parse_int_param(request.GET.get("month"), today_payroll_month)

        # Resolve the representative termset for the viewed month (may differ from today)
        viewed_termset = workplace.active_termset_in_month(year, month) or active_termset

        avatar_initials, avatar_color = avatar_for_name(workplace.name)

        grid = CalendarService.payroll_period_calendar(workplace.pk, year, month)
        grid.annotate_overlaps()

        # Period dates and earnings
        if viewed_termset:
            period_start, period_end = PayrollPeriodService.get_period_dates(
                viewed_termset, year, month
            )
            tax_pull_date = PayrollPeriodService.get_tax_pull_date(viewed_termset, year, month)
        else:
            period_start, period_end = month_bounds(year, month)
            tax_pull_date = date(year, month, 18)

        sessions_in_period = Shift.objects.filter(
            workplace=workplace,
            date__gte=period_start,
            date__lte=period_end,
        )
        actual_hours = sum((s.net_hours for s in sessions_in_period), Decimal("0"))
        avg_hours_per_week = (actual_hours / WEEKS_PER_MONTH).quantize(Decimal("0.01"))

        estimate = None
        feriepenge_gross = Decimal("0")
        feriepenge_am = Decimal("0")
        feriepenge_a_skat = Decimal("0")
        feriepenge_net = Decimal("0")
        feriepenge_rate = Decimal("0")
        pension_employee = Decimal("0")
        pension_employer = Decimal("0")
        fritvalgskonto = Decimal("0")

        if viewed_termset:
            # Month-aware estimate. Salaried: sum every term set active in the
            # month, each prorated to its active days (a mid-month start/end or
            # raise earns only part of each salary) — matches the dashboard and
            # analytics. Hourly: the month's actual hours.
            if viewed_termset.employment_type == ContractTermSet.EmploymentType.SALARIED:
                estimate = SalaryEstimateService.salaried_month_estimate(
                    viewed_termset.contract, year, month, as_of=tax_pull_date,
                )
            else:
                estimate = SalaryEstimateService.estimate_for_month(
                    viewed_termset, year, month, hours=actual_hours, as_of=tax_pull_date,
                )

            if viewed_termset.vacation_type == ContractTermSet.VacationType.FERIEKONTO:
                feriepenge_rate = Decimal("12.50")
                feriepenge_gross = (estimate.gross_pay * feriepenge_rate / Decimal("100")).quantize(Decimal("0.01"))
                feriepenge_tax = TaxCalculationService.calculate(
                    feriepenge_gross,
                    as_of=tax_pull_date,
                    tax_card_type="bikort",
                    employee_pension=Decimal("0"),
                    employee_atp=Decimal("0"),
                )
                feriepenge_am = feriepenge_tax.am_bidrag
                feriepenge_a_skat = feriepenge_tax.a_skat
                feriepenge_net = feriepenge_tax.net_pay

            pension_employee = estimate.employee_pension
            pension_employer = estimate.employer_pension
            fritvalgskonto = estimate.fritvalgskonto

        # Selected day sessions
        selected_date = request.GET.get("day")
        day_sessions = []
        if selected_date:
            try:
                sel_date = date.fromisoformat(selected_date)
                day_sessions = Shift.objects.filter(
                    workplace=workplace, date=sel_date
                ).order_by("start_time")
            except ValueError:
                selected_date = None

        prev_year, prev_month, next_year, next_month = prev_next_month(year, month)

        months_with_data = list(
            Shift.objects.filter(workplace=workplace)
            .values_list("date__year", "date__month")
            .distinct()
            .order_by("date__year", "date__month")
        )
        if (year, month) not in months_with_data:
            months_with_data.append((year, month))
            months_with_data.sort()
        if (today.year, today.month) not in months_with_data:
            months_with_data.append((today.year, today.month))
            months_with_data.sort()

        month_picker = []
        for y, m in months_with_data:
            month_picker.append({
                "year": y, "month": m,
                "label": _cal_mod.month_abbr[m],
                "is_current": y == today.year and m == today.month,
                "is_selected": y == year and m == month,
            })

        from collections import OrderedDict
        month_picker_by_year: dict[int, list] = OrderedDict()
        for mp in month_picker:
            month_picker_by_year.setdefault(mp["year"], []).append(mp)

        all_months = [(i, _cal_mod.month_name[i]) for i in range(1, 13)]

        pending_shifts = list(
            PlannedShift.objects.filter(
                workplace=workplace,
                status=PlannedShift.Status.PLANNED,
                date__lte=today,
            ).order_by("date", "start_time")
        )
        pending_shifts_count = len(pending_shifts)
        pending_shifts_json = [
            {
                "id": s.pk,
                "date": s.date.isoformat(),
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
                "break_minutes": s.break_minutes,
                "shift_type": s.shift_type,
                "shift_type_display": s.get_shift_type_display(),
                "net_hours": str(s.net_hours.quantize(Decimal("0.01"))),
            }
            for s in pending_shifts
        ]

        # All contracts for the timeline section, newest first by their earliest
        # term set (contracts have no date field of their own to order by).
        from django.db.models import Min
        contracts = (
            workplace.contracts.prefetch_related("term_sets")
            .annotate(_start=Min("term_sets__effective_from"))
            .order_by("-_start")
        )

        return render(
            request,
            "workplaces/workplace_detail.html",
            {
                "workplace": workplace,
                "active_termset": active_termset,
                "viewed_termset": viewed_termset,
                "contracts": contracts,
                "grid": grid,
                "year": year,
                "month": month,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
                "actual_hours": actual_hours,
                "avg_hours_per_week": avg_hours_per_week,
                "estimate": estimate,
                "feriepenge_rate": feriepenge_rate,
                "feriepenge_gross": feriepenge_gross,
                "feriepenge_am": feriepenge_am,
                "feriepenge_a_skat": feriepenge_a_skat,
                "feriepenge_net": feriepenge_net,
                "pension_employee": pension_employee,
                "pension_employer": pension_employer,
                "pension_total": pension_employee + pension_employer,
                "fritvalgskonto": fritvalgskonto,
                "selected_date": selected_date,
                "day_sessions": day_sessions,
                "avatar_initials": avatar_initials,
                "avatar_color": avatar_color,
                "month_picker_by_year": month_picker_by_year,
                "all_months": all_months,
                "today": today,
                "today_payroll_year": today_payroll_year,
                "today_payroll_month": today_payroll_month,
                "icon_choices": ICON_CHOICES,
                "bg_color_choices": BG_COLOR_CHOICES,
                "accent_color_choices": ACCENT_COLOR_CHOICES,
                "pending_shifts_count": pending_shifts_count,
                "pending_shifts_json": pending_shifts_json,
            },
        )


class WorkplaceCreateView(View):
    def get(self, request):
        form = WorkplaceForm()
        return render(request, "workplaces/workplace_form.html", {"form": form})

    def post(self, request):
        form = WorkplaceForm(request.POST)
        if form.is_valid():
            workplace = form.save()
            return redirect(f"/workplaces/{workplace.slug}/contracts/add/")
        return render(request, "workplaces/workplace_form.html", {"form": form})


class WorkplaceUpdateView(View):
    def get(self, request, slug):
        workplace = get_object_or_404(Workplace, slug=slug)
        form = WorkplaceForm(instance=workplace)
        return render(
            request, "workplaces/workplace_form.html",
            {"form": form, "workplace": workplace},
        )

    def post(self, request, slug):
        workplace = get_object_or_404(Workplace, slug=slug)
        form = WorkplaceForm(request.POST, instance=workplace)
        if form.is_valid():
            form.save()
            return redirect("workplaces:workplace-detail", slug=workplace.slug)
        return render(
            request, "workplaces/workplace_form.html",
            {"form": form, "workplace": workplace},
        )


class WorkplaceDeleteView(View):
    def post(self, request, slug):
        workplace = get_object_or_404(Workplace, slug=slug)
        workplace.delete()
        return redirect("workplaces:workplace-list")


# ─────────────────────────────────────────────────────────────────────────────
# Appearance customisation (icon / colour — AJAX)
# ─────────────────────────────────────────────────────────────────────────────

class WorkplaceCustomizeView(View):
    def post(self, request, slug):
        workplace = get_object_or_404(Workplace, slug=slug)

        icon = request.POST.get("icon", "")
        color = request.POST.get("color", "")
        accent_color = request.POST.get("accent_color", "")
        remove_custom_icon = request.POST.get("remove_custom_icon") == "1"

        if not valid_hex_color(color):
            return JsonResponse({"ok": False, "error": "Invalid background hex colour."}, status=400)
        if not valid_hex_color(accent_color):
            return JsonResponse({"ok": False, "error": "Invalid accent hex colour."}, status=400)
        if not valid_icon_class(icon):
            return JsonResponse({"ok": False, "error": "Invalid icon."}, status=400)

        workplace.icon = icon
        workplace.color = color
        workplace.accent_color = accent_color

        custom_icon_file = request.FILES.get("custom_icon")
        if custom_icon_file:
            ext = os.path.splitext(custom_icon_file.name or "")[1].lower()
            if custom_icon_file.content_type not in ALLOWED_ICON_CONTENT_TYPES or ext not in ALLOWED_ICON_EXTS:
                return JsonResponse(
                    {"ok": False, "error": "Only PNG and SVG files are allowed."}, status=400
                )
            if custom_icon_file.size > MAX_ICON_SIZE:
                return JsonResponse(
                    {"ok": False, "error": "Icon must be under 512 KB."}, status=400
                )
            if workplace.custom_icon:
                workplace.custom_icon.delete(save=False)
            is_svg = custom_icon_file.content_type == "image/svg+xml" or ext == ".svg"
            if is_svg:
                cleaned = sanitize_svg(custom_icon_file.read())
                if cleaned is None:
                    return JsonResponse(
                        {"ok": False, "error": "The SVG file could not be parsed."}, status=400
                    )
                workplace.custom_icon.save(
                    custom_icon_file.name, ContentFile(cleaned), save=False
                )
            else:
                workplace.custom_icon = custom_icon_file
            workplace.icon = ""
        elif (remove_custom_icon or icon) and workplace.custom_icon:
            # A named Bootstrap icon and a stored logo are mutually exclusive —
            # every template prefers the logo, so keeping both would silently
            # ignore the icon. The upload branch above already enforces the same
            # rule in reverse (it clears `icon`).
            workplace.custom_icon.delete(save=False)
            workplace.custom_icon = ""

        workplace.save()

        avatar_initials, avatar_color = avatar_for_name(workplace.name)
        return JsonResponse({
            "ok": True,
            "icon": workplace.icon,
            "color": workplace.color,
            "accent_color": workplace.accent_color,
            "custom_icon_url": workplace.custom_icon.url if workplace.custom_icon else "",
            "avatar_initials": avatar_initials,
            "avatar_color": avatar_color,
        })


# ─────────────────────────────────────────────────────────────────────────────
# WorkplaceContract CRUD
# ─────────────────────────────────────────────────────────────────────────────

def _contract_calendar_form(contract, data=None):
    """The per-contract invite config form, bound to the contract's config row
    (an unsaved one when none exists yet, so viewing doesn't create rows)."""
    from calendar_sync.forms import ContractCalendarConfigForm
    from calendar_sync.models import ContractCalendarConfig

    config = getattr(contract, "calendar_config", None) if contract.pk else None
    if config is None:
        config = ContractCalendarConfig(contract=contract if contract.pk else None)
    return ContractCalendarConfigForm(data, instance=config)


def _calendar_readiness():
    """Flags the contract form uses to warn that invites won't actually send yet:
    a working SMTP server and the global master arm are both required (see
    ``calendar_sync.invites.eligible``)."""
    from core.models import EmailSettings
    from calendar_sync.models import CalendarInviteSettings
    invite_settings = CalendarInviteSettings.load()
    return {
        "email_configured": EmailSettings.load().is_configured_for(
            EmailSettings.ROLE_CALENDAR
        ),
        "invites_master_on": invite_settings.enabled,
        # With both this and the contract's work address off, an invite has
        # nowhere to go — the partial warns rather than blocks.
        "personal_invites_on": invite_settings.send_to_personal,
    }


def _save_contract_calendar(contract, cal_form, request=None):
    """Persist the invite config for *contract* from a validated config form.

    When *request* is given, nudge if the change left active invites addressed to
    an old mailbox — they don't move on their own (explicit sync on Settings →
    Calendar). A brand-new contract has no prior invites, so this is a no-op there.
    """
    config = cal_form.save(commit=False)
    config.contract = contract
    config.save()
    if request is not None:
        from django.contrib import messages
        from calendar_sync import reconcile

        n = reconcile.contract_drift_count(contract)
        if n:
            messages.info(
                request,
                f"{n} calendar invite{'' if n == 1 else 's'} for this contract "
                f"still point{'s' if n == 1 else ''} at the previous address — "
                "sync them on Settings → Calendar.",
            )


class ContractCreateView(View):
    """Create a new contract for a workplace, then redirect to add the first termset."""

    def get(self, request, slug):
        workplace = get_object_or_404(Workplace, slug=slug)
        form = WorkplaceContractForm(workplace=workplace)
        return render(request, "workplaces/contract_form.html", {
            "form": form, "cal_form": _contract_calendar_form(WorkplaceContract()),
            "workplace": workplace,
            "is_first": not workplace.contracts.exists(),
            **_calendar_readiness(),
        })

    def post(self, request, slug):
        workplace = get_object_or_404(Workplace, slug=slug)
        form = WorkplaceContractForm(request.POST, workplace=workplace)
        cal_form = _contract_calendar_form(WorkplaceContract(), request.POST)
        if form.is_valid() and cal_form.is_valid():
            contract = form.save(commit=False)
            contract.workplace = workplace
            contract.save()
            _save_contract_calendar(contract, cal_form, request)
            return redirect(f"/workplaces/{slug}/contracts/{contract.pk}/terms/add/")
        return render(request, "workplaces/contract_form.html", {
            "form": form, "cal_form": cal_form, "workplace": workplace,
            "is_first": not workplace.contracts.exists(),
            **_calendar_readiness(),
        })


class ContractUpdateView(View):
    """Edit a contract's label and its calendar-invite config. Its active dates
    come from its term sets.

    Honours a same-origin ``next``: Settings → Calendar links here to fix a
    contract's invites, and landing on the workplace page afterwards left the
    owner to find their way back to the tab they came from."""

    def get(self, request, slug, cpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        form = WorkplaceContractForm(instance=contract, workplace=workplace)
        return render(request, "workplaces/contract_form.html", {
            "form": form, "cal_form": _contract_calendar_form(contract),
            "workplace": workplace, "contract": contract,
            "next_url": _safe_next(request, request.GET.get("next")),
            **_calendar_readiness(),
        })

    def post(self, request, slug, cpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        form = WorkplaceContractForm(request.POST, instance=contract, workplace=workplace)
        cal_form = _contract_calendar_form(contract, request.POST)
        next_url = _safe_next(request, request.POST.get("next"))
        ctx = {"form": form, "cal_form": cal_form, "workplace": workplace,
               "contract": contract, "next_url": next_url,
               **_calendar_readiness()}
        if form.is_valid() and cal_form.is_valid():
            updated = form.save(commit=False)
            try:
                updated.full_clean()
            except ValidationError as e:
                for msg in e.messages:
                    form.add_error(None, msg)
                return render(request, "workplaces/contract_form.html", ctx)
            updated.save()
            _save_contract_calendar(updated, cal_form, request)
            if next_url:
                return redirect(next_url)
            return redirect("workplaces:workplace-detail", slug=slug)
        return render(request, "workplaces/contract_form.html", ctx)


class ContractDeleteView(View):
    """Delete a contract (blocked if any shifts reference its termsets)."""

    def get(self, request, slug, cpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        from shifts.models import Shift
        shift_count = Shift.objects.filter(terms__contract=contract).count()
        return render(request, "workplaces/contract_confirm_delete.html", {
            "workplace": workplace, "contract": contract, "shift_count": shift_count,
        })

    def post(self, request, slug, cpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        from shifts.models import Shift
        if Shift.objects.filter(terms__contract=contract).exists():
            return redirect("workplaces:workplace-detail", slug=slug)
        contract.delete()
        return redirect("workplaces:workplace-detail", slug=slug)


# ─────────────────────────────────────────────────────────────────────────────
# ContractTermSet CRUD
# ─────────────────────────────────────────────────────────────────────────────

def _existing_terms_json(contract, exclude_pk=None):
    """Compact JSON of a contract's term-set date spans for the add-terms form's
    carry-over prompt: [{"from": iso, "until": iso|null}, ...]."""
    qs = contract.term_sets.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return json.dumps([
        {
            "from": ts.effective_from.isoformat(),
            "until": ts.effective_until.isoformat() if ts.effective_until else None,
        }
        for ts in qs
    ])


def _supersede_previous_expiry(new_ts):
    """A new term set that starts on or before a prior term set's end date
    supersedes it — the prior term set now only runs until the day before
    *new_ts*, so its own (later) end date is stale. Clear it. The "contract ends
    here" date, if any, lives on *new_ts* (chosen on the form)."""
    prev = (
        new_ts.contract.term_sets
        .filter(effective_from__lt=new_ts.effective_from)
        .exclude(pk=new_ts.pk)
        .order_by("-effective_from")
        .first()
    )
    if prev and prev.effective_until and prev.effective_until >= new_ts.effective_from:
        prev.effective_until = None
        prev.save(update_fields=["effective_until"])


class ContractTermSetCreateView(View):
    """Create a new termset (new effective date + settings) under a contract."""

    def get(self, request, slug, cpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        latest = contract.term_sets.first()
        initial = {}
        if latest:
            # Carry the pay/employment settings forward, but not the dates —
            # effective_from is today and effective_until is decided by the
            # carry-over prompt (see termset_form.js).
            for f in ContractTermSetForm.Meta.fields:
                if f not in ("effective_from", "effective_until"):
                    initial[f] = getattr(latest, f)
        initial["effective_from"] = timezone.localdate()
        form = ContractTermSetForm(initial=initial, contract=contract)
        return render(request, "workplaces/termset_form.html", {
            "form": form, "workplace": workplace, "contract": contract,
            "tax_profile_json": _tax_profile_json(), "month_choices": MONTH_CHOICES,
            "existing_terms_json": _existing_terms_json(contract),
        })

    def post(self, request, slug, cpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        form = ContractTermSetForm(request.POST, contract=contract)
        if form.is_valid():
            termset = form.save(commit=False)
            termset.contract = contract
            termset.save()
            _supersede_previous_expiry(termset)
            return redirect("workplaces:workplace-detail", slug=slug)
        return render(request, "workplaces/termset_form.html", {
            "form": form, "workplace": workplace, "contract": contract,
            "tax_profile_json": _tax_profile_json(), "month_choices": MONTH_CHOICES,
            "existing_terms_json": _existing_terms_json(contract),
        })


class ContractTermSetUpdateView(View):
    """Edit a termset — user can overwrite in-place or fork as new terms-from-date."""

    def _shift_count(self, termset):
        from shifts.models import Shift
        return Shift.objects.filter(terms=termset).count()

    def get(self, request, slug, cpk, tpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        termset = get_object_or_404(ContractTermSet, pk=tpk, contract=contract)
        form = ContractTermSetForm(instance=termset, contract=contract)
        return render(request, "workplaces/termset_form.html", {
            "form": form, "workplace": workplace, "contract": contract,
            "termset": termset, "shift_count": self._shift_count(termset),
            "tax_profile_json": _tax_profile_json(), "month_choices": MONTH_CHOICES,
            "existing_terms_json": _existing_terms_json(contract, exclude_pk=termset.pk),
        })

    def post(self, request, slug, cpk, tpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        termset = get_object_or_404(ContractTermSet, pk=tpk, contract=contract)

        action = request.POST.get("action", "overwrite")  # "overwrite" or "fork"

        if action == "fork":
            # Create a brand-new termset with the submitted data
            form = ContractTermSetForm(request.POST, contract=contract)
            if form.is_valid():
                new_ts = form.save(commit=False)
                new_ts.contract = contract
                new_ts.save()
                _supersede_previous_expiry(new_ts)
                return redirect("workplaces:workplace-detail", slug=slug)
        else:
            # Overwrite in place
            form = ContractTermSetForm(request.POST, instance=termset, contract=contract)
            if form.is_valid():
                form.save()
                return redirect("workplaces:workplace-detail", slug=slug)

        return render(request, "workplaces/termset_form.html", {
            "form": form, "workplace": workplace, "contract": contract,
            "termset": termset, "shift_count": self._shift_count(termset),
            "tax_profile_json": _tax_profile_json(), "month_choices": MONTH_CHOICES,
            "existing_terms_json": _existing_terms_json(contract, exclude_pk=termset.pk),
        })


class ContractTermSetDeleteView(View):
    def get(self, request, slug, cpk, tpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        termset = get_object_or_404(ContractTermSet, pk=tpk, contract=contract)
        from shifts.models import Shift
        shift_count = Shift.objects.filter(terms=termset).count()
        return render(request, "workplaces/termset_confirm_delete.html", {
            "workplace": workplace, "contract": contract, "termset": termset,
            "shift_count": shift_count,
        })

    def post(self, request, slug, cpk, tpk):
        workplace = get_object_or_404(Workplace, slug=slug)
        contract = get_object_or_404(WorkplaceContract, pk=cpk, workplace=workplace)
        termset = get_object_or_404(ContractTermSet, pk=tpk, contract=contract)
        from shifts.models import Shift
        if not Shift.objects.filter(terms=termset).exists():
            termset.delete()
        return redirect("workplaces:workplace-detail", slug=slug)
