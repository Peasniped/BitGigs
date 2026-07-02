"""
Dashboard data service — aggregates stats for the main dashboard.

Used by both the full-page DashboardView and the DashboardStatsAPIView
to avoid logic duplication.
"""
import calendar as cal_mod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from core.utils import WEEKS_PER_MONTH, avatar_for_name
from payroll.services import PayrollPeriodService, SalaryEstimateService
from shifts.models import Shift, PlannedShift
from workplaces.models import Workplace, ContractTermSet
from workplaces.services import workplaces_active_today, workplaces_active_in_period


TWO_PLACES = Decimal("0.01")


@dataclass
class DashboardStats:
    """Core stat card values shared between full-page and API responses."""
    total_earned_gross: Decimal = Decimal("0")
    total_earned_net: Decimal = Decimal("0")
    total_planned_gross: Decimal = Decimal("0")
    total_planned_net: Decimal = Decimal("0")
    has_any_goal: bool = False
    total_goal_min: Decimal = Decimal("0")
    total_goal_max: Decimal = Decimal("0")
    total_planned_hours: Decimal = Decimal("0")
    total_approved_hours: Decimal = Decimal("0")

    @property
    def combined_gross(self) -> Decimal:
        return self.total_earned_gross + self.total_planned_gross

    @property
    def combined_net(self) -> Decimal:
        return self.total_earned_net + self.total_planned_net

    @property
    def goal_denom(self) -> Decimal:
        return self.total_goal_max if self.total_goal_max else self.total_goal_min

    @property
    def goal_approved_pct(self) -> int:
        if self.has_any_goal and self.goal_denom:
            return int(self.total_approved_hours * 100 / self.goal_denom)
        return 0

    @property
    def goal_planned_pct(self) -> int:
        if self.has_any_goal and self.goal_denom:
            return int(self.total_planned_hours * 100 / self.goal_denom)
        return 0


@dataclass
class PayBreakdown:
    """Earned/planned gross+net for a single workplace over a month."""
    earned_gross: Decimal = Decimal("0")
    earned_net: Decimal = Decimal("0")
    planned_gross: Decimal = Decimal("0")
    planned_net: Decimal = Decimal("0")


@dataclass
class DashboardData:
    """Full dashboard context (stats + per-workplace details + banners)."""
    stats: DashboardStats = field(default_factory=DashboardStats)
    workplace_data: list = field(default_factory=list)
    period_boundaries: list = field(default_factory=list)
    cross_period_info: list = field(default_factory=list)


