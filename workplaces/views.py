from datetime import date
from decimal import Decimal
import json
import os

from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.views import View

from .models import Workplace
from .forms import WorkplaceForm

# Curated icon choices for the workplace icon picker
ICON_CHOICES = [
    "bi-briefcase", "bi-building", "bi-shop", "bi-laptop", "bi-pc-display",
    "bi-code-slash", "bi-tools", "bi-truck", "bi-cup-hot", "bi-basket",
    "bi-camera", "bi-music-note", "bi-mortarboard", "bi-heart-pulse",
    "bi-scissors", "bi-palette", "bi-wrench", "bi-gear", "bi-headset",
    "bi-house", "bi-graph-up", "bi-people", "bi-book", "bi-star",
]

# Muted / pastel palette for avatar background (Tailwind 200-level)
BG_COLOR_CHOICES = [
    "#c7d2fe", "#ddd6fe", "#fbcfe8", "#fecaca", "#fed7aa",
    "#fef08a", "#bbf7d0", "#99f6e4", "#bfdbfe", "#ffffff",
]

# Saturated palette for accent / theming (Tailwind 500-level)
ACCENT_COLOR_CHOICES = [
    "#6366f1", "#8b5cf6", "#ec4899", "#ef4444", "#f97316",
    "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#1e293b",
]

def _customize_ctx():
    """Return icon_choices and color_choices for the workplace form."""
    return {
        "icon_choices": ICON_CHOICES,
        "bg_color_choices": BG_COLOR_CHOICES,
        "accent_color_choices": ACCENT_COLOR_CHOICES,
    }


def _tax_profile_json():
    """Return a JSON string with the active tax profile data for form JS."""
    import json
    from core.services import TaxCalculationService
    profile = TaxCalculationService.get_active_profile()
    if profile:
        return json.dumps({
            "deduction": str(profile.monthly_deduction),
            "percent": str(profile.tax_percent + profile.church_tax_percent),
        })
    return ""


# Month choices for ferietillæg payout picker (value matches what the
# comma-separated CharField stores, label is the abbreviation).
import calendar as _cal_mod
MONTH_CHOICES = [(str(i), _cal_mod.month_abbr[i]) for i in range(1, 13)]


def _avatar_for_name(name: str) -> tuple[str, str]:
    """Return (initials, hex_color) for a workplace name."""
    AVATAR_COLORS = [
        "#6366f1", "#8b5cf6", "#ec4899", "#ef4444", "#f97316",
        "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6",
    ]
    parts = name.strip().split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[1][0]).upper()
    elif parts:
        initials = parts[0][:2].upper()
    else:
        initials = "?"
    color = AVATAR_COLORS[sum(ord(c) for c in name) % len(AVATAR_COLORS)]
    return initials, color


class WorkplaceListView(View):
    def get(self, request):
        workplaces = Workplace.objects.all()
        return render(
            request, "workplaces/workplace_list.html", {"workplaces": workplaces}
        )


