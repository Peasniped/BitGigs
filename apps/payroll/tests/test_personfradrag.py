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

from tax.models import TaxProfile
from tax.services import TaxCalculationService
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

    def test_a_split_month_prices_exactly_like_an_unsplit_one(self):
        """The invariant behind both fixes, and the one a user would notice: two
        term sets earning 50000 between them must cost the same tax and the same
        ATP as one term set earning 50000 over the same month. It is the same
        month and the same money — splitting it is a bookkeeping detail."""
        self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000")
        self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000")
        split = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)

        whole_contract = WorkplaceContract.objects.create(
            workplace=Workplace.objects.create(name="Whole Corp"),
        )
        ContractTermSet.objects.create(
            contract=whole_contract, effective_from=date(2026, 6, 1),
            effective_until=date(2026, 6, 30),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("50000"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        whole = SalaryEstimateService.salaried_month_estimate(whole_contract, 2026, 6)

        self.assertEqual(split.taxable_gross, whole.taxable_gross)
        self.assertEqual(split.employee_atp, whole.employee_atp)
        self.assertEqual(
            split.tax_breakdown.monthly_deduction,
            whole.tax_breakdown.monthly_deduction,
        )
        self.assertEqual(split.tax_breakdown.net_pay, whole.tax_breakdown.net_pay)

    def test_atp_is_charged_for_one_month_not_one_per_term_set(self):
        """ATP is a per-month contribution and its brackets are threshold-based,
        so the two halves' hours are summed and looked up once."""
        self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000")
        self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000")

        est = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)
        halves = [
            SalaryEstimateService.estimate(
                ts, Decimal("0"), monthly_salary_override=Decimal("25000"),
            )
            for ts in self.contract.term_sets.all()
        ]

        # One month of salaried hours (37 × 52/12), not two.
        self.assertAlmostEqual(est.atp_hours, Decimal("160.33"), places=1)
        self.assertLess(est.employee_atp, sum(h.employee_atp for h in halves))

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

    def test_card_follows_the_tax_pull_date_not_the_latest_term_set(self):
        """One payslip carries one card: the one the employer pulls from SKAT on
        tax_pull_day. Here that date (the 18th) falls inside the *first* term
        set, so its hovedkort governs the month even though the period ends on
        the second term set's bikort."""
        self._salaried(date(2026, 6, 1), date(2026, 6, 20), "50000",
                       tax_card_type="hovedkort")
        self._salaried(date(2026, 6, 21), date(2026, 6, 30), "50000",
                       tax_card_type="bikort")

        est = SalaryEstimateService.salaried_month_estimate(
            self.contract, 2026, 6, as_of=date(2026, 6, 18),
        )
        self.assertEqual(est.tax_breakdown.monthly_deduction, DEDUCTION)

    def test_card_switched_before_the_pull_date_governs_the_period(self):
        """The mirror: the switch to bikort lands on the 10th, before the 18th
        pull, so the whole period is taxed on the bikort — no deduction."""
        self._salaried(date(2026, 6, 1), date(2026, 6, 9), "50000",
                       tax_card_type="hovedkort")
        self._salaried(date(2026, 6, 10), date(2026, 6, 30), "50000",
                       tax_card_type="bikort")

        est = SalaryEstimateService.salaried_month_estimate(
            self.contract, 2026, 6, as_of=date(2026, 6, 18),
        )
        self.assertEqual(est.tax_breakdown.monthly_deduction, Decimal("0.00"))

    def test_bikort_only_gets_no_deduction(self):
        self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000",
                       tax_card_type="bikort")
        self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000",
                       tax_card_type="bikort")

        est = SalaryEstimateService.salaried_month_estimate(self.contract, 2026, 6)
        self.assertEqual(est.tax_breakdown.monthly_deduction, Decimal("0.00"))

    def test_card_falls_back_to_the_earliest_when_the_pull_predates_them_all(self):
        """A period estimated before any of its term sets start (a projection
        reaching back) has no card in force — take the earliest, as
        active_dated_row does, rather than dropping the deduction."""
        self._salaried(date(2026, 6, 1), date(2026, 6, 15), "50000",
                       tax_card_type="hovedkort")
        self._salaried(date(2026, 6, 16), date(2026, 6, 30), "50000",
                       tax_card_type="hovedkort")

        est = SalaryEstimateService.salaried_month_estimate(
            self.contract, 2026, 6, as_of=date(2026, 5, 1),
        )
        self.assertEqual(est.tax_breakdown.monthly_deduction, DEDUCTION)
