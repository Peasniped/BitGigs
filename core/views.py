from datetime import date
from decimal import Decimal

from django.shortcuts import redirect, render, get_object_or_404
from django.views import View

from .models import TaxProfile, UserSettings
from .forms import TaxProfileForm, UserSettingsForm


# Palette of pleasant colours for workplace avatars
_AVATAR_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#ef4444", "#f97316",
    "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6",
]


def _avatar_for_name(name: str) -> tuple[str, str]:
    """Return (initials, hex colour) for a workplace name."""
    parts = name.strip().split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[1][0]).upper()
    elif parts:
        initials = parts[0][:2].upper()
    else:
        initials = "?"
    color = _AVATAR_COLORS[sum(ord(c) for c in name) % len(_AVATAR_COLORS)]
    return initials, color


class DashboardView(View):
    """Home page — calendar, pay counters, and workplace cards."""

    def get(self, request):
        from workplaces.models import Workplace
        from calendar_view.services import CalendarService
        from payroll.services import SalaryEstimateService, PayrollPeriodService
        from worksessions.models import WorkSession

        # Setup redirect — if no tax profile or workplaces exist, go to setup wizard
        has_tax = TaxProfile.objects.exists()
        has_workplaces = Workplace.objects.exists()
        if not has_tax or not has_workplaces:
            return redirect("core:setup")

        today = date.today()
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))

        # Month calendar grid
        grid = CalendarService.month_calendar(year, month)

        # Prev/next nav
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        # Active workplaces + per-workplace salary estimates
        workplaces = Workplace.objects.filter(is_active=True)
        workplace_data = []
        total_earned_gross = Decimal("0")
        total_earned_net = Decimal("0")
        total_expected_gross = Decimal("0")
        total_expected_net = Decimal("0")

        for wp in workplaces:
            period_start, period_end = PayrollPeriodService.get_period_dates(wp, year, month)

            # Actual hours worked so far in this period
            sessions = WorkSession.objects.filter(
                workplace=wp,
                date__gte=period_start,
                date__lte=period_end,
            )
            actual_hours = sum(
                (s.net_hours for s in sessions), Decimal("0")
            )

            tax_pull_date = PayrollPeriodService.get_tax_pull_date(wp, year, month)
            earned_est = SalaryEstimateService.estimate(wp, actual_hours, as_of=tax_pull_date)
            total_earned_gross += earned_est.taxable_gross
            if earned_est.tax_breakdown:
                total_earned_net += earned_est.tax_breakdown.net_pay

            # Expected full-month estimate
            if wp.employment_type == Workplace.EmploymentType.SALARIED:
                expected_hours = wp.expected_weekly_hours * Decimal("4.33") if wp.expected_weekly_hours else Decimal("148")
            else:
                expected_hours = wp.expected_weekly_hours * Decimal("4.33") if wp.expected_weekly_hours else actual_hours

            expected_est = SalaryEstimateService.estimate(wp, expected_hours, as_of=tax_pull_date)
            total_expected_gross += expected_est.taxable_gross
            if expected_est.tax_breakdown:
                total_expected_net += expected_est.tax_breakdown.net_pay

            workplace_data.append({
                "workplace": wp,
                "actual_hours": actual_hours,
                "earned_gross": earned_est.taxable_gross,
                "earned_net": earned_est.tax_breakdown.net_pay if earned_est.tax_breakdown else earned_est.taxable_gross,
                "expected_gross": expected_est.taxable_gross,
                "avatar_initials": _avatar_for_name(wp.name)[0],
                "avatar_color": _avatar_for_name(wp.name)[1],
            })

        return render(
            request,
            "dashboard.html",
            {
                "grid": grid,
                "year": year,
                "month": month,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
                "workplace_data": workplace_data,
                "total_earned_gross": total_earned_gross,
                "total_earned_net": total_earned_net,
                "total_expected_gross": total_expected_gross,
                "total_expected_net": total_expected_net,
            },
        )


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
    def get(self, request):
        settings = UserSettings.load()
        form = UserSettingsForm(instance=settings)
        return render(request, "core/settings.html", {"form": form})

    def post(self, request):
        settings = UserSettings.load()
        form = UserSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            return redirect("core:settings")
        return render(request, "core/settings.html", {"form": form})


class SetupWizardView(View):
    """First-time setup: tax profile + first workplace."""

    def get(self, request):
        # If setup is already complete, redirect to dashboard
        if TaxProfile.objects.exists():
            from workplaces.models import Workplace
            if Workplace.objects.exists():
                return redirect("core:dashboard")

        tax_form = TaxProfileForm(prefix="tax")
        from workplaces.forms import WorkplaceForm
        from workplaces.views import MONTH_CHOICES
        workplace_form = WorkplaceForm(prefix="wp")
        return render(
            request,
            "core/setup.html",
            {"tax_form": tax_form, "workplace_form": workplace_form,
             "month_choices": MONTH_CHOICES},
        )

    def post(self, request):
        tax_form = TaxProfileForm(request.POST, prefix="tax")
        from workplaces.forms import WorkplaceForm
        from workplaces.views import MONTH_CHOICES
        workplace_form = WorkplaceForm(request.POST, prefix="wp")

        if tax_form.is_valid() and workplace_form.is_valid():
            tax_form.save()
            workplace_form.save()
            return redirect("core:dashboard")

        return render(
            request,
            "core/setup.html",
            {"tax_form": tax_form, "workplace_form": workplace_form,
             "month_choices": MONTH_CHOICES},
        )
