"""
Payroll services — period generation, salary estimates, flex time,
payslip building, vacation tracking, commuting.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from workplaces.models import Workplace
from worksessions.models import WorkSession
from core.services import TaxCalculationService, TaxBreakdown, ATPService

TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# Payroll Period Service
# ---------------------------------------------------------------------------

class PayrollPeriodService:
    """Generate and query payroll periods based on workplace config."""

    @staticmethod
    def get_period_dates(workplace: Workplace, year: int, month: int) -> tuple[date, date]:
        """
        Return (start_date, end_date) for the payroll period that corresponds
        to a given month.

        If payroll_period_start_day == 1, the period is simply the 1st to the
        last day of the month.

        If payroll_period_start_day == 20, the period for month M is:
          start = previous_month/20  →  end = current_month/19
        """
        start_day = workplace.payroll_period_start_day
        if start_day == 1:
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, 1), date(year, month, last_day)

        # Start is in the previous month
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1

        prev_last = calendar.monthrange(prev_year, prev_month)[1]
        actual_start_day = min(start_day, prev_last)
        start_date = date(prev_year, prev_month, actual_start_day)

        # End is start_day - 1 of the current month
        cur_last = calendar.monthrange(year, month)[1]
        end_day = min(start_day - 1, cur_last)
        end_date = date(year, month, end_day)

        return start_date, end_date

    @classmethod
    def get_or_create_period(cls, workplace: Workplace, year: int, month: int):
        """Get or create the PayrollPeriod object for a workplace and month."""
        from .models import PayrollPeriod

        start_date, end_date = cls.get_period_dates(workplace, year, month)
        period, created = PayrollPeriod.objects.get_or_create(
            workplace=workplace,
            start_date=start_date,
            defaults={"end_date": end_date},
        )
        if created:
            cls._populate_template_lines(period)
        return period, created

    @staticmethod
    def _populate_template_lines(period):
        """Copy PayslipLineTemplate entries into actual PayslipLines."""
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
    employee_pension: Decimal
    employer_pension: Decimal
    total_pension: Decimal
    employee_atp: Decimal
    employer_atp: Decimal
    tax_breakdown: TaxBreakdown | None


class SalaryEstimateService:
    """Calculate gross pay for a payroll period."""

    @staticmethod
    def estimate(
        workplace: Workplace,
        total_hours: Decimal,
        as_of: date | None = None,
    ) -> SalaryEstimate:
        if workplace.employment_type == Workplace.EmploymentType.HOURLY:
            effective_rate = workplace.effective_hourly_rate or workplace.hourly_rate
            gross = (total_hours * effective_rate).quantize(
                TWO_PLACES, ROUND_HALF_UP
            )
        else:
            gross = workplace.monthly_salary

        # Employee pension (deducted before tax)
        employee_pension = (
            gross * workplace.pension_employee_percent / Decimal("100")
        ).quantize(TWO_PLACES, ROUND_HALF_UP)

        # Employer pension
        employer_pension = (
            gross * workplace.pension_employer_percent / Decimal("100")
        ).quantize(TWO_PLACES, ROUND_HALF_UP)

        # ATP contributions based on monthly hours
        employee_atp, employer_atp = ATPService.get_contributions(
            total_hours, as_of=as_of
        )

        tax_breakdown = TaxCalculationService.calculate(
            gross,
            as_of=as_of,
            tax_card_type=workplace.tax_card_type,
            employee_pension=employee_pension,
            employee_atp=employee_atp,
        )

        return SalaryEstimate(
            workplace_name=workplace.name,
            employment_type=workplace.employment_type,
            total_hours=total_hours,
            hourly_rate=workplace.hourly_rate,
            effective_hourly_rate=workplace.effective_hourly_rate,
            total_hourly_rate=workplace.total_hourly_rate,
            monthly_salary=workplace.monthly_salary,
            gross_pay=gross,
            employee_pension=employee_pension,
            employer_pension=employer_pension,
            total_pension=employee_pension + employer_pension,
            employee_atp=employee_atp,
            employer_atp=employer_atp,
            tax_breakdown=tax_breakdown,
        )


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
    """
    Calculate flex time for salaried employees.
    Flex = actual hours − expected hours, carried between periods.
    """

    @staticmethod
    def count_weekdays(start_date: date, end_date: date) -> int:
        """Count weekdays (Mon–Fri) in the date range inclusive."""
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
        """Calculate flex time for a salaried workplace in a period."""
        if workplace.employment_type != Workplace.EmploymentType.SALARIED:
            raise ValueError("Flex time only applies to salaried employment.")

        weekdays = cls.count_weekdays(period_start, period_end)
        weekly_hours = workplace.expected_weekly_hours or Decimal("37")
        daily_hours = weekly_hours / Decimal("5")
        expected = (daily_hours * weekdays).quantize(TWO_PLACES, ROUND_HALF_UP)

        # Sum actual session hours in the period
        sessions = WorkSession.objects.filter(
            workplace=workplace,
            date__gte=period_start,
            date__lte=period_end,
        )
        actual = sum(
            (s.net_hours for s in sessions), Decimal("0")
        ).quantize(TWO_PLACES, ROUND_HALF_UP)

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
        "gross_pay",
        "ferietillaeg",
        "pension_employee",
        "atp_employee",
        "am_bidrag",
        "fradrag_used",
        "a_skat",
        "total_tax",
        "subtotal",
        "net_pay",
    ]

    @classmethod
    def populate_standard_lines(cls, period) -> None:
        """
        Create (or update) the standard payslip lines for a period,
        calculated from the workplace config and work sessions.
        Custom lines are preserved and interleaved.
        """
        from .models import PayslipLine

        workplace = period.workplace
        sessions = WorkSession.objects.filter(
            workplace=workplace,
            date__gte=period.start_date,
            date__lte=period.end_date,
        )
        total_hours = sum((s.net_hours for s in sessions), Decimal("0"))

        # Calculate salary estimate
        estimate = SalaryEstimateService.estimate(
            workplace, total_hours, as_of=period.start_date
        )
        tb = estimate.tax_breakdown

        # Determine amounts for each standard line
        gross = estimate.gross_pay
        pension_emp = estimate.employee_pension
        atp_emp = estimate.employee_atp

        am_bidrag = tb.am_bidrag if tb else Decimal("0")
        fradrag = tb.monthly_deduction if tb else Decimal("0")
        a_skat = tb.a_skat if tb else Decimal("0")
        net_pay = tb.net_pay if tb else gross

        total_tax = (am_bidrag + a_skat).quantize(TWO_PLACES)
        subtotal = (gross - pension_emp - atp_emp - am_bidrag - a_skat).quantize(TWO_PLACES)

        # Ferietillæg: % of yearly gross / 12 (for monthly payslips)
        ferietillaeg = Decimal("0")
        if getattr(workplace, 'ferietillaeg_enabled', False) and workplace.ferietillaeg_percent and workplace.ferietillaeg_percent > 0:
            ferietillaeg = (gross * Decimal("12") * workplace.ferietillaeg_percent / Decimal("100") / Decimal("12")).quantize(TWO_PLACES)

        std_values = {
            "gross_pay": {"name": "Gross pay", "amount": gross, "line_type": "pre_tax_add"},
            "ferietillaeg": {"name": "Ferietillæg", "amount": ferietillaeg, "line_type": "info"},
            "pension_employee": {"name": "Own pension contribution", "amount": pension_emp, "line_type": "pre_tax_deduct"},
            "atp_employee": {"name": "ATP (employee)", "amount": atp_emp, "line_type": "pre_tax_deduct"},
            "am_bidrag": {"name": "AM-bidrag (8%)", "amount": am_bidrag, "line_type": "pre_tax_deduct"},
            "fradrag_used": {"name": "Benyttet fradrag", "amount": fradrag, "line_type": "info"},
            "a_skat": {"name": "A-skat", "amount": a_skat, "line_type": "pre_tax_deduct"},
            "total_tax": {"name": "Total taxation", "amount": total_tax, "line_type": "info"},
            "subtotal": {"name": "Subtotal", "amount": subtotal, "line_type": "info"},
            "net_pay": {"name": "Net pay", "amount": net_pay, "line_type": "info"},
        }

        # Get existing lines to preserve custom lines
        existing_lines = list(
            PayslipLine.objects.filter(payroll_period=period).order_by("sort_order")
        )
        existing_std = {l.standard_line_key: l for l in existing_lines if l.standard_line_key}
        custom_lines = [l for l in existing_lines if not l.standard_line_key]

        # Build standard lines: update existing or create new
        sort_idx = 0
        for key in cls.STANDARD_LINE_ORDER:
            vals = std_values[key]
            # Skip ferietillæg if zero
            if key == "ferietillaeg" and ferietillaeg == 0:
                # If it existed before, delete it
                if key in existing_std:
                    existing_std[key].delete()
                continue

            if key in existing_std:
                line = existing_std[key]
                line.name = vals["name"]
                line.amount = vals["amount"]
                line.line_type = vals["line_type"]
                line.is_editable = False
                line.sort_order = sort_idx
                line.save()
            else:
                PayslipLine.objects.create(
                    payroll_period=period,
                    name=vals["name"],
                    amount=vals["amount"],
                    line_type=vals["line_type"],
                    standard_line_key=key,
                    is_editable=False,
                    sort_order=sort_idx,
                )
            sort_idx += 1

        # Re-sort custom lines after standard lines (preserving their relative order)
        for custom_line in custom_lines:
            custom_line.sort_order = sort_idx
            custom_line.save(update_fields=["sort_order"])
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
                post_tax_adjustments += amount
            elif line.line_type == PayslipLine.LineType.POST_TAX_DEDUCT:
                post_tax_adjustments -= amount
            # INFORMATIONAL lines don't affect running total

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

        # Calculate tax on the pre-tax total (gross salary)
        result.tax_breakdown = TaxCalculationService.calculate(
            max(running, Decimal("0")),
            as_of=period.start_date,
            tax_card_type=period.workplace.tax_card_type,
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
    """Manage vacation accrual and balance for workplaces with accrued vacation."""

    @staticmethod
    def update_balance(workplace: Workplace, year: int, month: int):
        """
        Recalculate vacation balance for a workplace/month.
        Accrual: vacation_days_per_year / 12 per month (converted to hours).
        Usage: sum of vacation session hours in that month.
        Carried over: previous month's balance.
        """
        from .models import VacationBalance

        if workplace.vacation_type != Workplace.VacationType.ACCRUED:
            return None

        daily_hours = workplace.expected_weekly_hours / Decimal("5") if workplace.expected_weekly_hours else Decimal("7.4")
        monthly_accrual_days = Decimal("2.08")  # Fixed Danish vacation accrual
        monthly_accrual_hours = (monthly_accrual_days * daily_hours).quantize(TWO_PLACES)

        # Vacation sessions in this month
        vacation_sessions = WorkSession.objects.filter(
            workplace=workplace,
            date__year=year,
            date__month=month,
            session_type=WorkSession.SessionType.VACATION,
        )
        used_hours = sum(
            (s.net_hours for s in vacation_sessions), Decimal("0")
        ).quantize(TWO_PLACES)

        # Carry over from previous month
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
        """Count unique on-site dates and update CommutingRecord."""
        from .models import CommutingRecord

        on_site_dates = (
            WorkSession.objects.filter(
                workplace=workplace,
                date__year=year,
                date__month=month,
                session_type=WorkSession.SessionType.ON_SITE,
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
