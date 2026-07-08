from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
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


@method_decorator(login_not_required, name="dispatch")
class FirstUserSetupView(View):
    """First-time setup — step 0: create the (single) user account.

    Only reachable while no account exists; once one does, the page is gone
    for good and everything runs through the normal login gate.
    """

    def dispatch(self, request, *args, **kwargs):
        from django.contrib.auth.models import User
        if User.objects.exists():
            return redirect("core:dashboard" if request.user.is_authenticated else "/accounts/login/")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        from django.contrib.auth.forms import UserCreationForm
        return render(request, "core/setup_user.html", {"form": UserCreationForm()})

    def post(self, request):
        from django.contrib.auth import login
        from django.contrib.auth.forms import UserCreationForm
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # Single-user app: the first (only) account is the admin.
            user.is_staff = True
            user.is_superuser = True
            user.save()
            login(request, user)
            return redirect("core:setup")
        return render(request, "core/setup_user.html", {"form": form})


class SetupWizardView(View):
    """First-time setup — step 1: tax profile only."""

    def get(self, request):
        from workplaces.models import Workplace
        # Setup fully complete → dashboard
        if TaxProfile.objects.exists() and Workplace.objects.exists():
            return redirect("core:dashboard")

        # Otherwise show step 1. If a profile already exists (e.g. the user
        # clicked the step-1 indicator to go back), edit it instead of starting
        # blank, so the back-navigation lands on the tax form rather than skipping.
        existing = TaxProfile.objects.order_by("-effective_from").first()
        tax_form = TaxProfileForm(prefix="tax", instance=existing)
        return render(request, "core/setup.html", {"tax_form": tax_form})

    def post(self, request):
        existing = TaxProfile.objects.order_by("-effective_from").first()
        tax_form = TaxProfileForm(request.POST, prefix="tax", instance=existing)
        if tax_form.is_valid():
            tax_form.save()
            return redirect("/workplaces/new/?setup=1")
        return render(request, "core/setup.html", {"tax_form": tax_form})
