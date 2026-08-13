from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.dashboard_service import DashboardDataService
from core.models import TaxProfile
from payroll.services import SalaryEstimateService
from workplaces.models import Workplace, WorkplaceContract, ContractTermSet


class DashboardTermsetResolutionTest(TestCase):
    """A contract/termset first effective on the 1st of the month must still
    surface pay and the hour-goal, even when the payroll period starts in the
    previous month (payroll_period_start_day != 1)."""

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"),
            tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"),
            am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Mid Start Corp")
        # Contract begins on the 1st of March 2026 (derived from its term set).
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        # Payroll period starts on the 20th, so March's period_start is Feb 20 —
        # before the contract exists.
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2026, 3, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"),
            weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=20,
            hour_goal_type=ContractTermSet.HourGoalType.MONTHLY,
            hour_goal_min=Decimal("140.00"),
        )

    def test_earned_and_goal_surface_for_first_month(self):
        stats = DashboardDataService.get_stats(2026, 3)
        self.assertGreater(stats.total_earned_gross, Decimal("0"))
        self.assertTrue(stats.has_any_goal)
        self.assertEqual(stats.total_goal_min, Decimal("140.00"))

    def test_get_full_matches_stats(self):
        data = DashboardDataService.get_full(2026, 3)
        self.assertGreater(data.stats.total_earned_gross, Decimal("0"))
        self.assertTrue(data.stats.has_any_goal)
        self.assertEqual(len(data.workplace_data), 1)


