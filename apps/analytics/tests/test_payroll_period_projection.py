"""Analytics buckets by payroll period, not calendar month.

For a workplace paid 20th→19th, the hours worked 20–31 July belong to the August
row — the month they are paid in — which is what makes this page agree with the
dashboard. Covers the four behaviours that follow from it:

* a shift lands in the period that pays it,
* a *closed* offset period is actual, never projected (the reported bug: July read
  as a 44.97 h projection while 85.75 h were approved),
* a shift still planned for *today* counts in the current period,
* each certainty band (actual / planned / projected) carries its own amounts and
  the bands always sum back to the row total.
"""
from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from workplaces.models import Workplace, WorkplaceContract, ContractTermSet
from core.models import TaxProfile
from shifts.models import Shift, PlannedShift
from analytics.services import AnalyticsService


class OffsetPeriodTestCase(TestCase):
    """A workplace paid on a 20th→19th cycle."""

    start_day = 20

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Offset Job")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)
        self.terms = ContractTermSet.objects.create(
            contract=self.contract,
            effective_from=date(2026, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
            weekly_hours_fixed=Decimal("20.00"),
            payroll_period_start_day=self.start_day,
        )

    def _rows(self, today, **kwargs):
        proj = AnalyticsService.project_year([self.wp], 2026, today=today, **kwargs)
        return {row.month: row for row in proj.workplaces[0].months}

    @staticmethod
    def _shift(wp, d, hours=8):
        return Shift.objects.create(
            workplace=wp, date=d,
            start_time=time(8, 0), end_time=time(8 + hours, 0),
        )

    @staticmethod
    def _planned(wp, d, hours=8):
        return PlannedShift.objects.create(
            workplace=wp, date=d,
            start_time=time(8, 0), end_time=time(8 + hours, 0),
            status=PlannedShift.Status.PLANNED,
        )


class PeriodBucketingTest(OffsetPeriodTestCase):
    def test_row_bounds_are_the_payroll_period(self):
        rows = self._rows(date(2026, 7, 30))
        self.assertEqual(rows[8].period_start, date(2026, 7, 20))
        self.assertEqual(rows[8].period_end, date(2026, 8, 19))

    def test_late_july_shift_belongs_to_august(self):
        # Worked the 25th; paid in the period that ends 19 August.
        self._shift(self.wp, date(2026, 7, 25))
        rows = self._rows(date(2026, 7, 30))
        self.assertEqual(rows[7].actual.hours, Decimal("0.00"))
        self.assertEqual(rows[8].actual.hours, Decimal("8.00"))

    def test_early_july_shift_belongs_to_july(self):
        self._shift(self.wp, date(2026, 7, 10))
        rows = self._rows(date(2026, 7, 30))
        self.assertEqual(rows[7].actual.hours, Decimal("8.00"))
        self.assertEqual(rows[8].actual.hours, Decimal("0.00"))


class ClosedPeriodIsActualTest(OffsetPeriodTestCase):
    """The reported bug. On 30 July the 20 Jun–19 Jul period has closed, so its
    row is what was worked — it must not fall back to the trailing average."""

    def test_closed_offset_period_is_actual_not_projected(self):
        self._shift(self.wp, date(2026, 7, 10))          # inside the July period
        self._shift(self.wp, date(2026, 6, 25), hours=6)  # also inside it
        rows = self._rows(date(2026, 7, 30))
        july = rows[7]
        self.assertEqual(july.state, "actual")
        self.assertFalse(july.is_projected)
        self.assertEqual(july.actual.hours, Decimal("14.00"))
        self.assertEqual(july.hours, Decimal("14.00"))

    def test_closed_period_with_no_work_stays_zero(self):
        # A month genuinely not worked is a fact, not a gap to guess at.
        self._shift(self.wp, date(2026, 6, 25))  # gives the trailing average a value
        rows = self._rows(date(2026, 7, 30))
        self.assertEqual(rows[3].state, "actual")
        self.assertEqual(rows[3].hours, Decimal("0"))
        self.assertEqual(rows[3].gross, Decimal("0"))


class TodaysPlannedShiftTest(OffsetPeriodTestCase):
    """A shift planned for today has not been worked yet, so it belongs to the
    planned band — it used to be dropped by an exclusive `date__gt=today`."""

    def test_shift_planned_for_today_counts_in_the_current_period(self):
        self._planned(self.wp, date(2026, 7, 30), hours=6)
        rows = self._rows(date(2026, 7, 30))
        august = rows[8]  # today sits in the 20 Jul–19 Aug period
        self.assertTrue(august.period_start <= date(2026, 7, 30) <= august.period_end)
        self.assertEqual(august.planned.hours, Decimal("6.00"))
        self.assertFalse(august.is_projected)

    def test_planned_shift_already_in_the_past_is_ignored(self):
        # It should have been approved by now; counting it would double up with
        # the approved hours that replaced it.
        self._planned(self.wp, date(2026, 7, 22), hours=6)
        rows = self._rows(date(2026, 7, 30))
        self.assertEqual(rows[8].planned.hours, Decimal("0.00"))

    def test_current_period_mixes_approved_and_planned(self):
        self._shift(self.wp, date(2026, 7, 22), hours=5)     # already worked
        self._planned(self.wp, date(2026, 8, 10), hours=7)   # still ahead
        rows = self._rows(date(2026, 7, 30))
        august = rows[8]
        self.assertEqual(august.state, "actual-planned")
        self.assertTrue(august.is_mixed)
        self.assertEqual(august.actual.hours, Decimal("5.00"))
        self.assertEqual(august.planned.hours, Decimal("7.00"))
        self.assertEqual(august.hours, Decimal("12.00"))


class BandsSumToTotalTest(OffsetPeriodTestCase):
    def test_every_row_adds_up(self):
        self._shift(self.wp, date(2026, 6, 25))
        self._shift(self.wp, date(2026, 7, 22), hours=5)
        self._planned(self.wp, date(2026, 8, 10), hours=7)
        for row in self._rows(date(2026, 7, 30)).values():
            self.assertEqual(
                row.gross, row.actual.gross + row.planned.gross + row.projected.gross,
                f"gross does not add up for month {row.month}",
            )
            self.assertEqual(
                row.net, row.actual.net + row.planned.net + row.projected.net,
                f"net does not add up for month {row.month}",
            )


class TrailingPeriodAverageTest(OffsetPeriodTestCase):
    def test_average_uses_periods_that_have_closed(self):
        # On 30 July the 20 Jun–19 Jul period has closed, so a one-period window
        # must average *it* — walking back from "last calendar month" would take
        # the 20 May–19 Jun one and skip a finished period.
        self._shift(self.wp, date(2026, 7, 10), hours=8)    # in the July period
        self._shift(self.wp, date(2026, 6, 10), hours=12)   # in the June period
        avg = AnalyticsService.trailing_average_hours(
            self.wp, 1, ref=date(2026, 7, 30), method="avg",
        )
        self.assertEqual(avg, Decimal("8.00"))


class RollingProjectionTest(TestCase):
    """Each period projects from its *own* trailing window, so consecutive
    projected periods differ instead of repeating one figure to December."""

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Rolling Job")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2025, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
            weekly_hours_fixed=Decimal("20.00"),
            payroll_period_start_day=1,
        )
        # A rising history through the first half of the year: 4h, 6h, 8h …
        for month, hours in ((1, 4), (2, 6), (3, 8), (4, 10), (5, 12), (6, 14)):
            Shift.objects.create(
                workplace=self.wp, date=date(2026, month, 10),
                start_time=time(8, 0), end_time=time(8 + hours, 0),
            )

    def _rows(self, **kwargs):
        proj = AnalyticsService.project_year(
            [self.wp], 2026, today=date(2026, 7, 15),
            trailing_months=3, method="avg", **kwargs,
        )
        return {row.month: row for row in proj.workplaces[0].months}

    def test_consecutive_projections_differ(self):
        rows = self._rows()
        projected = [rows[m].projected.hours for m in (8, 9, 10, 11, 12)]
        self.assertEqual(len(set(projected)), len(projected), f"repeated figures: {projected}")

    def test_first_projection_averages_the_three_periods_before_it(self):
        # August looks back at May, June and July. July is the current period and
        # holds nothing, so it projects (10+12+14)/3 = 12 first, and August then
        # averages 12, 14 and 12 → 12.67.
        rows = self._rows()
        self.assertEqual(rows[7].projected.hours, Decimal("12.00"))
        self.assertEqual(rows[8].projected.hours, Decimal("12.67"))

    def test_projection_does_not_decay_toward_zero(self):
        # The window rolls forward on each period's own resolved hours. Feeding it
        # approved hours alone would empty it as it advanced and drive every later
        # period to zero.
        rows = self._rows()
        for month in (9, 10, 11, 12):
            self.assertGreater(
                rows[month].projected.hours, Decimal("5"),
                f"month {month} decayed to {rows[month].projected.hours}",
            )

    def test_planned_work_feeds_later_projections(self):
        # A big planned September lifts the periods that look back at it.
        base = self._rows()[11].projected.hours
        PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 9, 10),
            start_time=time(8, 0), end_time=time(20, 0),  # 12h
        )
        PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 9, 20),
            start_time=time(8, 0), end_time=time(20, 0),  # 12h
        )
        lifted = self._rows()[11].projected.hours
        self.assertGreater(lifted, base)


