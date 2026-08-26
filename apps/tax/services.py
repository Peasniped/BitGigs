"""
Tax calculation service — Danish payroll rules for A-indkomst.

Processing order for monthly payroll:
1. Calculate gross pay.
2. Subtract employee ATP, if applicable.
3. Subtract employee pension contribution, if applicable (deducted before tax).
4. Calculate AM-bidrag = 8% of (gross − ATP − employee pension).
5. Subtract AM-bidrag.
6. Find taxable income for A-skat:
   - Hovedkort: subtract available monthly fradrag (but never below 0).
   - Bikort: do not subtract fradrag.
7. A-skat = taxable income × trækprocent.
8. Net pay = gross − ATP − employee pension − AM-bidrag − A-skat − post-tax deductions.

Important:
- AM-bidrag is processed before A-skat.
- Fradrag reduces the basis for A-skat only, NOT the basis for AM-bidrag.
- ATP employee contribution is the employee's share only.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone

from .models import TaxProfile, ATPConfiguration
# active_dated_row is platform machinery (pick the row effective on a date),
# so it stays in core — this app is only its Danish caller.
from core.utils import active_dated_row


TWO_PLACES = Decimal("0.01")


@dataclass
class TaxBreakdown:
    gross: Decimal
    employee_atp: Decimal
    employee_pension: Decimal
    am_basis: Decimal            # gross − ATP − employee pension
    am_bidrag: Decimal
    income_after_am: Decimal     # am_basis − am_bidrag
    monthly_deduction: Decimal
    taxable_income: Decimal
    tax_percent: Decimal
    church_tax_percent: Decimal
    a_skat: Decimal
    net_pay: Decimal


class ATPService:
    """Look up the active ATP configuration and compute contributions."""

    @staticmethod
    def get_active_config(as_of: date | None = None) -> ATPConfiguration | None:
        if as_of is None:
            as_of = timezone.localdate()
        return active_dated_row(ATPConfiguration.objects.all(), as_of)

    @classmethod
    def get_contributions(
        cls, monthly_hours: Decimal, as_of: date | None = None
    ) -> tuple[Decimal, Decimal]:
        """
        Return (employee_amount, employer_amount) for the given monthly hours.
        Returns (0, 0) if no ATP configuration exists or hours fall below all brackets.

        ATP tiers are defined by lower thresholds (>=39, >=78, >=117 h/month), so the
        applicable bracket is the highest one whose hours_min <= hours. hours_max is
        descriptive only and intentionally not used for matching, so fractional hours
        between tier edges can never fall into a gap.
        """
        config = cls.get_active_config(as_of)
        if config is None:
            return Decimal("0"), Decimal("0")

        match = None
        for bracket in config.brackets.all():
            if monthly_hours >= bracket.hours_min and (match is None or bracket.hours_min > match.hours_min):
                match = bracket

        if match is None:
            return Decimal("0"), Decimal("0")
        return match.employee_amount, match.employer_amount


class TaxCalculationService:
    """Calculate Danish payroll tax on a gross amount."""

    @staticmethod
    def get_active_profile(as_of: date | None = None) -> TaxProfile | None:
        """Return the tax profile effective on a given date.

        Falls back to the closest available profile if none is effective
        on the requested date (e.g. profile created after the period start).
        """
        if as_of is None:
            as_of = timezone.localdate()
        return active_dated_row(TaxProfile.objects.all(), as_of)

    @staticmethod
    def coverage_warning(as_of: date) -> str | None:
        """Return a warning if *as_of* precedes every tax profile, else None.

        Such a shift has no tax profile defined for its date; the estimate falls
        back to the earliest profile and may be inaccurate.
        """
        earliest = TaxProfile.objects.order_by("effective_from").first()
        if earliest and as_of < earliest.effective_from:
            return (
                f"This shift is dated {as_of}, before your earliest tax profile "
                f"({earliest.effective_from}). Pay estimates will use that profile "
                f"and may be inaccurate. Edit a tax profile or add one with an "
                f"earlier start date."
            )
        return None

    @classmethod
    def calculate(
        cls,
        gross: Decimal,
        profile: TaxProfile | None = None,
        as_of: date | None = None,
        tax_card_type: str = "hovedkort",
        employee_pension: Decimal = Decimal("0"),
        employee_atp: Decimal = Decimal("0"),
    ) -> TaxBreakdown:
        """
        Calculate net pay from gross using the correct Danish processing order.

        Parameters:
            gross: Total gross pay.
            profile: Tax profile to use (looked up if None).
            as_of: Date for profile lookup.
            tax_card_type: 'hovedkort' or 'bikort'.
            employee_pension: Employee pension contribution (deducted before tax).
            employee_atp: Employee ATP contribution (deducted before tax).
        """
        if profile is None:
            profile = cls.get_active_profile(as_of)

        zero = Decimal("0.00")

        if profile is None:
            return TaxBreakdown(
                gross=gross.quantize(TWO_PLACES),
                employee_atp=zero,
                employee_pension=zero,
                am_basis=gross.quantize(TWO_PLACES),
                am_bidrag=zero,
                income_after_am=gross.quantize(TWO_PLACES),
                monthly_deduction=zero,
                taxable_income=gross.quantize(TWO_PLACES),
                tax_percent=zero,
                church_tax_percent=zero,
                a_skat=zero,
                net_pay=gross.quantize(TWO_PLACES),
            )

        # Step 2+3: AM-bidrag basis = gross − ATP − employee pension
        am_basis = gross - employee_atp - employee_pension

        # Step 4: AM-bidrag
        am_rate = profile.am_bidrag_percent / Decimal("100")
        am_bidrag = (am_basis * am_rate).quantize(TWO_PLACES, ROUND_HALF_UP)

        # Step 5: Income after AM-bidrag
        income_after_am = am_basis - am_bidrag

        # Step 6: Taxable income for A-skat
        if tax_card_type == "hovedkort":
            deduction = profile.monthly_deduction
        else:
            deduction = zero

        taxable_income = max(income_after_am - deduction, zero)

        # Step 7: A-skat
        combined_tax_rate = (
            profile.tax_percent + profile.church_tax_percent
        ) / Decimal("100")
        a_skat = (taxable_income * combined_tax_rate).quantize(
            TWO_PLACES, ROUND_HALF_UP
        )

        # Step 8: Net pay = gross − ATP − employee pension − AM-bidrag − A-skat
        net_pay = gross - employee_atp - employee_pension - am_bidrag - a_skat

        return TaxBreakdown(
            gross=gross.quantize(TWO_PLACES),
            employee_atp=employee_atp.quantize(TWO_PLACES),
            employee_pension=employee_pension.quantize(TWO_PLACES),
            am_basis=am_basis.quantize(TWO_PLACES),
            am_bidrag=am_bidrag,
            income_after_am=income_after_am.quantize(TWO_PLACES),
            monthly_deduction=deduction.quantize(TWO_PLACES),
            taxable_income=taxable_income.quantize(TWO_PLACES),
            tax_percent=profile.tax_percent,
            church_tax_percent=profile.church_tax_percent,
            a_skat=a_skat,
            net_pay=net_pay.quantize(TWO_PLACES),
        )