class DashboardDataService:
    """Aggregate dashboard data for a given month."""

    @classmethod
    def get_stats(cls, year: int, month: int) -> DashboardStats:
        """Compute stat-card values only (used by the JSON API)."""
        stats = DashboardStats()
        today = date.today()
        import calendar as _cal_
        _m_start = date(year, month, 1)
        _m_end = date(year, month, _cal_.monthrange(year, month)[1])
        workplaces = workplaces_active_in_period(_m_start, _m_end)

        for wp in workplaces:
            # Bootstrap period using the month's representative termset
            # (payroll_period_start_day needed).
            _terms_mid = wp.active_termset_in_month(year, month)
            if _terms_mid:
                period_start, period_end = PayrollPeriodService.get_period_dates(_terms_mid, year, month)
            else:
                period_start = date(year, month, 1)
                period_end = date(year, month, _cal_.monthrange(year, month)[1])

            actual_hours = cls._sum_shift_hours(wp, period_start, period_end)
            planned_hours = cls._sum_planned_hours(wp, period_start, period_end)

            # Resolve terms with the mid-month termset, not period_start: when
            # payroll_period_start_day != 1, period_start falls in the previous
            # month and predates a contract/termset that first takes effect this
            # month, which would wrongly yield None (no pay, no hour-goal card).
            terms = _terms_mid
            tax_pull_date = PayrollPeriodService.get_tax_pull_date(terms, year, month) if terms else period_end
            pay = cls._compute_pay(terms, actual_hours, planned_hours, year, month, tax_pull_date, today)
            stats.total_earned_gross += pay.earned_gross
            stats.total_earned_net += pay.earned_net
            stats.total_planned_gross += pay.planned_gross
            stats.total_planned_net += pay.planned_net

            cls._accumulate_goals(stats, terms)
            stats.total_planned_hours += planned_hours
            stats.total_approved_hours += actual_hours

        return stats

    @classmethod
    def get_full(cls, year: int, month: int) -> DashboardData:
        """Compute full dashboard data (stats + workplace cards + cross-period info)."""
        data = DashboardData()
        today = date.today()
        import calendar as _cal_
        _m_start = date(year, month, 1)
        _m_end = date(year, month, _cal_.monthrange(year, month)[1])
        workplaces = workplaces_active_in_period(_m_start, _m_end)

        for wp in workplaces:
            # Bootstrap period using the month's representative termset.
            _terms_mid = wp.active_termset_in_month(year, month)
            if _terms_mid:
                period_start, period_end = PayrollPeriodService.get_period_dates(_terms_mid, year, month)
            else:
                period_start = date(year, month, 1)
                period_end = date(year, month, _cal_.monthrange(year, month)[1])

            data.period_boundaries.append({
                "workplace_name": wp.name,
                "color": wp.accent_color or wp.color or "#6366f1",
                "start": period_start.isoformat(),
                "end": period_end.isoformat(),
            })

            # Cross-period detection
            cls._detect_cross_period(data, wp, year, month, period_start, period_end)

            # Actual hours worked
            actual_hours = cls._sum_shift_hours(wp, period_start, period_end)
            avg_hours_per_week = (actual_hours / WEEKS_PER_MONTH).quantize(TWO_PLACES)

            # Planned hours
            planned_hours = cls._sum_planned_hours(wp, period_start, period_end)

            # See get_stats: resolve terms with the mid-month termset so a
            # contract/termset first effective this month isn't missed.
            terms = _terms_mid
            tax_pull_date = PayrollPeriodService.get_tax_pull_date(terms, year, month) if terms else period_end
            pay = cls._compute_pay(terms, actual_hours, planned_hours, year, month, tax_pull_date, today)
            data.stats.total_earned_gross += pay.earned_gross
            data.stats.total_earned_net += pay.earned_net
            data.stats.total_planned_gross += pay.planned_gross
            data.stats.total_planned_net += pay.planned_net

            # Hour goals
            cls._accumulate_goals(data.stats, terms)
            data.stats.total_planned_hours += planned_hours
            data.stats.total_approved_hours += actual_hours

            data.workplace_data.append({
                "workplace": wp,
                "actual_hours": actual_hours,
                "avg_hours_per_week": avg_hours_per_week,
                "earned_gross": pay.earned_gross,
                "earned_net": pay.earned_net,
                "planned_gross": pay.planned_gross,
                "avatar_initials": avatar_for_name(wp.name)[0],
                "avatar_color": avatar_for_name(wp.name)[1],
            })

        return data

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_pay(
        terms, actual_hours: Decimal, planned_hours: Decimal,
        year: int, month: int, tax_pull_date: date, today: date,
    ) -> PayBreakdown:
        """Split pay into earned (up to today) and planned (after today).

        Hourly: earned from approved hours, planned from planned hours.
        Salaried: the monthly salary accrues per calendar day the contract is
        active. Days on or before *today* are earned, later days planned — so a
        contract starting mid-month shows its prorated salary as planned until
        each day arrives (Månedsløn × lønnede dage / dage i måneden).
        """
        pay = PayBreakdown()
        if terms is None:
            return pay

        if terms.employment_type == ContractTermSet.EmploymentType.HOURLY:
            earned = SalaryEstimateService.estimate(terms, actual_hours, as_of=tax_pull_date)
            pay.earned_gross = earned.taxable_gross
            pay.earned_net = earned.tax_breakdown.net_pay if earned.tax_breakdown else earned.taxable_gross
            if planned_hours:
                planned = SalaryEstimateService.estimate(terms, planned_hours, as_of=tax_pull_date)
                pay.planned_gross = planned.taxable_gross
                pay.planned_net = planned.tax_breakdown.net_pay if planned.tax_breakdown else planned.taxable_gross
            return pay

        # Salaried — a month may span several term sets (e.g. a mid-month
        # raise), so sum each one's prorated pay by the days it is the active
        # rate. Days on or before today are Earned, later ones Planned.
        month_end = date(year, month, cal_mod.monthrange(year, month)[1])
        term_sets = terms.contract.term_sets.filter(
            effective_from__lte=month_end,
            employment_type=ContractTermSet.EmploymentType.SALARIED,
        )
        for ts in term_sets:
            earned_days, planned_days, days_in_month = SalaryEstimateService.active_day_split(
                ts, year, month, today
            )
            covered_days = earned_days + planned_days
            if covered_days == 0:
                continue
            covered_salary = (
                (ts.monthly_salary or Decimal("0")) * covered_days / days_in_month
            ).quantize(TWO_PLACES)
            est = SalaryEstimateService.estimate(
                ts, Decimal("0"), as_of=tax_pull_date,
                monthly_salary_override=covered_salary,
            )
            total_gross = est.taxable_gross
            total_net = est.tax_breakdown.net_pay if est.tax_breakdown else est.taxable_gross

            # Tax is computed once per term set on its covered salary; the
            # earned/planned split is then linear by day.
            earned_ratio = Decimal(earned_days) / Decimal(covered_days)
            earned_gross = (total_gross * earned_ratio).quantize(TWO_PLACES)
            earned_net = (total_net * earned_ratio).quantize(TWO_PLACES)
            pay.earned_gross += earned_gross
            pay.earned_net += earned_net
            pay.planned_gross += total_gross - earned_gross
            pay.planned_net += total_net - earned_net
        return pay

    @staticmethod
    def _sum_shift_hours(wp: Workplace, period_start: date, period_end: date) -> Decimal:
        shifts = Shift.objects.filter(
            workplace=wp,
            date__gte=period_start,
            date__lte=period_end,
        )
        return sum((s.net_hours for s in shifts), Decimal("0"))

    @staticmethod
    def _sum_planned_hours(wp: Workplace, period_start: date, period_end: date) -> Decimal:
        return sum(
            (p.net_hours for p in PlannedShift.objects.filter(
                workplace=wp,
                date__gte=period_start,
                date__lte=period_end,
                status=PlannedShift.Status.PLANNED,
            )),
            Decimal("0"),
        )

    @staticmethod
    def _accumulate_goals(stats: DashboardStats, terms) -> None:
        if terms and terms.hour_goal_type and terms.hour_goal_min:
            stats.has_any_goal = True
            goal_min = terms.hour_goal_min
            goal_max = terms.hour_goal_max or Decimal("0")
            if terms.hour_goal_type == "weekly":
                goal_min = goal_min * WEEKS_PER_MONTH
                goal_max = goal_max * WEEKS_PER_MONTH if goal_max else Decimal("0")
            stats.total_goal_min += goal_min
            stats.total_goal_max += goal_max

    @staticmethod
    def _detect_cross_period(
        data: DashboardData, wp: Workplace,
        year: int, month: int,
        period_start: date, period_end: date,
    ) -> None:
        first_of_month = date(year, month, 1)

        # Shifts from previous month belonging to this payroll period
        if period_start < first_of_month:
            prev_shifts = Shift.objects.filter(
                workplace=wp, date__gte=period_start, date__lt=first_of_month,
            )
            prev_planned = PlannedShift.objects.filter(
                workplace=wp, date__gte=period_start, date__lt=first_of_month,
                status=PlannedShift.Status.PLANNED,
            )
            count = prev_shifts.count() + prev_planned.count()
            hours = sum((s.net_hours for s in prev_shifts), Decimal("0"))
            hours += sum((p.net_hours for p in prev_planned), Decimal("0"))
            if count > 0:
                data.cross_period_info.append({
                    "workplace": wp.name,
                    "color": wp.accent_color or wp.color or "#6366f1",
                    "count": count,
                    "hours": hours,
                    "direction": "prev",
                    "other_month": cal_mod.month_name[period_start.month],
                    "payroll_month": cal_mod.month_name[month],
                })

        # Shifts in this month belonging to next payroll period
        last_of_month = date(year, month, cal_mod.monthrange(year, month)[1])
        if period_end < last_of_month:
            next_shifts = Shift.objects.filter(
                workplace=wp, date__gt=period_end, date__lte=last_of_month,
            )
            next_planned = PlannedShift.objects.filter(
                workplace=wp, date__gt=period_end, date__lte=last_of_month,
                status=PlannedShift.Status.PLANNED,
            )
            count = next_shifts.count() + next_planned.count()
            hours = sum((s.net_hours for s in next_shifts), Decimal("0"))
            hours += sum((p.net_hours for p in next_planned), Decimal("0"))
            if count > 0:
                nm = 1 if month == 12 else month + 1
                data.cross_period_info.append({
                    "workplace": wp.name,
                    "color": wp.accent_color or wp.color or "#6366f1",
                    "count": count,
                    "hours": hours,
                    "direction": "next",
                    "other_month": cal_mod.month_name[month],
                    "payroll_month": cal_mod.month_name[nm],
                })


