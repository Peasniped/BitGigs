from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from workplaces.models import Workplace, WorkplaceContract, ContractTermSet
from shifts.models import Shift
from payroll.services import (
    PayrollPeriodService,
    SalaryEstimateService,
    FlexTimeService,
)
from core.models import TaxProfile


def _make_workplace(name, **termset_kwargs):
    """Create a Workplace + one WorkplaceContract + one ContractTermSet."""
    wp = Workplace.objects.create(name=name)
    contract = WorkplaceContract.objects.create(workplace=wp)
    termset_kwargs.setdefault("effective_from", date(2000, 1, 1))
    ts = ContractTermSet.objects.create(contract=contract, **termset_kwargs)
    return wp, ts


class PayrollPeriodServiceTest(TestCase):
    def setUp(self):
        self.wp, self.ts = _make_workplace(
            "Test Corp",
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"),
            weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
            tax_card_type=ContractTermSet.TaxCardType.HOVEDKORT,
        )

    def test_standard_period_start_day_1(self):
        """Standard month period: 1st to last day."""
        start, end = PayrollPeriodService.get_period_dates(self.ts, 2026, 3)
        self.assertEqual(start, date(2026, 3, 1))
        self.assertEqual(end, date(2026, 3, 31))

    def test_custom_period_start_day_20(self):
        """Custom period: 20th of prev month to 19th of current."""
        self.ts.payroll_period_start_day = 20
        self.ts.save()
        start, end = PayrollPeriodService.get_period_dates(self.ts, 2026, 3)
        self.assertEqual(start, date(2026, 2, 20))
        self.assertEqual(end, date(2026, 3, 19))

    def test_custom_period_february(self):
        """February edge case with short month."""
        self.ts.payroll_period_start_day = 20
        self.ts.save()
        start, end = PayrollPeriodService.get_period_dates(self.ts, 2026, 2)
        self.assertEqual(start, date(2026, 1, 20))
        self.assertEqual(end, date(2026, 2, 19))

    def test_custom_period_january(self):
        """January period spans Dec of previous year."""
        self.ts.payroll_period_start_day = 20
        self.ts.save()
        start, end = PayrollPeriodService.get_period_dates(self.ts, 2026, 1)
        self.assertEqual(start, date(2025, 12, 20))
        self.assertEqual(end, date(2026, 1, 19))


class SalaryEstimateServiceTest(TestCase):
    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"),
            tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"),
            am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )

    def test_hourly_estimate(self):
        _, ts = _make_workplace(
            "Hourly Job",
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("200.00"),
            weekly_hours_fixed=Decimal("20.00"),
        )
        estimate = SalaryEstimateService.estimate(ts, Decimal("80.00"))
        # 80 hours * 200 DKK = 16000
        self.assertEqual(estimate.gross_pay, Decimal("16000.00"))
        self.assertEqual(estimate.taxable_gross, Decimal("16000.00"))
        self.assertIsNotNone(estimate.tax_breakdown)

    def test_salaried_estimate(self):
        _, ts = _make_workplace(
            "Salaried Job",
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("35000.00"),
            weekly_hours_fixed=Decimal("37.00"),
        )
        estimate = SalaryEstimateService.estimate(ts, Decimal("148.00"))
        # Salaried: gross is always monthly_salary regardless of hours
        self.assertEqual(estimate.gross_pay, Decimal("35000.00"))

    def test_pension_basis_includes_fritvalg_and_feriepenge_for_feriekonto(self):
        _, ts = _make_workplace(
            "Pension Basis Job",
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("100.00"),
            weekly_hours_fixed=Decimal("37.00"),
            vacation_type=ContractTermSet.VacationType.FERIEKONTO,
            fritvalgskonto_enabled=True,
            fritvalgskonto_percent=Decimal("5.00"),
            pension_employee_percent=Decimal("2.00"),
            pension_employer_percent=Decimal("10.00"),
        )

        estimate = SalaryEstimateService.estimate(ts, Decimal("100.00"))

        # Gross: 10,000.00
        # Fritvalgskonto (5%): 500.00
        # Feriepenge/FerieKonto (12.5%): 1,250.00
        # Pension basis: 11,750.00
        self.assertEqual(estimate.pension_basis, Decimal("11750.00"))
        self.assertEqual(estimate.employee_pension, Decimal("235.00"))
        self.assertEqual(estimate.employer_pension, Decimal("1175.00"))

    def test_taxable_gross_includes_fritvalgskonto(self):
        _, ts = _make_workplace(
            "Taxable Gross Job",
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("100.00"),
            weekly_hours_fixed=Decimal("37.00"),
            fritvalgskonto_enabled=True,
            fritvalgskonto_percent=Decimal("5.00"),
        )

        estimate = SalaryEstimateService.estimate(ts, Decimal("100.00"))

        self.assertEqual(estimate.gross_pay, Decimal("10000.00"))
        self.assertEqual(estimate.fritvalgskonto, Decimal("500.00"))
        self.assertEqual(estimate.taxable_gross, Decimal("10500.00"))


