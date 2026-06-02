"""
Analytics services.

Computes:
* trailing average hours per month/week for a workplace,
* projected gross/net pay per month for a year,
* rate history (gross + net hourly equivalent) over time.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q

from core.utils import WEEKS_PER_MONTH
from payroll.services import SalaryEstimateService
from shifts.models import Shift
from workplaces.models import Workplace, ContractTermSet


TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_iter(year: int):
    for m in range(1, 13):
        yield year, m


def _is_past_month(year: int, month: int, today: date | None = None) -> bool:
    today = today or date.today()
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day) < today


def _is_current_month(year: int, month: int, today: date | None = None) -> bool:
    today = today or date.today()
    return today.year == year and today.month == month


def _midmonth(year: int, month: int) -> date:
    return date(year, month, 15)


def _shift_hours_in_month(workplace: Workplace, year: int, month: int) -> Decimal:
    last_day = calendar.monthrange(year, month)[1]
    shifts = Shift.objects.filter(
        workplace=workplace,
        date__gte=date(year, month, 1),
        date__lte=date(year, month, last_day),
    )
    return sum((s.net_hours for s in shifts), Decimal("0"))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MonthRow:
    year: int
    month: int
    label: str
    hours: Decimal
    actual_hours: Decimal
    gross: Decimal
    net: Decimal
    is_projected: bool
    contract_active: bool


@dataclass
class WorkplaceProjection:
    workplace: Workplace
    trailing_avg_monthly_hours: Decimal
    trailing_avg_weekly_hours: Decimal
    months: list[MonthRow] = field(default_factory=list)
    year_gross: Decimal = Decimal("0")
    year_net: Decimal = Decimal("0")


@dataclass
class YearProjection:
    year: int
    trailing_months: int
    method: str
    start: date | None = None
    end: date | None = None
    workplaces: list[WorkplaceProjection] = field(default_factory=list)
    monthly_totals_gross: list[Decimal] = field(default_factory=list)
    monthly_totals_net: list[Decimal] = field(default_factory=list)
    monthly_labels: list[str] = field(default_factory=list)
    year_gross: Decimal = Decimal("0")
    year_net: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AnalyticsService:

    # ------------------------------------------------------------------
    # Trailing hours
    # ------------------------------------------------------------------

    @staticmethod
    def trailing_monthly_hours(
        workplace: Workplace, n_months: int, ref: date | None = None,
    ) -> list[Decimal]:
        ref = ref or date.today()
        if ref.month == 1:
            y, m = ref.year - 1, 12
        else:
            y, m = ref.year, ref.month - 1

        result: list[Decimal] = []
        for _ in range(n_months):
            result.append(_shift_hours_in_month(workplace, y, m))
            if m == 1:
                y, m = y - 1, 12
            else:
                m -= 1
        return list(reversed(result))

    @classmethod
    def trailing_average_hours(
        cls, workplace: Workplace, n_months: int, ref: date | None = None,
        method: str = "avg",
    ) -> Decimal:
        if n_months <= 0:
            return Decimal("0")
        hours = cls.trailing_monthly_hours(workplace, n_months, ref=ref)
        if not hours:
            return Decimal("0")

        if method == "ema":
            alpha = Decimal(2) / Decimal(n_months + 1)
            ema = hours[0]
            for h in hours[1:]:
                ema = alpha * h + (Decimal("1") - alpha) * ema
            return ema.quantize(TWO_PLACES, ROUND_HALF_UP)

        total = sum(hours, Decimal("0"))
        return (total / Decimal(n_months)).quantize(TWO_PLACES, ROUND_HALF_UP)

    # ------------------------------------------------------------------
    # Yearly projection
    # ------------------------------------------------------------------

    @classmethod
    def project_year(
        cls, workplaces, year: int, trailing_months: int = 6,
        method: str = "ema", today: date | None = None,
    ) -> YearProjection:
        return cls.project_period(
            workplaces,
            start=date(year, 1, 1),
            end=date(year, 12, 31),
            trailing_months=trailing_months,
            method=method,
            today=today,
        )

    @classmethod
    def project_period(
        cls, workplaces, start: date, end: date,
        trailing_months: int = 6, method: str = "ema",
        today: date | None = None,
    ) -> YearProjection:
        today = today or date.today()
        if end < start:
            start, end = end, start

        months: list[tuple[int, int]] = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            months.append((y, m))
            if m == 12:
                y, m = y + 1, 1
            else:
                m += 1

        proj = YearProjection(
            year=start.year, trailing_months=trailing_months,
            method=method, start=start, end=end,
        )
        multi_year = start.year != end.year
        proj.monthly_labels = [
            f"{calendar.month_abbr[mm]} {yy % 100:02d}" if multi_year
            else calendar.month_abbr[mm]
            for (yy, mm) in months
        ]
        proj.monthly_totals_gross = [Decimal("0") for _ in months]
        proj.monthly_totals_net = [Decimal("0") for _ in months]

        for wp in workplaces:
            trailing_avg = cls.trailing_average_hours(wp, trailing_months, ref=today, method=method)
            weekly_avg = (trailing_avg / WEEKS_PER_MONTH).quantize(TWO_PLACES, ROUND_HALF_UP)
            wp_proj = WorkplaceProjection(
                workplace=wp,
                trailing_avg_monthly_hours=trailing_avg,
                trailing_avg_weekly_hours=weekly_avg,
            )

            for idx, (y, m) in enumerate(months):
                label = proj.monthly_labels[idx]
                last_day = calendar.monthrange(y, m)[1]
                month_start = date(y, m, 1)
                month_end = date(y, m, last_day)
                contract_active = wp.contracts_in_period(month_start, month_end).exists()
                actual_hours_in_month = _shift_hours_in_month(wp, y, m)

                if not contract_active:
                    wp_proj.months.append(MonthRow(
                        year=y, month=m, label=label,
                        hours=Decimal("0"),
                        actual_hours=actual_hours_in_month,
                        gross=Decimal("0"), net=Decimal("0"),
                        is_projected=False, contract_active=False,
                    ))
                    continue

                is_past = _is_past_month(y, m, today)
                as_of = _midmonth(y, m)

                # Resolve the active termset for this month
                termset = wp.active_termset_on(as_of)
                if termset is None:
                    # Contract exists but no termset found — skip
                    wp_proj.months.append(MonthRow(
                        year=y, month=m, label=label,
                        hours=Decimal("0"),
                        actual_hours=actual_hours_in_month,
                        gross=Decimal("0"), net=Decimal("0"),
                        is_projected=False, contract_active=False,
                    ))
                    continue

                if termset.employment_type == ContractTermSet.EmploymentType.HOURLY:
                    if is_past:
                        hours = actual_hours_in_month
                        is_projected = False
                    else:
                        hours = trailing_avg
                        is_projected = True
                    estimate = SalaryEstimateService.estimate(termset, hours, as_of=as_of)
                else:  # SALARIED
                    weekly = termset.expected_weekly_hours or Decimal("37")
                    hours = (weekly * Decimal("52") / Decimal("12")).quantize(TWO_PLACES, ROUND_HALF_UP)
                    is_projected = not is_past
                    estimate = SalaryEstimateService.estimate(termset, hours, as_of=as_of)

                gross = estimate.taxable_gross
                net = (
                    estimate.tax_breakdown.net_pay
                    if estimate.tax_breakdown
                    else estimate.taxable_gross
                )

                wp_proj.months.append(MonthRow(
                    year=y, month=m, label=label,
                    hours=hours.quantize(TWO_PLACES, ROUND_HALF_UP),
                    actual_hours=actual_hours_in_month.quantize(TWO_PLACES, ROUND_HALF_UP),
                    gross=gross, net=net,
                    is_projected=is_projected, contract_active=True,
                ))
                wp_proj.year_gross += gross
                wp_proj.year_net += net
                proj.monthly_totals_gross[idx] += gross
                proj.monthly_totals_net[idx] += net

            proj.workplaces.append(wp_proj)
            proj.year_gross += wp_proj.year_gross
            proj.year_net += wp_proj.year_net

        return proj

    # ------------------------------------------------------------------
    # Rate history (now shows ContractTermSet history)
    # ------------------------------------------------------------------

    @staticmethod
    def rate_history(workplace: Workplace) -> list[dict]:
        """Return a chronological list of all ContractTermSet snapshots."""
        rows: list[dict] = []
        for contract in workplace.contracts.order_by("start_date"):
            for ts in contract.term_sets.order_by("effective_from"):
                rows.append(_rate_row(ts, ts.effective_from))
        if not rows:
            # No contracts at all — return empty
            return rows
        return rows


def _rate_row(ts: ContractTermSet, as_of: date) -> dict:
    weekly = ts.expected_weekly_hours or Decimal("37")
    monthly_hours = (weekly * Decimal("52") / Decimal("12")).quantize(TWO_PLACES, ROUND_HALF_UP)

    estimate = SalaryEstimateService.estimate(ts, monthly_hours, as_of=as_of)

    gross_monthly = estimate.taxable_gross
    net_monthly = (
        estimate.tax_breakdown.net_pay if estimate.tax_breakdown else gross_monthly
    )
    net_hourly = (
        (net_monthly / monthly_hours).quantize(TWO_PLACES, ROUND_HALF_UP)
        if monthly_hours > 0 else Decimal("0")
    )

    return {
        "effective_from": as_of,
        "hourly_rate": ts.hourly_rate,
        "monthly_salary": ts.monthly_salary,
        "base_hourly": ts.base_hourly_rate,
        "effective_hourly": ts.effective_hourly_rate,
        "total_hourly": ts.total_hourly_rate,
        "gross_monthly": gross_monthly,
        "net_monthly": net_monthly,
        "net_hourly": net_hourly,
        "monthly_hours": monthly_hours,
        "contract_name": ts.contract.name or str(ts.contract.start_date),
    }