class RepresentativeTermsetTest(TestCase):
    """active_termset_in_month must find the month's pay terms regardless of
    where in the month the contract/term set starts or ends (no 15th probe)."""

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2020, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Anchor Corp")

    def _add(self, start, end=None, eff=None, salary="30000"):
        c = WorkplaceContract.objects.create(workplace=self.wp)
        ts = ContractTermSet.objects.create(
            contract=c, effective_from=eff or start, effective_until=end,
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal(salary), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        return c, ts

    def test_contract_starting_after_the_15th_is_found(self):
        _, ts = self._add(date(2025, 6, 20))
        self.assertEqual(self.wp.active_termset_in_month(2025, 6), ts)

    def test_contract_ending_before_the_15th_is_found(self):
        _, ts = self._add(date(2025, 5, 1), end=date(2025, 6, 10))
        self.assertEqual(self.wp.active_termset_in_month(2025, 6), ts)

    def test_no_contract_returns_none(self):
        self.assertIsNone(self.wp.active_termset_in_month(2025, 6))

    def test_mid_month_raise_returns_latest_rate(self):
        c = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=c, effective_from=date(2025, 6, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("60000"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        newer = ContractTermSet.objects.create(
            contract=c, effective_from=date(2025, 6, 21),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("90000"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        self.assertEqual(self.wp.active_termset_in_month(2025, 6), newer)

    def test_dashboard_surfaces_pay_for_late_month_start(self):
        # A contract starting the 20th used to show nothing (15th probe); now it
        # earns 30000 × 11/30 for June (viewed fully in the past → all earned).
        self._add(date(2025, 6, 20))
        stats = DashboardDataService.get_stats(2025, 6)
        self.assertGreater(stats.total_earned_gross, Decimal("0"))


class SalaryProrationTest(TestCase):
    """A salaried salary accrues per calendar day the contract is active:
    days up to today are earned, later days planned (calendar-month denominator)."""

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"),
            tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"),
            am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Salary Corp")
        # Salaried contract starting mid-month (July has 31 days → 17 active days).
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)
        self.terms = ContractTermSet.objects.create(
            contract=self.contract,
            effective_from=date(2026, 7, 15),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"),
            weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        # taxable_gross == gross here (no fritvalgskonto), so it equals the
        # prorated covered salary: 30000 × 17 / 31.
        self.covered = (Decimal("30000") * 17 / 31).quantize(Decimal("0.01"))

    def _pay(self, today):
        return DashboardDataService._compute_pay(
            self.terms, Decimal("0"), Decimal("0"),
            2026, 7, date(2026, 7, 18), today,
        )

    def test_all_planned_before_start(self):
        pay = self._pay(date(2026, 7, 1))
        self.assertEqual(pay.earned_gross, Decimal("0"))
        self.assertEqual(pay.planned_gross, self.covered)

    def test_split_midway(self):
        pay = self._pay(date(2026, 7, 20))
        self.assertGreater(pay.earned_gross, Decimal("0"))
        self.assertGreater(pay.planned_gross, Decimal("0"))
        self.assertEqual(pay.earned_gross + pay.planned_gross, self.covered)

    def test_all_earned_after_end(self):
        pay = self._pay(date(2026, 8, 1))
        self.assertEqual(pay.planned_gross, Decimal("0"))
        self.assertEqual(pay.earned_gross, self.covered)

    def test_covered_salary_prorates_by_active_days(self):
        # User scenario: 9000/mo, contract from June 10 (30-day month, 21 active
        # days) → 9000 × 21 / 30 = 6300.
        from payroll.services import SalaryEstimateService
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        terms = ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2025, 6, 10),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("9000.00"),
            weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        self.assertEqual(
            SalaryEstimateService.covered_salary(terms, 2025, 6), Decimal("6300.00")
        )

    def test_covered_salary_follows_termset_not_contract(self):
        # Contract runs the whole month, but a raise takes effect June 10. Each
        # term set is prorated by its own effective window, not the contract.
        from payroll.services import SalaryEstimateService
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        old_terms = ContractTermSet.objects.create(
            contract=contract, effective_from=date(2025, 6, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        new_terms = ContractTermSet.objects.create(
            contract=contract, effective_from=date(2025, 6, 10),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        # New term set active June 10–30 → 21/30 days.
        self.assertEqual(
            SalaryEstimateService.covered_salary(new_terms, 2025, 6),
            (Decimal("30000") * 21 / 30).quantize(Decimal("0.01")),
        )
        # Old term set active June 1–9 → 9/30 days.
        self.assertEqual(
            SalaryEstimateService.covered_salary(old_terms, 2025, 6),
            (Decimal("30000") * 9 / 30).quantize(Decimal("0.01")),
        )

    def test_mid_month_raise_sums_both_rates(self):
        # Raise mid-month: 60000 for June 1–20, 90000 for June 21–30.
        # Monthly earning = 60000 × 20/30 + 90000 × 10/30 = 40000 + 30000 = 70000.
        wp = Workplace.objects.create(name="Raise Corp")
        contract = WorkplaceContract.objects.create(workplace=wp)
        ts_first = ContractTermSet.objects.create(
            contract=contract, effective_from=date(2025, 6, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("60000.00"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        # Last term set carries the contract's end date (June 30).
        ContractTermSet.objects.create(
            contract=contract, effective_from=date(2025, 6, 21),
            effective_until=date(2025, 6, 30),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("90000.00"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        # Viewed after month end → the whole month is Earned.
        pay = DashboardDataService._compute_pay(
            ts_first, Decimal("0"), Decimal("0"),
            2025, 6, date(2025, 6, 18), date(2025, 7, 1),
        )
        self.assertEqual(pay.earned_gross, Decimal("70000.00"))
        self.assertEqual(pay.planned_gross, Decimal("0"))


class ComputePayDeductionTests(TestCase):
    """_compute_pay estimates the month once and allocates the earned/planned
    split out of it. Estimating the halves separately applied the monthly
    personfradrag to each and overstated net — see
    payroll.tests.test_personfradrag for the same defect in _combine_estimates.
    """

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2025, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Split Pay Corp")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)

    def _hourly(self):
        return ContractTermSet.objects.create(
            contract=self.contract, effective_from=date(2025, 6, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("200.00"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )

    def test_hourly_earned_plus_planned_prices_as_one_month(self):
        """100 approved + 50 planned hours must cost the same tax as 150 hours
        in one go — it is one month's pay, taxed once."""
        terms = self._hourly()
        pay = DashboardDataService._compute_pay(
            terms, Decimal("100"), Decimal("50"),
            2025, 6, date(2025, 6, 18), date(2025, 6, 20),
        )
        whole = SalaryEstimateService.estimate(
            terms, Decimal("150"), as_of=date(2025, 6, 18),
        )

        self.assertEqual(pay.earned_gross + pay.planned_gross, whole.taxable_gross)
        self.assertEqual(
            pay.earned_net + pay.planned_net, whole.tax_breakdown.net_pay,
        )

    def test_hourly_split_matches_the_hours_ratio(self):
        terms = self._hourly()
        pay = DashboardDataService._compute_pay(
            terms, Decimal("100"), Decimal("50"),
            2025, 6, date(2025, 6, 18), date(2025, 6, 20),
        )
        # 100:50 of 30000 gross.
        self.assertEqual(pay.earned_gross, Decimal("20000.00"))
        self.assertEqual(pay.planned_gross, Decimal("10000.00"))

    def test_hourly_with_no_planned_hours_is_unchanged(self):
        terms = self._hourly()
        pay = DashboardDataService._compute_pay(
            terms, Decimal("100"), Decimal("0"),
            2025, 6, date(2025, 6, 18), date(2025, 6, 20),
        )
        whole = SalaryEstimateService.estimate(
            terms, Decimal("100"), as_of=date(2025, 6, 18),
        )
        self.assertEqual(pay.earned_net, whole.tax_breakdown.net_pay)
        self.assertEqual(pay.planned_net, Decimal("0"))

    def test_salaried_mid_month_raise_deducts_once(self):
        """The gross split is already pinned above; this pins the net, which is
        what the double deduction moved."""
        ts_first = ContractTermSet.objects.create(
            contract=self.contract, effective_from=date(2025, 6, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("60000.00"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        ContractTermSet.objects.create(
            contract=self.contract, effective_from=date(2025, 6, 21),
            effective_until=date(2025, 6, 30),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("90000.00"), weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        pay = DashboardDataService._compute_pay(
            ts_first, Decimal("0"), Decimal("0"),
            2025, 6, date(2025, 6, 18), date(2025, 7, 1),
        )
        combined = SalaryEstimateService.salaried_month_estimate(
            self.contract, 2025, 6, as_of=date(2025, 6, 18),
        )

        self.assertEqual(pay.earned_gross, Decimal("70000.00"))
        self.assertEqual(pay.earned_net, combined.tax_breakdown.net_pay)
        self.assertEqual(combined.tax_breakdown.monthly_deduction, Decimal("4000.00"))
