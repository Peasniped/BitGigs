"""The monthly personfradrag is deducted exactly once per payroll period.

``TaxCalculationService.calculate`` subtracts the deduction once per call, so
anything that estimated a period piece by piece — a mid-period raise (two term
sets), or the dashboard's earned/planned split — and then *added the breakdowns
up* deducted it once per piece. A-skat came out too low and net pay too high, by
``monthly_deduction × (tax_percent + church_tax_percent)`` for every extra piece.

The fix is the same everywhere: estimate the period once on the combined bases,
then allocate the parts out of that single figure.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.models import TaxProfile
from core.services import TaxCalculationService
from payroll.services import SalaryEstimateService
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract

# 8% AM-bidrag, 37% A-skat, 4000 kr/month personfradrag. One extra deduction is
# therefore worth 4000 × 37% = 1480 kr of net pay — the size of the bug.
DEDUCTION = Decimal("4000.00")
TAX_PERCENT = Decimal("37.00")
OVERSTATEMENT = Decimal("1480.00")


def _tax_profile():
    return TaxProfile.objects.create(
        monthly_deduction=DEDUCTION, tax_percent=TAX_PERCENT,
        church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
        effective_from=date(2026, 1, 1),
    )


class CombinedEstimateDeductionTests(TestCase):
    """``_combine_estimates`` recomputes tax on the summed bases rather than
    summing the per-term-set breakdowns."""

    def setUp(self):
        _tax_profile()
        self.wp = Workplace.objects.create(name="Split Corp")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)

    def _salaried(self, eff_from, eff_until, salary, **kwargs):
        return ContractTermSet.objects.create(
            contract=self.contract, effective_from=eff_from,
            effective_until=eff_until,
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal(salary), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1, **kwargs
        )

    def test_deduction_applied_once_across_two_term_sets(self):
        # A mid-month raise: two halves of June, 50000/month each → 50000 gross.
        self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000")
        self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000")

        est = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)

        self.assertEqual(est.taxable_gross, Decimal("50000.00"))
        # The bug: this summed to 8000 across the two term sets.
        self.assertEqual(est.tax_breakdown.monthly_deduction, DEDUCTION)

    def test_combined_net_matches_one_calculation_on_the_same_basis(self):
        """The whole point: two term sets must price identically to one term set
        earning the same total, because the tax owed is the same money."""
        self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000")
        self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000")

        est = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)
        expected = TaxCalculationService.calculate(
            Decimal("50000.00"),
            employee_pension=est.employee_pension,
            employee_atp=est.employee_atp,
        )

        self.assertEqual(est.tax_breakdown.net_pay, expected.net_pay)
        self.assertEqual(est.tax_breakdown.a_skat, expected.a_skat)
        self.assertEqual(est.tax_breakdown.taxable_income, expected.taxable_income)

    def test_the_old_summed_breakdown_overstated_net_by_one_deduction(self):
        """Pins the direction and the exact size, so a regression can't pass by
        landing on some other wrong number.

        Rebuilds what the old code did — estimate each term set, add the
        breakdowns up — and measures the gap. Everything else about the two
        figures is identical, so the whole difference is the second deduction.
        """
        first = self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000")
        second = self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000")

        est = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)
        halves = [
            SalaryEstimateService.estimate(
                ts, Decimal("0"), monthly_salary_override=Decimal("25000"),
            )
            for ts in (first, second)
        ]
        summed_net = sum(h.tax_breakdown.net_pay for h in halves)

        self.assertEqual(summed_net - est.tax_breakdown.net_pay, OVERSTATEMENT)
        self.assertEqual(
            sum(h.tax_breakdown.monthly_deduction for h in halves), DEDUCTION * 2,
        )

    def test_single_term_set_is_untouched(self):
        """A one-term-set month never went through the summing path, so it must
        still price exactly as a lone estimate does."""
        self._salaried(date(2026, 6, 1), date(2026, 6, 30), "50000")

        est = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)
        expected = TaxCalculationService.calculate(
            Decimal("50000.00"),
            employee_pension=est.employee_pension,
            employee_atp=est.employee_atp,
        )
        self.assertEqual(est.tax_breakdown.net_pay, expected.net_pay)
        self.assertEqual(est.tax_breakdown.monthly_deduction, DEDUCTION)

    def test_hovedkort_wins_when_the_cards_disagree(self):
        """The personfradrag follows the hovedkort, and the period did earn it —
        so one bikort term set must not swallow the whole month's deduction."""
        self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000",
                       tax_card_type="hovedkort")
        self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000",
                       tax_card_type="bikort")

        est = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)
        self.assertEqual(est.tax_breakdown.monthly_deduction, DEDUCTION)

    def test_bikort_only_gets_no_deduction(self):
        self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000",
                       tax_card_type="bikort")
        self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000",
                       tax_card_type="bikort")

        est = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)
        self.assertEqual(est.tax_breakdown.monthly_deduction, Decimal("0.00"))