def get_pending_shifts(today: date) -> tuple[list, int]:
    """Return (list, count) of shifts pending approval (for json_script)."""
    now_time = datetime.now().time()
    all_pending = PlannedShift.objects.filter(
        workplace__in=workplaces_active_today(),
        status=PlannedShift.Status.PLANNED,
        date__lte=today,
    ).select_related("workplace").order_by("workplace__name", "date", "start_time")

    one_hour = timedelta(hours=1)
    pending_shifts = [
        s for s in all_pending
        if s.date < today or (
            datetime.combine(today, s.end_time) - one_hour
        ).time() <= now_time
    ]

    pending_data = [
        {
            "id": s.pk,
            "workplace_id": s.workplace_id,
            "workplace_name": s.workplace.name,
            "workplace_color": s.workplace.accent_color or s.workplace.color or avatar_for_name(s.workplace.name)[1],
            "date": s.date.isoformat(),
            "start_time": s.start_time.strftime("%H:%M"),
            "end_time": s.end_time.strftime("%H:%M"),
            "break_minutes": s.break_minutes,
            "shift_type": s.shift_type,
            "shift_type_display": s.get_shift_type_display(),
            "net_hours": str(s.net_hours.quantize(TWO_PLACES)),
        }
        for s in pending_shifts
    ]
    return pending_data, len(pending_shifts)


