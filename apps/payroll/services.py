"""
Payroll services — period generation, salary estimates, flex time,
payslip building, vacation tracking, commuting.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from workplaces.models import Workplace, ContractTermSet
from shifts.models import Shift
from core.services import TaxCalculationService, TaxBreakdown, ATPService
from core.utils import month_bounds, weekly_to_monthly_hours

TWO_PLACES = Decimal("0.01")
# Danish standard vacation accrual: 25 days/year over 12 months.
VACATION_DAYS_PER_MONTH = Decimal("2.08")
FERIEPENGE_PERCENT = Decimal("12.50")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_termset_for_period(period) -> ContractTermSet | None:
    """Return the ContractTermSet active at the start of a payroll period."""
    return period.workplace.active_termset_on(period.start_date)


# ---------------------------------------------------------------------------
# Payroll Period Service
# ---------------------------------------------------------------------------

class PayrollPeriodService:
    """Generate and query payroll periods based on workplace/termset config."""

    @staticmethod
    def get_period_dates(settings, year: int, month: int) -> tuple[date, date]:
        """
        Return (start_date, end_date) for the payroll period.
        *settings* is any object with a ``payroll_period_start_day`` attribute
        (either a ContractTermSet or duck-typed equivalent).
        """
        start_day = settings.payroll_period_start_day
        if start_day == 1:
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, 1), date(year, month, last_day)

        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1

        prev_last = calendar.monthrange(prev_year, prev_month)[1]
        actual_start_day = min(start_day, prev_last)
        start_date = date(prev_year, prev_month, actual_start_day)

        cur_last = calendar.monthrange(year, month)[1]
        end_day = min(start_day - 1, cur_last)
        end_date = date(year, month, end_day)

        return start_date, end_date

    @staticmethod
    def get_payroll_month(settings, d: date) -> tuple[int, int]:
        """
        Return (year, month) of the payroll period that contains date *d*.
        *settings* is any object with a ``payroll_period_start_day`` attribute.
        """
        start_day = settings.payroll_period_start_day
        if start_day == 1:
            return d.year, d.month
        if d.day >= start_day:
            if d.month == 12:
                return d.year + 1, 1
            return d.year, d.month + 1
        return d.year, d.month

    @staticmethod
    def get_tax_pull_date(settings, year: int, month: int) -> date:
        """Return the tax card pull date for a payroll period month.
        *settings* is any object with a ``tax_pull_day`` attribute.
        """
        pull_day = settings.tax_pull_day
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(pull_day, last_day))

    @classmethod
    def resolve_period_bounds(cls, workplace: Workplace, year: int, month: int):
        """Return (termset, period_start, period_end) for a workplace's payroll
        month: the month's representative term set decides the period; without
        one the period is the plain calendar month."""
        terms = workplace.active_termset_in_month(year, month)
        if terms is not None:
            start_date, end_date = cls.get_period_dates(terms, year, month)
        else:
            last_day = calendar.monthrange(year, month)[1]
            start_date = date(year, month, 1)
            end_date = date(year, month, last_day)
        return terms, start_date, end_date

    @classmethod
    def get_or_create_period(cls, workplace: Workplace, year: int, month: int):
        """Get or create the PayrollPeriod object for a workplace and month."""
        from .models import PayrollPeriod

        _terms, start_date, end_date = cls.resolve_period_bounds(workplace, year, month)

        period, created = PayrollPeriod.objects.get_or_create(
            workplace=workplace,
            start_date=start_date,
            defaults={"end_date": end_date},
        )
        if created:
            cls._populate_template_lines(period)
            cls._carry_forward_custom_lines(period)
        return period, created

    @staticmethod
    @transaction.atomic
    def _populate_template_lines(period):
        from .models import PayslipLine, PayslipLineTemplate

        templates = PayslipLineTemplate.objects.filter(
            workplace=period.workplace
        ).order_by("sort_order")
        lines = []
        for tmpl in templates:
            lines.append(
                PayslipLine(
                    payroll_period=period,
                    name=tmpl.name,
                    quantity=tmpl.default_quantity,
                    rate=tmpl.default_rate,
                    amount=tmpl.default_amount or Decimal("0"),
                    line_type=tmpl.line_type,
                    rounding_method=tmpl.rounding_method,
                    sort_order=tmpl.sort_order,
                )
            )
        PayslipLine.objects.bulk_create(lines)

    @staticmethod
    def _carry_forward_custom_lines(period):
        from .models import PayslipLine, PayrollPeriod

        prev_period = (
            PayrollPeriod.objects
            .filter(workplace=period.workplace, start_date__lt=period.start_date)
            .order_by("-start_date")
            .first()
        )
        if not prev_period:
            return

        custom_lines = PayslipLine.objects.filter(
            payroll_period=prev_period,
            standard_line_key__isnull=True,
        ).order_by("sort_order")

        for cl in custom_lines:
            PayslipLine.objects.create(
                payroll_period=period,
                name=cl.name,
                quantity=cl.quantity,
                rate=cl.rate,
                amount=cl.amount,
                line_type=cl.line_type,
                rounding_method=cl.rounding_method,
                is_editable=True,
                sort_order=cl.sort_order,
            )


# ---------------------------------------------------------------------------
# Salary Estimate Service
# ---------------------------------------------------------------------------

@dataclass
class SalaryEstimate:
    workplace_name: str
    employment_type: str
    total_hours: Decimal
    hourly_rate: Decimal | None
    effective_hourly_rate: Decimal | None
    total_hourly_rate: Decimal | None
    monthly_salary: Decimal | None
    gross_pay: Decimal
    fritvalgskonto: Decimal
    taxable_gross: Decimal
    pension_basis: Decimal
    employee_pension: Decimal
    employer_pension: Decimal
    total_pension: Decimal
    employee_atp: Decimal
    employer_atp: Decimal
    tax_breakdown: TaxBreakdown | None


@dataclass
class SalariedMonthLine:
    """One salaried term set's contribution to a calendar month: how many of the
    month's days it is the active rate (split earned/planned by a reference date)
    and its salary prorated to those days."""
    termset: "ContractTermSet"
    earned_days: int
    planned_days: int
    covered_days: int
    covered_salary: Decimal


class SalaryEstimateService:
    """Calculate gross pay for a payroll period."""

    @staticmethod
    def estimate(
        terms: ContractTermSet,
        total_hours: Decimal,
        as_of: date | None = None,
        monthly_salary_override: Decimal | None = None,
    ) -> SalaryEstimate:
        hourly_rate, monthly_salary = terms.get_rate_as_of(as_of)
        if monthly_salary_override is not None:
            monthly_salary = monthly_salary_override

        if terms.employment_type == ContractTermSet.EmploymentType.HOURLY:
            base_rate = hourly_rate or Decimal("0")
            gross = (total_hours * base_rate).quantize(TWO_PLACES, ROUND_HALF_UP)
        else:
            gross = monthly_salary or Decimal("0")

        fritvalg_basis = Decimal("0")
        if (
            getattr(terms, "fritvalgskonto_enabled", False)
            and terms.fritvalgskonto_percent
            and terms.fritvalgskonto_percent > 0
        ):
            fritvalg_basis = (
                gross * terms.fritvalgskonto_percent / Decimal("100")
            ).quantize(TWO_PLACES, ROUND_HALF_UP)

        feriepenge_basis = Decimal("0")
        if terms.vacation_type == ContractTermSet.VacationType.FERIEKONTO:
            feriepenge_basis = (
                gross * FERIEPENGE_PERCENT / Decimal("100")
            ).quantize(TWO_PLACES, ROUND_HALF_UP)

        taxable_gross = (gross + fritvalg_basis).quantize(TWO_PLACES, ROUND_HALF_UP)
        pension_basis = (gross + fritvalg_basis + feriepenge_basis).quantize(TWO_PLACES, ROUND_HALF_UP)

        employee_pension = (
            pension_basis * terms.pension_employee_percent / Decimal("100")
        ).quantize(TWO_PLACES, ROUND_HALF_UP)
        employer_pension = (
            pension_basis * terms.pension_employer_percent / Decimal("100")
        ).quantize(TWO_PLACES, ROUND_HALF_UP)

        if terms.employment_type == ContractTermSet.EmploymentType.SALARIED:
            weekly = terms.expected_weekly_hours or Decimal("37")
            atp_hours = weekly_to_monthly_hours(weekly).quantize(TWO_PLACES)
        else:
            atp_hours = total_hours
        employee_atp, employer_atp = ATPService.get_contributions(atp_hours, as_of=as_of)

        tax_breakdown = TaxCalculationService.calculate(
            taxable_gross,
            as_of=as_of,
            tax_card_type=terms.tax_card_type,
            employee_pension=employee_pension,
            employee_atp=employee_atp,
        )

        # Derive workplace name from contract if available
        try:
            wp_name = terms.contract.workplace.name
        except Exception:
            wp_name = ""

        return SalaryEstimate(
            workplace_name=wp_name,
            employment_type=terms.employment_type,
            total_hours=total_hours,
            hourly_rate=hourly_rate,
            effective_hourly_rate=terms.effective_hourly_rate,
            total_hourly_rate=terms.total_hourly_rate,
            monthly_salary=monthly_salary,
            gross_pay=gross,
            fritvalgskonto=fritvalg_basis,
            taxable_gross=taxable_gross,
            pension_basis=pension_basis,
            employee_pension=employee_pension,
            employer_pension=employer_pension,
            total_pension=employee_pension + employer_pension,
            employee_atp=employee_atp,
            employer_atp=employer_atp,
            tax_breakdown=tax_breakdown,
        )

    @staticmethod
    def _termset_active_range(terms: ContractTermSet) -> tuple[date, date | None]:
        """The date range during which *terms* is the active pay rate within its
        contract: from its effective_from until the day before the next term set
        starts, capped by its own effective_until. ``end`` is None when
        open-ended (last term set with no end date)."""
        contract = terms.contract
        next_ts = (
            contract.term_sets
            .filter(effective_from__gt=terms.effective_from)
            .order_by("effective_from")
            .first()
        )
        end = terms.effective_until  # may be None (open-ended)
        if next_ts:
            boundary = next_ts.effective_from - timedelta(days=1)
            end = boundary if end is None else min(end, boundary)
        return terms.effective_from, end

    @classmethod
    def active_day_split_range(
        cls, terms: ContractTermSet, start: date, end: date, today: date,
    ) -> tuple[int, int, int]:
        """Split the days of [start, end] by the days *terms* is the active pay
        rate: days on or before *today* are earned, later ones planned. The pay
        rate comes from the term set, so proration follows the term set's
        effective window (not the whole contract). Returns
        (earned_days, planned_days, days_in_range).

        The range form is what an offset payroll period needs (a period may span
        two calendar months); ``active_day_split`` is the calendar-month case.
        """
        ts_start, ts_end = cls._termset_active_range(terms)
        days_in_range = (end - start).days + 1
        earned = planned = 0
        for offset in range(days_in_range):
            d = start + timedelta(days=offset)
            if d < ts_start or (ts_end and d > ts_end):
                continue
            if d <= today:
                earned += 1
            else:
                planned += 1
        return earned, planned, days_in_range

    @classmethod
    def active_day_split(
        cls, terms: ContractTermSet, year: int, month: int, today: date,
    ) -> tuple[int, int, int]:
        """Calendar-month form of ``active_day_split_range``. Returns
        (earned_days, planned_days, days_in_month)."""
        last_day = calendar.monthrange(year, month)[1]
        return cls.active_day_split_range(
            terms, date(year, month, 1), date(year, month, last_day), today,
        )

    @classmethod
    def covered_salary_range(
        cls, terms: ContractTermSet, start: date, end: date,
    ) -> Decimal:
        """Monthly salary prorated to the days of [start, end] this term set is
        the active pay rate (Månedsløn × lønnede dage / dage i perioden). A term
        set active for the whole range earns the full salary, so an offset
        payroll period pays one month's salary like a calendar month does."""
        earned, planned, days_in_range = cls.active_day_split_range(terms, start, end, end)
        covered = earned + planned
        salary = terms.monthly_salary or Decimal("0")
        return (salary * covered / days_in_range).quantize(TWO_PLACES, ROUND_HALF_UP)

    @classmethod
    def covered_salary(cls, terms: ContractTermSet, year: int, month: int) -> Decimal:
        """Monthly salary prorated to the calendar days this term set is the
        active pay rate in the month (Månedsløn × lønnede dage / dage i måneden)."""
        last_day = calendar.monthrange(year, month)[1]
        return cls.covered_salary_range(
            terms, date(year, month, 1), date(year, month, last_day),
        )

    @classmethod
    def estimate_for_month(
        cls,
        terms: ContractTermSet,
        year: int,
        month: int,
        *,
        hours: Decimal = Decimal("0"),
        as_of: date | None = None,
    ) -> SalaryEstimate:
        """The single entry point for a term set's estimate over a calendar
        month. Salaried pay is prorated to the days the term set is the active
        rate in the month (a mid-month start or end earns only part of the
        salary) via ``covered_salary``; hourly pay uses the supplied *hours*.

        For a month that may hold several salaried term sets (a mid-month raise),
        use ``salaried_month_estimate`` instead. Use this instead of calling
        ``estimate`` directly from month views so proration stays consistent
        across the dashboard, workplace page and analytics."""
        if terms.employment_type == ContractTermSet.EmploymentType.SALARIED:
            covered = cls.covered_salary(terms, year, month)
            return cls.estimate(
                terms, hours, as_of=as_of, monthly_salary_override=covered,
            )
        return cls.estimate(terms, hours, as_of=as_of)

    @classmethod
    def salaried_period_lines(
        cls, contract, start: date, end: date, today: date,
    ) -> list["SalariedMonthLine"]:
        """For every salaried term set of *contract* that is the active rate on
        at least one day of [start, end], its day split by *today* and its salary
        prorated to those active days. This is the shared basis for salaried pay
        over a span — a span may hold several term sets (e.g. a mid-month raise),
        each prorated by the days it is the active rate.

        The range form is what an offset payroll period needs;
        ``salaried_month_lines`` is the calendar-month case."""
        lines: list[SalariedMonthLine] = []
        term_sets = contract.term_sets.filter(
            effective_from__lte=end,
            employment_type=ContractTermSet.EmploymentType.SALARIED,
        )
        for ts in term_sets:
            earned, planned, days_in_range = cls.active_day_split_range(ts, start, end, today)
            covered_days = earned + planned
            if covered_days == 0:
                continue
            covered_salary = (
                (ts.monthly_salary or Decimal("0")) * covered_days / days_in_range
            ).quantize(TWO_PLACES, ROUND_HALF_UP)
            lines.append(SalariedMonthLine(
                termset=ts, earned_days=earned, planned_days=planned,
                covered_days=covered_days, covered_salary=covered_salary,
            ))
        return lines

    @classmethod
    def salaried_month_lines(
        cls, contract, year: int, month: int, today: date,
    ) -> list["SalariedMonthLine"]:
        """Calendar-month form of ``salaried_period_lines``."""
        return cls.salaried_period_lines(contract, *month_bounds(year, month), today)

    @staticmethod
    def _combine_estimates(ests: list[SalaryEstimate]) -> SalaryEstimate:
        """Sum several per-term-set estimates into one month estimate. Additive
        money fields are summed; rate/config fields come from the last (latest)
        term set, which is the representative rate for the month."""
        if len(ests) == 1:
            return ests[0]
        rep = ests[-1]

        def s(attr: str) -> Decimal:
            return sum((getattr(e, attr) for e in ests), Decimal("0"))

        tax_breakdown = None
        if all(e.tax_breakdown for e in ests):
            first = ests[0].tax_breakdown

            def stb(attr: str) -> Decimal:
                return sum((getattr(e.tax_breakdown, attr) for e in ests), Decimal("0"))

            tax_breakdown = TaxBreakdown(
                gross=stb("gross"), employee_atp=stb("employee_atp"),
                employee_pension=stb("employee_pension"), am_basis=stb("am_basis"),
                am_bidrag=stb("am_bidrag"), income_after_am=stb("income_after_am"),
                monthly_deduction=stb("monthly_deduction"), taxable_income=stb("taxable_income"),
                tax_percent=first.tax_percent, church_tax_percent=first.church_tax_percent,
                a_skat=stb("a_skat"), net_pay=stb("net_pay"),
            )

        return SalaryEstimate(
            workplace_name=rep.workplace_name,
            employment_type=rep.employment_type,
            total_hours=s("total_hours"),
            hourly_rate=rep.hourly_rate,
            effective_hourly_rate=rep.effective_hourly_rate,
            total_hourly_rate=rep.total_hourly_rate,
            monthly_salary=rep.monthly_salary,
            gross_pay=s("gross_pay"),
            fritvalgskonto=s("fritvalgskonto"),
            taxable_gross=s("taxable_gross"),
            pension_basis=s("pension_basis"),
            employee_pension=s("employee_pension"),
            employer_pension=s("employer_pension"),
            total_pension=s("total_pension"),
            employee_atp=s("employee_atp"),
            employer_atp=s("employer_atp"),
            tax_breakdown=tax_breakdown,
        )

    @classmethod
    def salaried_month_estimate(
        cls, contract, year: int, month: int, as_of: date | None = None,
    ) -> SalaryEstimate | None:
        """Combined estimate for a salaried calendar month: every salaried term
        set active in the month, each prorated to its active days, summed field
        by field. Handles a mid-month raise and a partial-month start/end. Month
        end is the reference, so all active days count. Returns None when no
        salaried term set is active in the month."""
        month_end = month_bounds(year, month)[1]
        lines = cls.salaried_month_lines(contract, year, month, month_end)
        if not lines:
            return None
        ests = [
            cls.estimate(
                line.termset, Decimal("0"), as_of=as_of,
                monthly_salary_override=line.covered_salary,
            )
            for line in lines
        ]
        return cls._combine_estimates(ests)

    @classmethod
    def salaried_month_totals(
        cls, contract, year: int, month: int, as_of: date | None = None,
    ) -> tuple[Decimal, Decimal]:
        """(taxable_gross, net) for a salaried calendar month — see
        salaried_month_estimate. Returns (0, 0) if no term set is active."""
        est = cls.salaried_month_estimate(contract, year, month, as_of=as_of)
        if est is None:
            return Decimal("0"), Decimal("0")
        net = est.tax_breakdown.net_pay if est.tax_breakdown else est.taxable_gross
        return est.taxable_gross, net