class FlexTimeServiceTest(TestCase):
    def setUp(self):
        self.workplace, _ = _make_workplace(
            "Flex Corp",
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"),
            weekly_hours_fixed=Decimal("37.00"),
        )

    def test_count_weekdays(self):
        """March 2026: 22 weekdays."""
        count = FlexTimeService.count_weekdays(date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(count, 22)

    def test_flex_positive(self):
        """Working more than expected = positive flex."""
        # March 2026 has 22 weekdays. Expected = 37/5 * 22 = 162.80h
        # Log sessions on all weekdays: 22 days × 7.75h = 170.50h
        for day_num in range(1, 32):  # All days in March
            d = date(2026, 3, day_num)
            if d.weekday() < 5:  # Only weekdays
                Shift.objects.create(
                    workplace=self.workplace,
                    date=d,
                    start_time=time(8, 0),
                    end_time=time(16, 0),  # 8 hours
                    break_minutes=15,
                    shift_type=Shift.ShiftType.ON_SITE,
                )

        result = FlexTimeService.calculate(
            self.workplace, date(2026, 3, 1), date(2026, 3, 31)
        )
        self.assertEqual(result.expected_hours, Decimal("162.80"))
        self.assertGreater(result.actual_hours, Decimal("0"))
        # 22 days * (8h - 15min) = 22 * 7.75 = 170.50
        self.assertEqual(result.actual_hours, Decimal("170.50"))
        self.assertEqual(result.flex_this_period, Decimal("7.70"))  # 170.50 - 162.80

    def test_flex_negative(self):
        """Working less than expected = negative flex."""
        # Log only 5 days of 7h each = 35h
        for day_num in [2, 3, 4, 5, 6]:
            d = date(2026, 3, day_num)
            if d.weekday() < 5:
                Shift.objects.create(
                    workplace=self.workplace,
                    date=d,
                    start_time=time(9, 0),
                    end_time=time(16, 0),  # 7 hours
                    shift_type=Shift.ShiftType.REMOTE,
                )

        result = FlexTimeService.calculate(
            self.workplace, date(2026, 3, 1), date(2026, 3, 31)
        )
        self.assertLess(result.flex_this_period, Decimal("0"))

    def test_flex_with_carry_over(self):
        """Flex total = carried_over + this period's flex."""
        result = FlexTimeService.calculate(
            self.workplace,
            date(2026, 3, 1),
            date(2026, 3, 31),
            carried_over=Decimal("5.50"),
        )
        # No sessions logged → actual = 0, expected = 162.80
        # flex_this = 0 - 162.80 = -162.80
        # flex_total = 5.50 + (-162.80) = -157.30
        self.assertEqual(result.flex_carried_over, Decimal("5.50"))
        self.assertEqual(result.flex_total, Decimal("-157.30"))