def get_todays_banner(today: date) -> tuple[dict | None, list, list]:
    """Return (banner_dict_or_None, shifts_list, banner_shifts_list) for json_script."""
    all_todays_shifts = list(PlannedShift.objects.filter(
        workplace__in=workplaces_active_today(),
        status=PlannedShift.Status.PLANNED,
        date=today,
    ).select_related("workplace").order_by("start_time"))

    if not all_todays_shifts:
        return None, [], []

    workplaces_info = []
    seen_wp = set()
    for s in all_todays_shifts:
        if s.workplace_id not in seen_wp:
            seen_wp.add(s.workplace_id)
            wp = s.workplace
            workplaces_info.append({
                "name": wp.name,
                "color": wp.color or avatar_for_name(wp.name)[1],
                "icon": wp.icon or "",
                "custom_icon_url": wp.custom_icon.url if wp.custom_icon else "",
                "initials": avatar_for_name(wp.name)[0],
            })

    # Oxford comma join
    wp_names = [w["name"] for w in workplaces_info]
    if len(wp_names) == 1:
        wp_name_str = wp_names[0]
    elif len(wp_names) == 2:
        wp_name_str = wp_names[0] + " and " + wp_names[1]
    else:
        wp_name_str = ", ".join(wp_names[:-1]) + ", and " + wp_names[-1]

    banner = {
        "workplace_name": wp_name_str,
        "workplaces": workplaces_info,
        "shifts": [
            {
                "start_time": s.start_time.strftime("%H:%M"),
                "end_time": s.end_time.strftime("%H:%M"),
                "net_hours": str(s.net_hours.quantize(TWO_PLACES)),
                "workplace_name": s.workplace.name,
                "shift_type": s.get_shift_type_display(),
            }
            for s in all_todays_shifts
        ],
        "has_unconfirmed": any(not s.arrival_confirmed for s in all_todays_shifts),
        "multiple": len(all_todays_shifts) > 1,
    }

    # Unconfirmed shifts for the arrival queue (JS)
    unconfirmed = [s for s in all_todays_shifts if not s.arrival_confirmed]
    todays_shifts_data = [
        {"id": s.pk, "start_time": s.start_time.strftime("%H:%M")}
        for s in unconfirmed
    ]

    # All shifts for countdown timer (JS)
    banner_shifts_data = [
        {
            "start_time": s.start_time.strftime("%H:%M"),
            "end_time": s.end_time.strftime("%H:%M"),
            "net_hours": str(s.net_hours.quantize(TWO_PLACES)),
            "workplace_name": s.workplace.name,
            "shift_type": s.get_shift_type_display(),
        }
        for s in all_todays_shifts
    ]

    return banner, todays_shifts_data, banner_shifts_data