# ---------------------------------------------------------------------------
# Flex Time Service
# ---------------------------------------------------------------------------

@dataclass
class FlexTimeResult:
    workplace_name: str
    period_start: date
    period_end: date
    expected_hours: Decimal
    actual_hours: Decimal
    flex_this_period: Decimal
    flex_carried_over: Decimal
    flex_total: Decimal


class FlexTimeService:
    """Calculate flex time for salaried employees."""

    @staticmethod
    def count_weekdays(start_date: date, end_date: date) -> int:
        count = 0
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                count += 1
            current += timedelta(days=1)
        return count

    @classmethod
    def calculate(
        cls,
        workplace: Workplace,
        period_start: date,
        period_end: date,
        carried_over: Decimal = Decimal("0"),
    ) -> FlexTimeResult:
        mid = period_start + (period_end - period_start) / 2
        terms = workplace.active_termset_on(mid)
        if terms is None or terms.employment_type != ContractTermSet.EmploymentType.SALARIED:
            raise ValueError("Flex time only applies to salaried employment.")

        weekdays = cls.count_weekdays(period_start, period_end)
        weekly_hours = terms.expected_weekly_hours or Decimal("37")
        daily_hours = weekly_hours / Decimal("5")
        expected = (daily_hours * weekdays).quantize(TWO_PLACES, ROUND_HALF_UP)

        sessions = Shift.objects.filter(
            workplace=workplace,
            date__gte=period_start,
            date__lte=period_end,
        )
        actual = sum((s.net_hours for s in sessions), Decimal("0")).quantize(TWO_PLACES, ROUND_HALF_UP)

        flex_this = actual - expected
        flex_total = carried_over + flex_this

        return FlexTimeResult(
            workplace_name=workplace.name,
            period_start=period_start,
            period_end=period_end,
            expected_hours=expected,
            actual_hours=actual,
            flex_this_period=flex_this,
            flex_carried_over=carried_over,
            flex_total=flex_total,
        )


