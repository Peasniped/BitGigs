"""Analytics projection with planned shifts + the trailing-average fix.

Covers three behaviours:
* a future month with planned shifts uses those hours (not the projection),
* the current month is a hybrid of approved (worked) + remaining planned hours,
* the trailing average counts only months the contract was active, so pre-hire
  zero-hour months don't drag it down for the first few months of a job.
"""
from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from workplaces.models import Workplace, WorkplaceContract, ContractTermSet
from tax.models import TaxProfile
from shifts.models import Shift, PlannedShift
from analytics.services import AnalyticsService


class PlannedShiftProjectionTest(TestCase):
    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Cafe")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        # Open-ended hourly terms from the start of the year.
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2026, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
            weekly_hours_fixed=Decimal("20.00"),
        )

    def _row(self, proj, month):
        for wpp in proj.workplaces:
            for row in wpp.months:
                if row.month == month:
                    return row
        return None

    def test_future_month_uses_planned_hours(self):
        # An 8-hour planned shift in August (a future month vs. mid-July today).
        PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 8, 10),
            start_time=time(8, 0), end_time=time(16, 0),
            status=PlannedShift.Status.PLANNED,
        )
        proj = AnalyticsService.project_year(
            [self.wp], 2026, today=date(2026, 7, 15), use_planned=True,
        )
        aug = self._row(proj, 8)
        self.assertTrue(aug.is_planned)
        self.assertFalse(aug.is_projected)
        self.assertEqual(aug.hours, Decimal("8.00"))

    def test_use_planned_off_falls_back_to_projection(self):
        PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 8, 10),
            start_time=time(8, 0), end_time=time(16, 0),
            status=PlannedShift.Status.PLANNED,
        )
        proj = AnalyticsService.project_year(
            [self.wp], 2026, today=date(2026, 7, 15), use_planned=False,
        )
        aug = self._row(proj, 8)
        self.assertFalse(aug.is_planned)
        self.assertTrue(aug.is_projected)

    def test_approved_planned_shift_is_ignored(self):
        # An already-approved PlannedShift became a real Shift; counting it too
        # would double it up. It must not drive the planned override.
        PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 8, 10),
            start_time=time(8, 0), end_time=time(16, 0),
            status=PlannedShift.Status.APPROVED,
        )
        proj = AnalyticsService.project_year(
            [self.wp], 2026, today=date(2026, 7, 15), use_planned=True,
        )
        aug = self._row(proj, 8)
        self.assertFalse(aug.is_planned)
        self.assertTrue(aug.is_projected)

    def test_current_month_is_hybrid_approved_plus_remaining_planned(self):
        # Worked 8h earlier this month (approved), 8h still planned ahead, and a
        # stray planned shift on a past day that must NOT be counted.
        Shift.objects.create(
            workplace=self.wp, date=date(2026, 7, 5),
            start_time=time(8, 0), end_time=time(16, 0),
        )
        PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 7, 20),
            start_time=time(8, 0), end_time=time(16, 0),
            status=PlannedShift.Status.PLANNED,
        )
        PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 7, 10),  # before today, ignored
            start_time=time(8, 0), end_time=time(16, 0),
            status=PlannedShift.Status.PLANNED,
        )
        proj = AnalyticsService.project_year(
            [self.wp], 2026, today=date(2026, 7, 15), use_planned=True,
        )
        jul = self._row(proj, 7)
        self.assertTrue(jul.is_planned)
        self.assertEqual(jul.hours, Decimal("16.00"))  # 8 approved + 8 remaining


class TrailingAverageActiveMonthsTest(TestCase):
    def test_average_counts_active_contract_months_only(self):
        wp = Workplace.objects.create(name="New Job")
        contract = WorkplaceContract.objects.create(workplace=wp)
        # Started 1 May 2026 — only May and June fall inside a 6-month window
        # ending mid-July, the four earlier months predate the job.
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2026, 5, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
            weekly_hours_fixed=Decimal("20.00"),
        )
        Shift.objects.create(
            workplace=wp, date=date(2026, 5, 4),
            start_time=time(8, 0), end_time=time(16, 0),  # 8h
        )
        Shift.objects.create(
            workplace=wp, date=date(2026, 6, 1),
            start_time=time(8, 0), end_time=time(16, 0),  # 8h
        )
        Shift.objects.create(
            workplace=wp, date=date(2026, 6, 2),
            start_time=time(8, 0), end_time=time(16, 0),  # 8h
        )
        # Active months = May (8h), June (16h) → mean 12, not 24/6 = 4.
        avg = AnalyticsService.trailing_average_hours(
            wp, 6, ref=date(2026, 7, 15), method="avg",
        )
        self.assertEqual(avg, Decimal("12.00"))