class WorkplaceDetailView(View):
    """Workplace detail with payroll-period calendar and session panel."""

    def get(self, request, pk):
        from calendar_view.services import CalendarService
        from payroll.services import PayrollPeriodService, SalaryEstimateService
        from core.services import TaxCalculationService
        from worksessions.models import WorkSession, PlannedShift

        workplace = get_object_or_404(Workplace, pk=pk)
        today = date.today()

        # Determine which payroll month "today" belongs to for this workplace
        today_payroll_year, today_payroll_month = PayrollPeriodService.get_payroll_month(workplace, today)

        year = int(request.GET.get("year", today_payroll_year))
        month = int(request.GET.get("month", today_payroll_month))

        # Avatar
        avatar_initials, avatar_color = _avatar_for_name(workplace.name)

        # Payroll-period calendar for this workplace
        grid = CalendarService.payroll_period_calendar(pk, year, month)

        # Calculate earned so far
        period_start, period_end = PayrollPeriodService.get_period_dates(workplace, year, month)
        sessions_in_period = WorkSession.objects.filter(
            workplace=workplace,
            date__gte=period_start,
            date__lte=period_end,
        )
        actual_hours = sum((s.net_hours for s in sessions_in_period), Decimal("0"))
        avg_hours_per_week = (actual_hours / Decimal("4.33")).quantize(Decimal("0.01"))
        tax_pull_date = PayrollPeriodService.get_tax_pull_date(workplace, year, month)
        estimate = SalaryEstimateService.estimate(workplace, actual_hours, as_of=tax_pull_date)

        # Feriepenge calculation (only for feriekonto workplaces)
        feriepenge_gross = Decimal("0")
        feriepenge_am = Decimal("0")
        feriepenge_a_skat = Decimal("0")
        feriepenge_net = Decimal("0")
        feriepenge_rate = Decimal("0")
        if workplace.vacation_type == Workplace.VacationType.FERIEKONTO:
            feriepenge_rate = Decimal("12.50")
            feriepenge_gross = (estimate.gross_pay * feriepenge_rate / Decimal("100")).quantize(Decimal("0.01"))
            # Taxed with AM-bidrag and A-skat, no fradrag (like bikort)
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

        # Pension & fritvalgskonto from estimate
        pension_employee = estimate.employee_pension
        pension_employer = estimate.employer_pension
        fritvalgskonto = estimate.fritvalgskonto

        # Selected day sessions (if a day is clicked)
        selected_date = request.GET.get("day")
        day_sessions = []
        if selected_date:
            try:
                sel_date = date.fromisoformat(selected_date)
                day_sessions = WorkSession.objects.filter(
                    workplace=workplace, date=sel_date
                ).order_by("start_time")
            except ValueError:
                selected_date = None

        # Navigation
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        # Months that have session data (for the month picker)
        months_with_data = list(
            WorkSession.objects.filter(workplace=workplace)
            .values_list("date__year", "date__month")
            .distinct()
            .order_by("date__year", "date__month")
        )
        # Always include the currently selected month in the list
        if (year, month) not in months_with_data:
            months_with_data.append((year, month))
            months_with_data.sort()
        # Always include the current month
        if (today.year, today.month) not in months_with_data:
            months_with_data.append((today.year, today.month))
            months_with_data.sort()

        import calendar as cal_mod
        month_picker = []
        for y, m in months_with_data:
            month_picker.append({
                "year": y,
                "month": m,
                "label": cal_mod.month_abbr[m],
                "is_current": y == today.year and m == today.month,
                "is_selected": y == year and m == month,
            })

        # Group months by year for the picker UI
        from collections import OrderedDict
        month_picker_by_year: dict[int, list] = OrderedDict()
        for mp in month_picker:
            month_picker_by_year.setdefault(mp["year"], []).append(mp)

        # All month names for the "go to month" dropdown
        all_months = [(i, cal_mod.month_name[i]) for i in range(1, 13)]

        # Pending planned shifts (for approval banner + modal)
        pending_shifts = list(
            PlannedShift.objects.filter(
                workplace=workplace,
                status=PlannedShift.Status.PLANNED,
                date__lte=today,
            ).order_by("date", "start_time")
        )
        pending_shifts_count = len(pending_shifts)
        pending_shifts_json = json.dumps([
            {
                "id": s.pk,
                "date": s.date.isoformat(),
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
                "break_minutes": s.break_minutes,
                "session_type": s.session_type,
                "session_type_display": s.get_session_type_display(),
                "net_hours": str(s.net_hours.quantize(Decimal("0.01"))),
            }
            for s in pending_shifts
        ])

        return render(
            request,
            "workplaces/workplace_detail.html",
            {
                "workplace": workplace,
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
        return render(request, "workplaces/workplace_form.html", {
            "form": form, "tax_profile_json": _tax_profile_json(),
            "month_choices": MONTH_CHOICES,
        })

    def post(self, request):
        form = WorkplaceForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("workplaces:workplace-list")
        return render(request, "workplaces/workplace_form.html", {
            "form": form, "tax_profile_json": _tax_profile_json(),
            "month_choices": MONTH_CHOICES,
        })


class WorkplaceUpdateView(View):
    def get(self, request, pk):
        workplace = get_object_or_404(Workplace, pk=pk)
        form = WorkplaceForm(instance=workplace)
        return render(
            request,
            "workplaces/workplace_form.html",
            {"form": form, "workplace": workplace, "tax_profile_json": _tax_profile_json(),
             "month_choices": MONTH_CHOICES},
        )

    def post(self, request, pk):
        workplace = get_object_or_404(Workplace, pk=pk)
        form = WorkplaceForm(request.POST, instance=workplace)
        if form.is_valid():
            form.save()
            return redirect("workplaces:workplace-detail", pk=pk)
        return render(
            request,
            "workplaces/workplace_form.html",
            {"form": form, "workplace": workplace, "tax_profile_json": _tax_profile_json(),
             "month_choices": MONTH_CHOICES},
        )


class WorkplaceDeleteView(View):
    def post(self, request, pk):
        workplace = get_object_or_404(Workplace, pk=pk)
        workplace.delete()
        return redirect("workplaces:workplace-list")


# Allowed MIME types for custom icon uploads
_ALLOWED_ICON_TYPES = {"image/png", "image/svg+xml"}
_MAX_ICON_SIZE = 512 * 1024  # 512 KB


class WorkplaceCustomizeView(View):
    """AJAX endpoint for updating workplace icon, colour, and custom icon."""

    def post(self, request, pk):
        workplace = get_object_or_404(Workplace, pk=pk)

        icon = request.POST.get("icon", "")
        color = request.POST.get("color", "")
        accent_color = request.POST.get("accent_color", "")
        remove_custom_icon = request.POST.get("remove_custom_icon") == "1"

        # Validate colours
        if color and (len(color) != 7 or not color.startswith("#")):
            return JsonResponse({"ok": False, "error": "Invalid background hex colour."}, status=400)
        if accent_color and (len(accent_color) != 7 or not accent_color.startswith("#")):
            return JsonResponse({"ok": False, "error": "Invalid accent hex colour."}, status=400)

        workplace.icon = icon
        workplace.color = color
        workplace.accent_color = accent_color

        # Handle custom icon upload
        custom_icon_file = request.FILES.get("custom_icon")
        if custom_icon_file:
            if custom_icon_file.content_type not in _ALLOWED_ICON_TYPES:
                return JsonResponse(
                    {"ok": False, "error": "Only PNG and SVG files are allowed."},
                    status=400,
                )
            if custom_icon_file.size > _MAX_ICON_SIZE:
                return JsonResponse(
                    {"ok": False, "error": "Icon must be under 512 KB."},
                    status=400,
                )
            # Delete old custom icon file if exists
            if workplace.custom_icon:
                workplace.custom_icon.delete(save=False)
            workplace.custom_icon = custom_icon_file
            # Clear the Bootstrap icon when a custom icon is uploaded
            workplace.icon = ""
        elif remove_custom_icon and workplace.custom_icon:
            workplace.custom_icon.delete(save=False)
            workplace.custom_icon = ""

        workplace.save()

        # Build response with updated avatar info
        avatar_initials, avatar_color = _avatar_for_name(workplace.name)
        return JsonResponse({
            "ok": True,
            "icon": workplace.icon,
            "color": workplace.color,
            "accent_color": workplace.accent_color,
            "custom_icon_url": workplace.custom_icon.url if workplace.custom_icon else "",
            "avatar_initials": avatar_initials,
            "avatar_color": avatar_color,
        })
