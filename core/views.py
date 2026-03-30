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
        from worksessions.models import WorkSession, PlannedShift

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
        total_planned_gross = Decimal("0")
        total_planned_net = Decimal("0")

        # Hour goal aggregation
        total_goal_min = Decimal("0")
        total_goal_max = Decimal("0")
        total_planned_hours = Decimal("0")
        total_approved_hours = Decimal("0")
        has_any_goal = False

        # Collect payroll period boundaries for calendar indication
        period_boundaries = []
        # Cross-period shift info for banners
        cross_period_info = []

        for wp in workplaces:
            period_start, period_end = PayrollPeriodService.get_period_dates(wp, year, month)
            period_boundaries.append({
                "workplace_name": wp.name,
                "color": wp.accent_color or wp.color or "#6366f1",
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
            })

            # Check for sessions in previous month that belong to THIS payroll period
            import calendar as _cal_mod2
            first_of_month = date(year, month, 1)
            if period_start < first_of_month:
                prev_sessions = WorkSession.objects.filter(
                    workplace=wp,
                    date__gte=period_start,
                    date__lt=first_of_month,
                )
                prev_planned = PlannedShift.objects.filter(
                    workplace=wp,
                    date__gte=period_start,
                    date__lt=first_of_month,
                    status=PlannedShift.Status.PLANNED,
                )
                count = prev_sessions.count() + prev_planned.count()
                hours = sum((s.net_hours for s in prev_sessions), Decimal("0"))
                hours += sum((p.net_hours for p in prev_planned), Decimal("0"))
                if count > 0:
                    prev_month_name = _cal_mod2.month_name[period_start.month]
                    cross_period_info.append({
                        "workplace": wp.name,
                        "color": wp.accent_color or wp.color or "#6366f1",
                        "count": count,
                        "hours": hours,
                        "direction": "prev",
                        "other_month": prev_month_name,
                        "payroll_month": _cal_mod2.month_name[month],
                    })

            # Check for sessions in THIS month that belong to NEXT payroll period
            last_of_month = date(year, month, _cal_mod2.monthrange(year, month)[1])
            if period_end < last_of_month:
                next_sessions = WorkSession.objects.filter(
                    workplace=wp,
                    date__gt=period_end,
                    date__lte=last_of_month,
                )
                next_planned = PlannedShift.objects.filter(
                    workplace=wp,
                    date__gt=period_end,
                    date__lte=last_of_month,
                    status=PlannedShift.Status.PLANNED,
                )
                count = next_sessions.count() + next_planned.count()
                hours = sum((s.net_hours for s in next_sessions), Decimal("0"))
                hours += sum((p.net_hours for p in next_planned), Decimal("0"))
                if count > 0:
                    if month == 12:
                        nm = 1
                    else:
                        nm = month + 1
                    cross_period_info.append({
                        "workplace": wp.name,
                        "color": wp.accent_color or wp.color or "#6366f1",
                        "count": count,
                        "hours": hours,
                        "direction": "next",
                        "other_month": _cal_mod2.month_name[month],
                        "payroll_month": _cal_mod2.month_name[nm],
                    })

            # Actual hours worked so far in this period
            sessions = WorkSession.objects.filter(
                workplace=wp,
                date__gte=period_start,
                date__lte=period_end,
            )
            actual_hours = sum(
                (s.net_hours for s in sessions), Decimal("0")
            )
            avg_hours_per_week = (actual_hours / Decimal("4.33")).quantize(Decimal("0.01"))

            # Planned hours (not yet approved)
            planned_hours = sum(
                (p.net_hours for p in PlannedShift.objects.filter(
                    workplace=wp,
                    date__gte=period_start,
                    date__lte=period_end,
                    status=PlannedShift.Status.PLANNED,
                )),
                Decimal("0"),
            )

            tax_pull_date = PayrollPeriodService.get_tax_pull_date(wp, year, month)
            earned_est = SalaryEstimateService.estimate(wp, actual_hours, as_of=tax_pull_date)
            total_earned_gross += earned_est.taxable_gross
            if earned_est.tax_breakdown:
                total_earned_net += earned_est.tax_breakdown.net_pay

            # Planned estimate (planned shifts only)
            # Salaried workplaces already have their full salary in earned_est,
            # so only add planned earnings for hourly workplaces.
            if wp.employment_type == Workplace.EmploymentType.HOURLY and planned_hours:
                planned_est = SalaryEstimateService.estimate(wp, planned_hours, as_of=tax_pull_date)
                total_planned_gross += planned_est.taxable_gross
                if planned_est.tax_breakdown:
                    total_planned_net += planned_est.tax_breakdown.net_pay
            else:
                planned_est = None

            # Hour goal aggregation (convert weekly to monthly)
            if wp.hour_goal_type and wp.hour_goal_min:
                has_any_goal = True
                goal_min = wp.hour_goal_min
                goal_max = wp.hour_goal_max or Decimal("0")
                if wp.hour_goal_type == "weekly":
                    goal_min = goal_min * Decimal("4.33")
                    goal_max = goal_max * Decimal("4.33") if goal_max else Decimal("0")
                total_goal_min += goal_min
                total_goal_max += goal_max
            total_planned_hours += planned_hours
            total_approved_hours += actual_hours

            workplace_data.append({
                "workplace": wp,
                "actual_hours": actual_hours,
                "avg_hours_per_week": avg_hours_per_week,
                "earned_gross": earned_est.taxable_gross,
                "earned_net": earned_est.tax_breakdown.net_pay if earned_est.tax_breakdown else earned_est.taxable_gross,
                "planned_gross": planned_est.taxable_gross if planned_est else Decimal("0"),
                "avatar_initials": _avatar_for_name(wp.name)[0],
                "avatar_color": _avatar_for_name(wp.name)[1],
            })

        # ── Pending shifts for approval (across all workplaces) ──
        # Past shifts: always approvable. Today's shifts: only once near/past end time.
        import json as _json2
        from datetime import datetime as _dt, timedelta as _td
        now_time = _dt.now().time()
        all_pending = PlannedShift.objects.filter(
            workplace__is_active=True,
            status=PlannedShift.Status.PLANNED,
            date__lte=today,
        ).select_related("workplace").order_by("workplace__name", "date", "start_time")
        # Filter out today's shifts that haven't nearly ended (1h before end_time)
        one_hour = _td(hours=1)
        pending_shifts = [
            s for s in all_pending
            if s.date < today or (
                _dt.combine(today, s.end_time) - one_hour
            ).time() <= now_time
        ]

        pending_shifts_json = _json2.dumps([
            {
                "id": s.pk,
                "workplace_id": s.workplace_id,
                "workplace_name": s.workplace.name,
                "workplace_color": s.workplace.accent_color or s.workplace.color or _avatar_for_name(s.workplace.name)[1],
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
        pending_shifts_count = len(pending_shifts)

        # ── Today's shifts ──
        from datetime import datetime as _dt2
        import json as _json3
        all_todays_shifts = list(PlannedShift.objects.filter(
            workplace__is_active=True,
            status=PlannedShift.Status.PLANNED,
            date=today,
        ).select_related("workplace").order_by("start_time"))

        todays_banner = None
        todays_shifts_json = "[]"
        todays_banner_shifts_json = "[]"
        if all_todays_shifts:
            # Collect unique workplaces for icons and names
            workplaces_info = []
            seen_wp = set()
            for s in all_todays_shifts:
                if s.workplace_id not in seen_wp:
                    seen_wp.add(s.workplace_id)
                    wp = s.workplace
                    workplaces_info.append({
                        "name": wp.name,
                        "color": wp.color or _avatar_for_name(wp.name)[1],
                        "icon": wp.icon or "",
                        "custom_icon_url": wp.custom_icon.url if wp.custom_icon else "",
                        "initials": _avatar_for_name(wp.name)[0],
                    })

            # Oxford comma join for workplace names
            wp_names = [w["name"] for w in workplaces_info]
            if len(wp_names) == 1:
                wp_name_str = wp_names[0]
            elif len(wp_names) == 2:
                wp_name_str = wp_names[0] + " and " + wp_names[1]
            else:
                wp_name_str = ", ".join(wp_names[:-1]) + ", and " + wp_names[-1]

            todays_banner = {
                "workplace_name": wp_name_str,
                "workplaces": workplaces_info,
                "shifts": [
                    {
                        "start_time": s.start_time.strftime("%H:%M"),
                        "end_time": s.end_time.strftime("%H:%M"),
                        "net_hours": str(s.net_hours.quantize(Decimal("0.01"))),
                        "workplace_name": s.workplace.name,
                        "session_type": s.get_session_type_display(),
                    }
                    for s in all_todays_shifts
                ],
                "has_unconfirmed": any(not s.arrival_confirmed for s in all_todays_shifts),
                "multiple": len(all_todays_shifts) > 1,
            }

            # Unconfirmed shifts for the arrival queue (JS)
            unconfirmed = [s for s in all_todays_shifts if not s.arrival_confirmed]
            todays_shifts_json = _json3.dumps([
                {
                    "id": s.pk,
                    "start_time": s.start_time.strftime("%H:%M"),
                }
                for s in unconfirmed
            ])

            # All shifts for countdown timer (JS)
            todays_banner_shifts_json = _json3.dumps([
                {
                    "start_time": s.start_time.strftime("%H:%M"),
                    "end_time": s.end_time.strftime("%H:%M"),
                    "net_hours": str(s.net_hours.quantize(Decimal("0.01"))),
                    "workplace_name": s.workplace.name,
                    "session_type": s.get_session_type_display(),
                }
                for s in all_todays_shifts
            ])

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
                "total_planned_gross": total_planned_gross,
                "total_planned_net": total_planned_net,
                "total_combined_gross": total_earned_gross + total_planned_gross,
                "total_combined_net": total_earned_net + total_planned_net,
                "has_any_goal": has_any_goal,
                "total_goal_min": total_goal_min,
                "total_goal_max": total_goal_max,
                "total_planned_hours": total_planned_hours,
                "total_approved_hours": total_approved_hours,
                "goal_bar_max": total_goal_max if total_goal_max else total_goal_min,
                "goal_approved_pct": int(total_approved_hours * 100 / (total_goal_max or total_goal_min)) if has_any_goal and (total_goal_max or total_goal_min) else 0,
                "goal_planned_pct": int(total_planned_hours * 100 / (total_goal_max or total_goal_min)) if has_any_goal and (total_goal_max or total_goal_min) else 0,
                "cross_period_info": cross_period_info,
                "today": today,
                "pending_shifts_json": pending_shifts_json,
                "pending_shifts_count": pending_shifts_count,
                "todays_banner": todays_banner,
                "todays_shifts_json": todays_shifts_json,
                "todays_banner_shifts_json": todays_banner_shifts_json,
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