class SalariedHistoryIgnoredTest(TestCase):
    """An hourly projection must not learn from periods the workplace was
    salaried: those logged hours were never paid hourly."""

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Switched Job")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        common = dict(
            contract=contract,
            weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )
        ContractTermSet.objects.create(
            effective_from=date(2026, 1, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("31000.00"), **common,
        )
        ContractTermSet.objects.create(
            effective_from=date(2026, 6, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"), **common,
        )
        # Heavy logged hours while salaried, light ones once hourly.
        for month in (3, 4, 5):
            Shift.objects.create(
                workplace=self.wp, date=date(2026, month, 10),
                start_time=time(8, 0), end_time=time(20, 0),  # 12h
            )
        Shift.objects.create(
            workplace=self.wp, date=date(2026, 6, 10),
            start_time=time(8, 0), end_time=time(11, 0),  # 3h, hourly era
        )

    def test_projection_only_learns_from_hourly_periods(self):
        proj = AnalyticsService.project_year(
            [self.wp], 2026, today=date(2026, 7, 15),
            trailing_months=6, method="avg",
        )
        rows = {row.month: row for row in proj.workplaces[0].months}
        # Only June was hourly, with 3 h — the 12 h salaried months are skipped.
        self.assertEqual(rows[7].projected.hours, Decimal("3.00"))


class ProjectionProrationTest(TestCase):
    """A period the contract only partly covers gets a partial projection."""

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Ending Job")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2026, 1, 1),
            effective_until=date(2026, 10, 15),  # job ends mid-October
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
            weekly_hours_fixed=Decimal("20.00"),
            payroll_period_start_day=1,
        )
        Shift.objects.create(
            workplace=self.wp, date=date(2026, 8, 10),
            start_time=time(8, 0), end_time=time(18, 0),  # 10h in the August period
        )

    def test_partly_covered_period_projects_only_its_active_days(self):
        proj = AnalyticsService.project_year(
            [self.wp], 2026, today=date(2026, 9, 1),
            trailing_months=1, method="avg",
        )
        rows = {row.month: row for row in proj.workplaces[0].months}
        # Trailing average is August's 10 h; October is covered 15 of 31 days.
        self.assertEqual(proj.workplaces[0].trailing_avg_monthly_hours, Decimal("10.00"))
        october = rows[10]
        self.assertEqual(october.state, "projected")
        self.assertEqual(october.projected.hours, Decimal("4.84"))  # 10 × 15/31

    def test_fully_covered_period_projects_the_whole_average(self):
        proj = AnalyticsService.project_year(
            [self.wp], 2026, today=date(2026, 9, 1),
            trailing_months=1, method="avg",
        )
        rows = {row.month: row for row in proj.workplaces[0].months}
        self.assertEqual(rows[9].projected.hours, Decimal("10.00"))


class MidPeriodRateChangeTest(TestCase):
    """Hours are priced at the rate in force on each shift's own date — a raise
    mid-period used to reprice the whole period at the new rate."""

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Raise Job")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        common = dict(
            contract=contract,
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            weekly_hours_fixed=Decimal("20.00"),
            payroll_period_start_day=1,
        )
        ContractTermSet.objects.create(
            effective_from=date(2026, 1, 1), hourly_rate=Decimal("150.00"), **common,
        )
        ContractTermSet.objects.create(
            effective_from=date(2026, 7, 15), hourly_rate=Decimal("200.00"), **common,
        )

    def test_each_shift_is_paid_at_its_own_rate(self):
        # 8 h before the raise and 8 h after: 8×150 + 8×200, not 16×200.
        for day in (10, 20):
            Shift.objects.create(
                workplace=self.wp, date=date(2026, 7, day),
                start_time=time(8, 0), end_time=time(16, 0),
            )
        proj = AnalyticsService.project_year([self.wp], 2026, today=date(2026, 7, 31))
        july = next(r for r in proj.workplaces[0].months if r.month == 7)
        self.assertEqual(july.hours, Decimal("16.00"))
        self.assertEqual(july.actual.gross, Decimal("2800.00"))


