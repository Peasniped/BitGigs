"""A salaried term set active only part of a month must project a *prorated*
gross in analytics — not the full monthly salary (regression: analytics used
to ignore the term set's active window)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from workplaces.models import Workplace, WorkplaceContract, ContractTermSet
from core.models import TaxProfile
from analytics.services import AnalyticsService


class SalariedProrationInProjectionTest(TestCase):
    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Short Stint")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        # Active only July 7–10, 2026 (4 of 31 days) at 100.000/mo.
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2026, 7, 7),
            effective_until=date(2026, 7, 10),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("100000.00"),
            weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )

    def _july_row(self):
        proj = AnalyticsService.project_year([self.wp], 2026, today=date(2026, 7, 10))
        for wpp in proj.workplaces:
            for row in wpp.months:
                if row.month == 7:
                    return row
        return None

    def test_july_gross_is_prorated_not_full_salary(self):
        row = self._july_row()
        self.assertIsNotNone(row)
        self.assertTrue(row.contract_active)
        # 100000 × 4 / 31 = 12903.23, not the full 100000.
        self.assertEqual(row.gross, Decimal("12903.23"))

    def test_month_without_active_terms_is_inactive(self):
        # August has no active term set → no projected gross.
        proj = AnalyticsService.project_year([self.wp], 2026, today=date(2026, 7, 10))
        aug = next(
            r for wpp in proj.workplaces for r in wpp.months if r.month == 8
        )
        self.assertFalse(aug.contract_active)
        self.assertEqual(aug.gross, Decimal("0"))