# ---------------------------------------------------------------------------
# Payslip Service
# ---------------------------------------------------------------------------

@dataclass
class PayslipLineData:
    name: str
    quantity: Decimal | None
    rate: Decimal | None
    amount: Decimal
    line_type: str
    running_subtotal: Decimal
    standard_line_key: str | None = None
    is_editable: bool = True
    line_id: int | None = None


@dataclass
class PayslipResult:
    period_start: date
    period_end: date
    workplace_name: str
    lines: list[PayslipLineData] = field(default_factory=list)
    gross_salary: Decimal = Decimal("0")
    pre_tax_total: Decimal = Decimal("0")
    taxable_gross: Decimal = Decimal("0")
    tax_breakdown: TaxBreakdown | None = None
    post_tax_total: Decimal = Decimal("0")
    net_pay: Decimal = Decimal("0")


class PayslipService:
    """Build a complete payslip with standard lines and running subtotals."""

    STANDARD_LINE_ORDER = [
        "gross_pay", "fritvalgskonto", "ferietillaeg",
        "pension_employee", "atp_employee", "am_bidrag",
        "fradrag_used", "a_skat", "total_tax", "subtotal", "net_pay",
    ]

    @classmethod
    @transaction.atomic
    def populate_standard_lines(cls, period) -> None:
        from .models import PayslipLine

        workplace = period.workplace
        terms = _get_termset_for_period(period)

        sessions = Shift.objects.filter(
            workplace=workplace,
            date__gte=period.start_date,
            date__lte=period.end_date,
        )
        total_hours = sum((s.net_hours for s in sessions), Decimal("0"))

        if terms is None:
            return  # No active contract — nothing to compute

        tax_pull_date = PayrollPeriodService.get_tax_pull_date(
            terms, period.end_date.year, period.end_date.month
        )
        estimate = SalaryEstimateService.estimate(terms, total_hours, as_of=tax_pull_date)

        gross = estimate.gross_pay
        pension_emp = estimate.employee_pension
        atp_emp = estimate.employee_atp

        # -- Fritvalgskonto ---------------------------------------------------
        fritvalg = Decimal("0")
        if (
            getattr(terms, "fritvalgskonto_enabled", False)
            and terms.fritvalgskonto_percent
            and terms.fritvalgskonto_percent > 0
        ):
            fritvalg = (
                gross * terms.fritvalgskonto_percent / Decimal("100")
            ).quantize(TWO_PLACES)

        # -- Ferietillaeg -----------------------------------------------------
        if terms.employment_type == ContractTermSet.EmploymentType.SALARIED:
            yearly_gross_est = (terms.monthly_salary or Decimal("0")) * 12
        else:
            weekly_hours = terms.expected_weekly_hours or Decimal("37")
            yearly_gross_est = weekly_hours * 52 * (terms.hourly_rate or Decimal("0"))

        payout_months = getattr(terms, "ferietillaeg_payout_month_list", []) or []
        num_payout_months = len(payout_months) or 1
        period_month = period.end_date.month

        ferietillaeg = Decimal("0")
        ferietillaeg_name = "Ferietillaeg"
        if (
            getattr(terms, "ferietillaeg_enabled", False)
            and terms.ferietillaeg_percent
            and terms.ferietillaeg_percent > 0
            and period_month in payout_months
        ):
            yearly_ft = (
                yearly_gross_est * terms.ferietillaeg_percent / Decimal("100")
            ).quantize(TWO_PLACES)
            ferietillaeg = (yearly_ft / num_payout_months).quantize(TWO_PLACES)
            import calendar as _cal
            month_names = [_cal.month_abbr[m] for m in payout_months if 1 <= m <= 12]
            ferietillaeg_name = f"Ferietillaeg (paid out in {' & '.join(month_names)})"

        # -- Custom line classification ----------------------------------------
        existing_lines = list(
            PayslipLine.objects.filter(payroll_period=period).order_by("sort_order")
        )
        existing_std = {l.standard_line_key: l for l in existing_lines if l.standard_line_key}
        custom_lines = [l for l in existing_lines if not l.standard_line_key]

        std_sort_positions = {
            l.standard_line_key: l.sort_order
            for l in existing_lines if l.standard_line_key
        }
        custom_positions = {}
        for cl in custom_lines:
            after_key = None
            best_sort = -1
            for sk, so in std_sort_positions.items():
                if so < cl.sort_order and so > best_sort:
                    best_sort = so
                    after_key = sk
            custom_positions[cl.pk] = after_key

        PRE_TAX_POSITIONS = {
            None, "gross_pay", "fritvalgskonto", "ferietillaeg",
            "pension_employee", "atp_employee",
        }
        for cl in custom_lines:
            is_addition = cl.line_type in (
                PayslipLine.LineType.PRE_TAX_ADD,
                PayslipLine.LineType.POST_TAX_ADD,
            )
            is_pre_tax = custom_positions[cl.pk] in PRE_TAX_POSITIONS
            if is_pre_tax:
                want = PayslipLine.LineType.PRE_TAX_ADD if is_addition else PayslipLine.LineType.PRE_TAX_DEDUCT
            else:
                want = PayslipLine.LineType.POST_TAX_ADD if is_addition else PayslipLine.LineType.POST_TAX_DEDUCT
            if cl.line_type != want:
                cl.line_type = want
                cl.save(update_fields=["line_type"])

        custom_pre_add = sum(
            (cl.amount or Decimal("0")) for cl in custom_lines
            if cl.line_type == PayslipLine.LineType.PRE_TAX_ADD
        )
        custom_pre_deduct = sum(
            (cl.amount or Decimal("0")) for cl in custom_lines
            if cl.line_type == PayslipLine.LineType.PRE_TAX_DEDUCT
        )
        custom_post_add = sum(
            (cl.amount or Decimal("0")) for cl in custom_lines
            if cl.line_type == PayslipLine.LineType.POST_TAX_ADD
        )
        custom_post_deduct = sum(
            (cl.amount or Decimal("0")) for cl in custom_lines
            if cl.line_type == PayslipLine.LineType.POST_TAX_DEDUCT
        )

        adjusted_gross = gross + fritvalg + ferietillaeg + custom_pre_add - custom_pre_deduct

        tb = TaxCalculationService.calculate(
            adjusted_gross,
            as_of=tax_pull_date,
            tax_card_type=terms.tax_card_type,
            employee_pension=pension_emp,
            employee_atp=atp_emp,
        )

        am_bidrag = tb.am_bidrag if tb else Decimal("0")
        fradrag = tb.monthly_deduction if tb else Decimal("0")
        a_skat = tb.a_skat if tb else Decimal("0")
        net_pay = (tb.net_pay if tb else adjusted_gross) + custom_post_add - custom_post_deduct

        total_tax = (am_bidrag + a_skat).quantize(TWO_PLACES)
        subtotal = (adjusted_gross - pension_emp - atp_emp - am_bidrag - a_skat).quantize(TWO_PLACES)

        # -- Basis/rate for standard lines ------------------------------------
        if terms.employment_type == ContractTermSet.EmploymentType.HOURLY:
            gross_qty = total_hours
            gross_rate = terms.hourly_rate
        else:
            gross_qty = total_hours
            weekly = terms.expected_weekly_hours or Decimal("37")
            monthly_norm = weekly_to_monthly_hours(weekly).quantize(TWO_PLACES)
            gross_rate = ((terms.monthly_salary or Decimal("0")) / monthly_norm).quantize(TWO_PLACES) if monthly_norm else None

        if terms.employment_type == ContractTermSet.EmploymentType.SALARIED:
            weekly_h = terms.expected_weekly_hours or Decimal("37")
            atp_hours = weekly_to_monthly_hours(weekly_h).quantize(TWO_PLACES)
        else:
            atp_hours = total_hours

        am_pct = tb.am_bidrag / tb.am_basis * Decimal("100") if tb and tb.am_basis else Decimal("8")
        combined_tax_pct = (tb.tax_percent + tb.church_tax_percent) if tb else Decimal("0")
        taxable_income = tb.taxable_income if tb else Decimal("0")
        am_basis = tb.am_basis if tb else gross

        std_values = {
            "gross_pay": {"name": "Gross pay", "quantity": gross_qty, "rate": gross_rate, "amount": gross, "line_type": "pre_tax_add"},
            "fritvalgskonto": {"name": "Fritvalgskonto", "quantity": gross, "rate": terms.fritvalgskonto_percent if fritvalg else None, "amount": fritvalg, "line_type": "pre_tax_add"},
            "ferietillaeg": {"name": ferietillaeg_name, "quantity": yearly_gross_est.quantize(TWO_PLACES) if ferietillaeg else None, "rate": terms.ferietillaeg_percent if ferietillaeg else None, "amount": ferietillaeg, "line_type": "pre_tax_add"},
            "pension_employee": {"name": "Own pension contribution", "quantity": estimate.pension_basis, "rate": terms.pension_employee_percent, "amount": pension_emp, "line_type": "pre_tax_deduct"},
            "atp_employee": {"name": "ATP (employee)", "quantity": atp_hours, "rate": None, "amount": atp_emp, "line_type": "pre_tax_deduct"},
            "am_bidrag": {"name": "AM-bidrag", "quantity": am_basis.quantize(TWO_PLACES), "rate": am_pct.quantize(TWO_PLACES), "amount": am_bidrag, "line_type": "pre_tax_deduct"},
            "fradrag_used": {"name": "Benyttet fradrag", "quantity": None, "rate": None, "amount": fradrag, "line_type": "info"},
            "a_skat": {"name": "A-skat", "quantity": taxable_income.quantize(TWO_PLACES), "rate": combined_tax_pct.quantize(TWO_PLACES), "amount": a_skat, "line_type": "pre_tax_deduct"},
            "total_tax": {"name": "Total taxation", "quantity": None, "rate": None, "amount": total_tax, "line_type": "info"},
            "subtotal": {"name": "Subtotal", "quantity": None, "rate": None, "amount": subtotal, "line_type": "info"},
            "net_pay": {"name": "Net pay", "quantity": None, "rate": None, "amount": net_pay, "line_type": "info"},
        }

        active_std_keys = []
        for key in cls.STANDARD_LINE_ORDER:
            vals = std_values[key]
            if key == "fritvalgskonto" and fritvalg == 0:
                if key in existing_std:
                    existing_std[key].delete()
                continue
            if key == "ferietillaeg" and ferietillaeg == 0:
                if key in existing_std:
                    existing_std[key].delete()
                continue
            active_std_keys.append(key)

            if key in existing_std:
                line = existing_std[key]
                line.name = vals["name"]
                line.quantity = vals["quantity"]
                line.rate = vals["rate"]
                line.amount = vals["amount"]
                line.line_type = vals["line_type"]
                line.is_editable = False
                line.save(update_fields=["name", "quantity", "rate", "amount", "line_type", "is_editable"])
            else:
                PayslipLine.objects.create(
                    payroll_period=period,
                    name=vals["name"],
                    quantity=vals["quantity"],
                    rate=vals["rate"],
                    amount=vals["amount"],
                    line_type=vals["line_type"],
                    standard_line_key=key,
                    is_editable=False,
                    sort_order=0,
                )

        from collections import defaultdict as _dd
        customs_after = _dd(list)
        for cl in custom_lines:
            customs_after[custom_positions[cl.pk]].append(cl)

        sort_idx = 0
        for cl in customs_after.get(None, []):
            cl.sort_order = sort_idx
            cl.save(update_fields=["sort_order"])
            sort_idx += 1

        for key in active_std_keys:
            if key in existing_std:
                existing_std[key].sort_order = sort_idx
                existing_std[key].save(update_fields=["sort_order"])
            else:
                PayslipLine.objects.filter(
                    payroll_period=period, standard_line_key=key
                ).update(sort_order=sort_idx)
            sort_idx += 1
            for cl in customs_after.get(key, []):
                cl.sort_order = sort_idx
                cl.save(update_fields=["sort_order"])
                sort_idx += 1

    @staticmethod
    def build_payslip(period) -> PayslipResult:
        from .models import PayslipLine

        lines_qs = PayslipLine.objects.filter(payroll_period=period).order_by("sort_order")
        result = PayslipResult(
            period_start=period.start_date,
            period_end=period.end_date,
            workplace_name=period.workplace.name,
        )

        running = Decimal("0")
        pre_tax_adjustments = Decimal("0")
        post_tax_adjustments = Decimal("0")

        line_data_list = []
        for line in lines_qs:
            amount = line.amount or Decimal("0")
            if line.line_type == PayslipLine.LineType.PRE_TAX_ADD:
                running += amount
                pre_tax_adjustments += amount
            elif line.line_type == PayslipLine.LineType.PRE_TAX_DEDUCT:
                running -= amount
                pre_tax_adjustments -= amount
            elif line.line_type == PayslipLine.LineType.POST_TAX_ADD:
                running += amount
                post_tax_adjustments += amount
            elif line.line_type == PayslipLine.LineType.POST_TAX_DEDUCT:
                running -= amount
                post_tax_adjustments -= amount

            line_data_list.append(
                PayslipLineData(
                    name=line.name,
                    quantity=line.quantity,
                    rate=line.rate,
                    amount=amount,
                    line_type=line.line_type,
                    running_subtotal=running.quantize(TWO_PLACES),
                    standard_line_key=line.standard_line_key,
                    is_editable=line.is_editable,
                    line_id=line.pk,
                )
            )

        result.lines = line_data_list
        result.gross_salary = running.quantize(TWO_PLACES)
        result.pre_tax_total = pre_tax_adjustments.quantize(TWO_PLACES)

        terms = _get_termset_for_period(period)
        if terms is not None:
            tax_pull_date = PayrollPeriodService.get_tax_pull_date(
                terms, period.end_date.year, period.end_date.month
            )
            tax_card_type = terms.tax_card_type
        else:
            tax_pull_date = date(period.end_date.year, period.end_date.month, 18)
            tax_card_type = "hovedkort"

        result.tax_breakdown = TaxCalculationService.calculate(
            max(running, Decimal("0")),
            as_of=tax_pull_date,
            tax_card_type=tax_card_type,
        )

        if result.tax_breakdown:
            after_tax = result.tax_breakdown.net_pay
        else:
            after_tax = running

        result.post_tax_total = post_tax_adjustments.quantize(TWO_PLACES)
        result.net_pay = (after_tax + post_tax_adjustments).quantize(TWO_PLACES)

        return result


