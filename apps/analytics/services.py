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

from django.utils import timezone

from core.utils import (
    WEEKS_PER_MONTH,
    allocate_proportionally as _allocate,
    weekly_to_monthly_hours,
)
from payroll.services import PayrollPeriodService, SalaryEstimateService
from shifts.models import Shift, PlannedShift
from workplaces.models import Workplace, ContractTermSet


TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _period_bounds(workplace: Workplace, year: int, month: int):
    """(termset, period_start, period_end) for a workplace's payroll month.

    Analytics buckets by **payroll period, not calendar month**: for a workplace
    paid 20th→19th, the shifts worked 20–31 July belong to the August row, which
    is the month they are paid in. That keeps every row equal to a payday and
    makes this page agree with the dashboard, which already resolves periods
    this way. It also makes the year total "income paid in this year" rather than
    "hours worked in it" — the right basis for Danish tax, which is assessed on
    payment.
    """
    return PayrollPeriodService.resolve_period_bounds(workplace, year, month)


def _shift_hours_in_period(workplace: Workplace, start: date, end: date) -> Decimal:
    shifts = Shift.objects.filter(workplace=workplace, date__gte=start, date__lte=end)
    return sum((s.net_hours for s in shifts), Decimal("0"))


def _hours_by_termset(
    workplace: Workplace, start: date, end: date, today: date, use_planned: bool,
) -> tuple[dict[int, "_TermsetHours"], Decimal, Decimal]:
    """Group a period's net hours by the term set active on each shift's own date,
    split into approved and still-planned. Returns (buckets, actual, planned).

    Grouping by date is the mid-period rate fix: a raise on the 15th used to price
    the whole period at one representative rate. Planned shifts are counted only
    from *today* onwards — an earlier one should have been approved by now, and
    counting it would double up with the approved hours that replaced it. That one
    rule covers all three cases: a future period is entirely on/after today, a
    closed period entirely before it, and the current period splits at today.
    """
    buckets: dict[int, _TermsetHours] = {}
    actual_total = planned_total = Decimal("0")

    def bucket_for(d: date) -> "_TermsetHours | None":
        terms = workplace.active_termset_on(d)
        if terms is None:
            return None
        b = buckets.get(terms.pk)
        if b is None:
            b = buckets[terms.pk] = _TermsetHours(termset=terms)
        return b

    for shift in Shift.objects.filter(workplace=workplace, date__gte=start, date__lte=end):
        b = bucket_for(shift.date)
        if b is not None:
            b.actual += shift.net_hours
            actual_total += shift.net_hours

    if use_planned:
        lower = max(start, today)
        for planned in PlannedShift.objects.filter(
            workplace=workplace,
            status=PlannedShift.Status.PLANNED,
            date__gte=lower,
            date__lte=end,
        ):
            b = bucket_for(planned.date)
            if b is not None:
                b.planned += planned.net_hours
                planned_total += planned.net_hours

    return buckets, actual_total, planned_total




# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class _TermsetHours:
    """One term set's hours within a period, split by certainty."""
    termset: ContractTermSet
    actual: Decimal = Decimal("0")
    planned: Decimal = Decimal("0")
    projected: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.actual + self.planned + self.projected


@dataclass
class PayPart:
    """One certainty band of a period's pay. A period is normally a mix: the
    current one holds approved hours *and* hours still planned, and a salaried
    period splits at today by day."""
    hours: Decimal = Decimal("0")
    gross: Decimal = Decimal("0")
    net: Decimal = Decimal("0")
    # A band can be *in play* while still amounting to nothing: a future period
    # with no history projects zero hours, and that is a projection of zero, not
    # a worked zero. Without this the row would read as actual.
    active: bool = False

    @property
    def any(self) -> bool:
        return self.active or bool(self.hours or self.gross)