class SalariedDaySplitTest(TestCase):
    """A salary accrues per calendar day, so days up to today are actual and
    later ones planned. A salary is known from the contract — never projected."""

    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.wp = Workplace.objects.create(name="Salaried Job")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2026, 1, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("31000.00"),
            weekly_hours_fixed=Decimal("37.00"),
            payroll_period_start_day=1,
        )

    def _rows(self, today):
        proj = AnalyticsService.project_year([self.wp], 2026, today=today)
        return {row.month: row for row in proj.workplaces[0].months}

    def test_current_period_splits_at_today(self):
        rows = self._rows(date(2026, 7, 10))
        july = rows[7]
        self.assertEqual(july.state, "actual-planned")
        # 10 of July's 31 days earned, 21 still to come.
        self.assertEqual(july.actual.gross, Decimal("10000.00"))
        self.assertEqual(july.planned.gross, Decimal("21000.00"))
        self.assertEqual(july.gross, Decimal("31000.00"))

    def test_future_period_is_planned_not_projected(self):
        rows = self._rows(date(2026, 7, 10))
        self.assertEqual(rows[9].state, "planned")
        self.assertFalse(rows[9].is_projected)
        self.assertEqual(rows[9].planned.gross, Decimal("31000.00"))

    def test_past_period_is_all_actual(self):
        rows = self._rows(date(2026, 7, 10))
        self.assertEqual(rows[5].state, "actual")
        self.assertEqual(rows[5].actual.gross, Decimal("31000.00"))
        self.assertEqual(rows[5].planned.gross, Decimal("0"))