# ---------------------------------------------------------------------------
# Vacation Service
# ---------------------------------------------------------------------------

class VacationService:
    """Manage vacation accrual and balance."""

    @staticmethod
    def update_balance(workplace: Workplace, year: int, month: int):
        from .models import VacationBalance

        terms = workplace.active_termset_in_month(year, month)
        if terms is None or terms.vacation_type != ContractTermSet.VacationType.ACCRUED:
            return None

        daily_hours = terms.expected_weekly_hours / Decimal("5") if terms.expected_weekly_hours else Decimal("7.4")
        monthly_accrual_hours = (VACATION_DAYS_PER_MONTH * daily_hours).quantize(TWO_PLACES)

        vacation_sessions = Shift.objects.filter(
            workplace=workplace,
            date__year=year,
            date__month=month,
            shift_type=Shift.ShiftType.VACATION,
        )
        used_hours = sum(
            (s.net_hours for s in vacation_sessions), Decimal("0")
        ).quantize(TWO_PLACES)

        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1

        prev_balance = VacationBalance.objects.filter(
            workplace=workplace, year=prev_year, month=prev_month
        ).first()
        carried = prev_balance.balance if prev_balance else Decimal("0")

        balance, _ = VacationBalance.objects.update_or_create(
            workplace=workplace,
            year=year,
            month=month,
            defaults={
                "accrued_hours": monthly_accrual_hours,
                "used_hours": used_hours,
                "carried_over_hours": carried.quantize(TWO_PLACES),
            },
        )
        return balance


# ---------------------------------------------------------------------------
# Commuting Service
# ---------------------------------------------------------------------------

class CommutingService:
    """Auto-count commuting days from on-site sessions."""

    @staticmethod
    def update_commuting(workplace: Workplace, year: int, month: int):
        from .models import CommutingRecord

        on_site_dates = (
            Shift.objects.filter(
                workplace=workplace,
                date__year=year,
                date__month=month,
                shift_type=Shift.ShiftType.ON_SITE,
            )
            .values_list("date", flat=True)
            .distinct()
        )
        count = len(set(on_site_dates))

        record, _ = CommutingRecord.objects.update_or_create(
            workplace=workplace,
            year=year,
            month=month,
            defaults={"commuting_days": count},
        )
        return record