@dataclass
class MonthRow:
    year: int
    month: int
    label: str
    period_start: date
    period_end: date
    contract_active: bool
    actual: PayPart = field(default_factory=PayPart)
    planned: PayPart = field(default_factory=PayPart)
    projected: PayPart = field(default_factory=PayPart)
    # Net hours of real logged shifts in the period. Distinct from
    # ``actual.hours``, which for a salaried row is the *notional* hours behind
    # the salary — the salaried table shows the two side by side.
    logged_hours: Decimal = Decimal("0")

    @property
    def parts(self) -> list[tuple[str, PayPart]]:
        return [
            ("actual", self.actual),
            ("planned", self.planned),
            ("projected", self.projected),
        ]

    @property
    def hours(self) -> Decimal:
        return self.actual.hours + self.planned.hours + self.projected.hours

    @property
    def actual_hours(self) -> Decimal:
        return self.actual.hours

    @property
    def gross(self) -> Decimal:
        return self.actual.gross + self.planned.gross + self.projected.gross

    @property
    def net(self) -> Decimal:
        return self.actual.net + self.planned.net + self.projected.net

    @property
    def is_planned(self) -> bool:
        return self.planned.any

    @property
    def is_projected(self) -> bool:
        return self.projected.any

    @property
    def state(self) -> str:
        """The row's single-word state, for a table row that shows one colour.
        A mix names its least certain band, because a total is only as certain as
        its weakest ingredient."""
        if not self.contract_active:
            return "inactive"
        if self.projected.any:
            return "projected"
        if self.planned.any:
            return "actual-planned" if self.actual.any else "planned"
        return "actual"

    @property
    def is_mixed(self) -> bool:
        return sum(1 for _, p in self.parts if p.any) > 1


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
    def _trailing_periods(
        workplace: Workplace, n_months: int, ref: date,
    ) -> list[tuple[int, int, date, date]]:
        """The ``n_months`` payroll periods that have *closed* before ``ref``,
        oldest → newest, as (year, month, period_start, period_end).

        Closed-ness has to be tested against the period's own end date, not the
        calendar month: on 30 July a workplace paid 20th→19th has already closed
        its July period (20 Jun – 19 Jul), so walking back from "last calendar
        month" would skip a completed period and average one that is still open.
        """
        out: list[tuple[int, int, date, date]] = []
        y, m = ref.year, ref.month
        # Walk back far enough to fill the window even when the newest labelled
        # months are still open; two extra steps covers any single-month offset.
        for _ in range(n_months + 2):
            _terms, ps, pe = _period_bounds(workplace, y, m)
            if pe < ref:
                out.append((y, m, ps, pe))
                if len(out) == n_months:
                    break
            if m == 1:
                y, m = y - 1, 12
            else:
                m -= 1
        return list(reversed(out))

    @staticmethod
    def _aggregate(hours: list[Decimal], method: str) -> Decimal:
        """Reduce a trailing window of hours to one figure — the shared basis for
        the workplace's headline average and for each period's own projection."""
        if not hours:
            return Decimal("0")
        if method == "ema":
            alpha = Decimal(2) / Decimal(len(hours) + 1)
            ema = hours[0]
            for h in hours[1:]:
                ema = alpha * h + (Decimal("1") - alpha) * ema
            return ema.quantize(TWO_PLACES, ROUND_HALF_UP)
        total = sum(hours, Decimal("0"))
        return (total / Decimal(len(hours))).quantize(TWO_PLACES, ROUND_HALF_UP)

    @staticmethod
    def _hourly_period_hours(
        workplace: Workplace, year: int, month: int, today: date, use_planned: bool,
    ) -> Decimal | None:
        """A period's hours as they are actually known — approved plus whatever is
        still planned — or ``None`` when the period is not one an hourly average
        may learn from.

        ``None`` covers three cases, all of which must be *skipped* rather than
        counted as zero: no contract yet (pre-hire zeros would drag a new job's
        average down), no term set, and a period the workplace was **salaried**.
        Salaried periods often carry logged shifts, but those hours were never
        paid hourly, so pricing them at an hourly rate would invent income.
        """
        terms, ps, pe = _period_bounds(workplace, year, month)
        if terms is None or not workplace.contracts_in_period(ps, pe):
            return None
        if terms.employment_type != ContractTermSet.EmploymentType.HOURLY:
            return None
        _buckets, actual, planned = _hours_by_termset(
            workplace, ps, pe, today, use_planned,
        )
        return actual + planned

    @classmethod
    def _seed_window(
        cls, workplace: Workplace, first: tuple[int, int], n_months: int,
        today: date, use_planned: bool,
    ) -> list[Decimal]:
        """The hourly history immediately *before* the first visible period,
        oldest → newest, so the first projected period has a full window even when
        the page starts in January."""
        if n_months <= 0:
            return []
        out: list[Decimal] = []
        y, m = first
        for _ in range(n_months):
            if m == 1:
                y, m = y - 1, 12
            else:
                m -= 1
            hours = cls._hourly_period_hours(workplace, y, m, today, use_planned)
            if hours is not None:
                out.append(hours)
        return list(reversed(out))

    @classmethod
    def trailing_average_hours(
        cls, workplace: Workplace, n_months: int, ref: date | None = None,
        method: str = "avg",
    ) -> Decimal:
        """The workplace's headline recent average, anchored at ``ref`` — the
        figure shown on its card. Each *projected period* computes its own window
        instead (see ``project_period``), so this is a summary, not the forecast.
        """
        if n_months <= 0:
            return Decimal("0")
        ref = ref or timezone.localdate()

        # Only periods where the contract was actually active count. Periods
        # before the workplace was even a job would otherwise sit at 0 hours
        # and drag the average right down for the first few months of work.
        hours = [
            _shift_hours_in_period(workplace, ps, pe)
            for (_y, _m, ps, pe) in cls._trailing_periods(workplace, n_months, ref)
            if workplace.contracts_in_period(ps, pe)
        ]
        return cls._aggregate(hours, method)

    # ------------------------------------------------------------------
    # Yearly projection
    # ------------------------------------------------------------------

    @classmethod
    def project_year(
        cls, workplaces, year: int, trailing_months: int = 6,
        method: str = "ema", today: date | None = None,
        use_planned: bool = True,
    ) -> YearProjection:
        return cls.project_period(
            workplaces,
            start=date(year, 1, 1),
            end=date(year, 12, 31),
            trailing_months=trailing_months,
            method=method,
            today=today,
            use_planned=use_planned,
        )

    @classmethod
    def project_period(
        cls, workplaces, start: date, end: date,
        trailing_months: int = 6, method: str = "ema",
        today: date | None = None, use_planned: bool = True,
    ) -> YearProjection:
        today = today or timezone.localdate()
        if end < start:
            start, end = end, start

        # Every period resolves its own term set, and hourly hours are grouped by
        # the term set active on each shift's own date — both walk
        # ``contracts``/``term_sets``, which are plain properties, so without this
        # a year's projection costs hundreds of queries. Callers may pass a plain
        # list (tests do), so only a queryset gets the prefetch.
        if hasattr(workplaces, "prefetch_related"):
            workplaces = workplaces.prefetch_related("contracts__term_sets")

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

            # Each period projects from its *own* trailing window, so a projection
            # differs month to month instead of repeating one figure to December.
            # The window rolls forward on every period's resolved hours — approved,
            # still-planned, or (once past the last real data) what the previous
            # period projected. Feeding it approved hours alone would empty it as
            # it advanced into the future and decay every projection toward zero.
            window = cls._seed_window(
                wp, months[0], trailing_months, today, use_planned,
            ) if months else []

            for idx, (y, m) in enumerate(months):
                label = proj.monthly_labels[idx]
                termset, period_start, period_end = _period_bounds(wp, y, m)
                contract_active = bool(wp.contracts_in_period(period_start, period_end))

                logged_hours = _shift_hours_in_period(wp, period_start, period_end)

                if not contract_active or termset is None:
                    wp_proj.months.append(MonthRow(
                        year=y, month=m, label=label,
                        period_start=period_start, period_end=period_end,
                        contract_active=False,
                        logged_hours=logged_hours.quantize(TWO_PLACES, ROUND_HALF_UP),
                    ))
                    continue

                # A period is past once it has closed and current while today
                # falls inside it — read off the bounds, so an offset period is
                # judged by its own dates rather than by the calendar month it is
                # labelled with.
                is_past = period_end < today
                as_of = PayrollPeriodService.get_tax_pull_date(termset, y, m)

                if termset.employment_type == ContractTermSet.EmploymentType.HOURLY:
                    row = cls._hourly_row(
                        wp, y, m, label, period_start, period_end, today,
                        is_past=is_past, as_of=as_of,
                        trailing_avg=cls._aggregate(
                            window[-trailing_months:] if trailing_months > 0 else [],
                            method,
                        ),
                        use_planned=use_planned,
                    )
                    window.append(row.hours)
                else:
                    row = cls._salaried_row(
                        termset.contract, y, m, label, period_start, period_end,
                        today, as_of=as_of,
                    )
                    # A salaried period teaches an hourly average nothing.

                row.logged_hours = logged_hours.quantize(TWO_PLACES, ROUND_HALF_UP)
                wp_proj.months.append(row)
                wp_proj.year_gross += row.gross
                wp_proj.year_net += row.net
                proj.monthly_totals_gross[idx] += row.gross
                proj.monthly_totals_net[idx] += row.net

            proj.workplaces.append(wp_proj)
            proj.year_gross += wp_proj.year_gross
            proj.year_net += wp_proj.year_net

        return proj

    # ------------------------------------------------------------------
    # Per-period rows
    # ------------------------------------------------------------------

    @classmethod
    def _hourly_row(
        cls, workplace: Workplace, year: int, month: int, label: str,
        period_start: date, period_end: date, today: date, *,
        is_past: bool, as_of: date, trailing_avg: Decimal, use_planned: bool,
    ) -> MonthRow:
        """An hourly period: approved hours are actual, still-planned hours are
        planned, and a period with neither falls back to the projection."""
        buckets, actual_hours, planned_hours = _hours_by_termset(
            workplace, period_start, period_end, today, use_planned,
        )

        # The projection only fills a period that holds *nothing* real. A closed
        # period is whatever was worked — including zero, which is a fact, not a
        # gap to guess at. And a period that already has approved or planned hours
        # must not have an average added on top: those hours are part of what the
        # average predicts, so adding both would count them twice.
        projected_basis = not is_past and actual_hours == 0 and planned_hours == 0
        if projected_basis and trailing_avg > 0:
            terms = workplace.active_termset_on(period_end) or workplace.active_termset_on(period_start)
            if terms is not None:
                # Prorate to the days the contract actually covers, so a job
                # starting or ending mid-period is not credited a whole one.
                earned, planned_days, days_in_range = (
                    SalaryEstimateService.active_day_split_range(
                        terms, period_start, period_end, period_end,
                    )
                )
                covered = earned + planned_days
                projected = (
                    trailing_avg * covered / days_in_range
                ).quantize(TWO_PLACES, ROUND_HALF_UP) if days_in_range else Decimal("0")
                if projected > 0:
                    b = buckets.get(terms.pk)
                    if b is None:
                        b = buckets[terms.pk] = _TermsetHours(termset=terms)
                    b.projected += projected

        row = cls._compose_row(
            year, month, label, period_start, period_end,
            list(buckets.values()), as_of=as_of,
        )
        if projected_basis:
            row.projected.active = True
        return row

    @classmethod
    def _compose_row(
        cls, year: int, month: int, label: str,
        period_start: date, period_end: date,
        buckets: list[_TermsetHours], *, as_of: date,
    ) -> MonthRow:
        """Price each term set's own hours at its own rate, then split the period
        total across the three certainty bands.

        Estimating each band separately would apply the monthly personfradrag once
        per band and overstate net, so the period is estimated *once* and the parts
        are allocated from that total in proportion to their gross.
        """
        row = MonthRow(
            year=year, month=month, label=label,
            period_start=period_start, period_end=period_end,
            contract_active=True,
        )
        buckets = [b for b in buckets if b.total > 0]
        if not buckets:
            return row

        estimates = [
            SalaryEstimateService.estimate(b.termset, b.total, as_of=as_of)
            for b in buckets
        ]
        combined = SalaryEstimateService._combine_estimates(estimates, as_of=as_of)
        total_gross = combined.taxable_gross
        total_net = (
            combined.tax_breakdown.net_pay
            if combined.tax_breakdown else combined.taxable_gross
        )

        # Each band's gross is exact (hours × that term set's own rate); net is
        # allocated from the single period figure by gross share.
        band_gross = {"actual": Decimal("0"), "planned": Decimal("0"), "projected": Decimal("0")}
        band_hours = {"actual": Decimal("0"), "planned": Decimal("0"), "projected": Decimal("0")}
        for b, est in zip(buckets, estimates):
            shares = _allocate(est.taxable_gross, [b.actual, b.planned, b.projected])
            for name, hours, gross in zip(
                ("actual", "planned", "projected"),
                (b.actual, b.planned, b.projected),
                shares,
            ):
                band_hours[name] += hours
                band_gross[name] += gross

        names = ("actual", "planned", "projected")
        nets = _allocate(total_net, [band_gross[n] for n in names])
        # Rounding per term set can drift the summed band gross off the combined
        # figure; hand the difference to the largest band so the parts still add up.
        drift = total_gross - sum(band_gross.values(), Decimal("0"))
        if drift:
            band_gross[max(names, key=lambda n: band_gross[n])] += drift

        for name, net in zip(names, nets):
            setattr(row, name, PayPart(
                hours=band_hours[name].quantize(TWO_PLACES, ROUND_HALF_UP),
                gross=band_gross[name],
                net=net,
            ))
        return row

    @classmethod
    def _salaried_row(
        cls, contract, year: int, month: int, label: str,
        period_start: date, period_end: date, today: date, *, as_of: date,
    ) -> MonthRow:
        """A salaried period: the salary accrues per calendar day, so days up to
        and including today are actual and later ones are planned. A salary is
        never *projected* — it is known from the contract — so a fully past period
        comes out all actual and a future one all planned, with no special-casing.
        """
        row = MonthRow(
            year=year, month=month, label=label,
            period_start=period_start, period_end=period_end,
            contract_active=True,
        )
        lines = SalaryEstimateService.salaried_period_lines(
            contract, period_start, period_end, today,
        )
        if not lines:
            row.contract_active = False
            return row

        estimates = [
            SalaryEstimateService.estimate(
                line.termset, Decimal("0"), as_of=as_of,
                monthly_salary_override=line.covered_salary,
            )
            for line in lines
        ]
        combined = SalaryEstimateService._combine_estimates(estimates, as_of=as_of)
        total_gross = combined.taxable_gross
        total_net = (
            combined.tax_breakdown.net_pay
            if combined.tax_breakdown else combined.taxable_gross
        )

        actual_gross = planned_gross = Decimal("0")
        actual_hours = planned_hours = Decimal("0")
        for line, est in zip(lines, estimates):
            a_gross, p_gross = _allocate(
                est.taxable_gross, [Decimal(line.earned_days), Decimal(line.planned_days)],
            )
            actual_gross += a_gross
            planned_gross += p_gross
            # Notional hours behind the salary, split by the same day ratio.
            weekly = line.termset.expected_weekly_hours or Decimal("37")
            line_hours = (
                weekly_to_monthly_hours(weekly) * line.covered_days
                / ((period_end - period_start).days + 1)
            )
            a_hours, p_hours = _allocate(
                line_hours.quantize(TWO_PLACES, ROUND_HALF_UP),
                [Decimal(line.earned_days), Decimal(line.planned_days)],
            )
            actual_hours += a_hours
            planned_hours += p_hours

        drift = total_gross - (actual_gross + planned_gross)
        if drift:
            if actual_gross >= planned_gross:
                actual_gross += drift
            else:
                planned_gross += drift

        actual_net, planned_net = _allocate(total_net, [actual_gross, planned_gross])
        row.actual = PayPart(hours=actual_hours, gross=actual_gross, net=actual_net)
        row.planned = PayPart(hours=planned_hours, gross=planned_gross, net=planned_net)
        return row

    # ------------------------------------------------------------------
    # Rate history (now shows ContractTermSet history)
    # ------------------------------------------------------------------

    @staticmethod
    def rate_history(workplace: Workplace) -> list[dict]:
        """Return a chronological list of all ContractTermSet snapshots."""
        rows: list[dict] = []
        from django.db.models import Min
        ordered_contracts = (
            workplace.contracts.annotate(_start=Min("term_sets__effective_from"))
            .order_by("_start")
        )
        for contract in ordered_contracts:
            for ts in contract.term_sets.order_by("effective_from"):
                rows.append(_rate_row(ts, ts.effective_from))
        if not rows:
            # No contracts at all — return empty
            return rows
        return rows


def _rate_row(ts: ContractTermSet, as_of: date) -> dict:
    weekly = ts.expected_weekly_hours or Decimal("37")
    monthly_hours = weekly_to_monthly_hours(weekly).quantize(TWO_PLACES, ROUND_HALF_UP)

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
