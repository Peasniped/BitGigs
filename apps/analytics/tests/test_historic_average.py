"""The workplace card's headline average must describe the *selected* range.

Regression: the card showed the trailing average, which is anchored at today and
filters out periods with no active contract. For a job that ended inside the
range every period in that window was filtered out, the window came back empty,
and an empty window aggregates to Decimal("0") — so a workplace with nine months
of shifts reported "0 h/wk" rather than what it was actually worked.
"""
from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from analytics.services import AnalyticsService
from core.models import TaxProfile
from shifts.models import Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract

TODAY = date(2026, 8, 13)


class HistoricAverageTests(TestCase):
    def setUp(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"), tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"), am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2025, 1, 1),
        )

    def _hourly_workplace(self, name, start, until=None):
        wp = Workplace.objects.create(name=name)
        contract = WorkplaceContract.objects.create(workplace=wp)
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=start,
            effective_until=until,
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
            weekly_hours_min=Decimal("5"),
            weekly_hours_max=Decimal("15"),
            payroll_period_start_day=1,
        )
        return wp

    def _add_shifts(self, wp, first_month, months, per_month=4):
        """`per_month` eight-hour shifts a month, starting at `first_month`."""
        y, m = first_month
        for _ in range(months):
            for day in range(1, per_month + 1):
                Shift.objects.create(
                    workplace=wp, date=date(y, m, day + 1),
                    start_time=time(8, 0), end_time=time(16, 0), break_minutes=0,
                )
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    # ── the reported bug ────────────────────────────────────────────────────
    def test_ended_contract_reports_the_months_it_was_worked(self):
        wp = self._hourly_workplace("Café", date(2025, 1, 1), date(2025, 9, 30))
        self._add_shifts(wp, (2025, 1), months=9)          # 32 h/mo, Jan–Sep 2025

        hist = AnalyticsService.historic_average_hours(
            wp, date(2025, 1, 1), date(2026, 12, 31), ref=TODAY,
        )
        self.assertTrue(hist.has_data)
        self.assertEqual(hist.periods, 9)
        self.assertEqual(hist.monthly, Decimal("32.00"))
        self.assertEqual(hist.first, date(2025, 1, 1))
        self.assertEqual(hist.last, date(2025, 9, 30))

        # The trailing average — anchored at today — still reports 0 for this
        # workplace. That is what the card used to show.
        self.assertEqual(
            AnalyticsService.trailing_average_hours(wp, 6, ref=TODAY, method="avg"),
            Decimal("0"),
        )

    def test_ended_contract_has_nothing_to_project(self):
        wp = self._hourly_workplace("Café", date(2025, 1, 1), date(2025, 9, 30))
        self._add_shifts(wp, (2025, 1), months=9)
        proj = AnalyticsService.project_period(
            [wp], date(2025, 1, 1), date(2026, 12, 31), today=TODAY,
        )
        self.assertFalse(proj.workplaces[0].has_projection)

    # ── the same empty window, in the other direction ───────────────────────
    def test_brand_new_job_reports_no_data_rather_than_zero(self):
        """A job whose first period has not closed yet has nothing to average.
        It must read as "—", not as a confident zero."""
        wp = self._hourly_workplace("Just Started", date(2026, 8, 1))
        self._add_shifts(wp, (2026, 8), months=1)

        hist = AnalyticsService.historic_average_hours(
            wp, date(2026, 1, 1), date(2026, 12, 31), ref=TODAY,
        )
        self.assertFalse(hist.has_data)
        self.assertEqual(hist.periods, 0)

        proj = AnalyticsService.project_period(
            [wp], date(2026, 1, 1), date(2026, 12, 31), today=TODAY,
        )
        # The job is live, so a forecast is wanted — but there is no closed
        # period to base one on, and an empty window averages to 0. The card
        # must say "too new", not project zero hours a month.
        self.assertTrue(proj.workplaces[0].has_projection)
        self.assertFalse(proj.workplaces[0].has_projection_basis)
        self.assertEqual(proj.workplaces[0].trailing_avg_monthly_hours, Decimal("0"))

    # ── everything else must keep working ───────────────────────────────────
    def test_active_job_averages_only_closed_periods(self):
        wp = self._hourly_workplace("Netto", date(2025, 1, 1))
        self._add_shifts(wp, (2025, 1), months=20)         # Jan 2025 – Aug 2026

        hist = AnalyticsService.historic_average_hours(
            wp, date(2025, 1, 1), date(2026, 12, 31), ref=TODAY,
        )
        # Jan 2025 → Jul 2026 closed; August is still running and is excluded.
        self.assertEqual(hist.periods, 19)
        self.assertEqual(hist.last, date(2026, 7, 31))
        self.assertEqual(hist.monthly, Decimal("32.00"))

    def test_range_scopes_the_average(self):
        """Narrowing the filter narrows the figure — that is the whole point."""
        wp = self._hourly_workplace("Netto", date(2025, 1, 1))
        self._add_shifts(wp, (2025, 1), months=6, per_month=2)    # 16 h/mo H1 2025
        self._add_shifts(wp, (2025, 7), months=6, per_month=6)    # 48 h/mo H2 2025

        first_half = AnalyticsService.historic_average_hours(
            wp, date(2025, 1, 1), date(2025, 6, 30), ref=TODAY,
        )
        whole_year = AnalyticsService.historic_average_hours(
            wp, date(2025, 1, 1), date(2025, 12, 31), ref=TODAY,
        )
        self.assertEqual(first_half.monthly, Decimal("16.00"))
        self.assertEqual(whole_year.monthly, Decimal("32.00"))

    def test_average_is_a_plain_mean_not_the_projection_method(self):
        """The historic figure describes closed months, so it must not weight the
        recent ones — that is the forecast's job."""
        wp = self._hourly_workplace("Netto", date(2025, 1, 1))
        self._add_shifts(wp, (2025, 1), months=3, per_month=2)    # 16 h/mo
        self._add_shifts(wp, (2025, 4), months=3, per_month=8)    # 64 h/mo

        hist = AnalyticsService.historic_average_hours(
            wp, date(2025, 1, 1), date(2025, 6, 30), ref=TODAY,
        )
        self.assertEqual(hist.monthly, Decimal("40.00"))          # (16+64)/2

        ema = AnalyticsService.trailing_average_hours(
            wp, 6, ref=date(2025, 7, 1), method="ema",
        )
        self.assertNotEqual(ema, hist.monthly)

    def test_weekly_is_derived_from_monthly(self):
        wp = self._hourly_workplace("Netto", date(2025, 1, 1))
        self._add_shifts(wp, (2025, 1), months=6)
        hist = AnalyticsService.historic_average_hours(
            wp, date(2025, 1, 1), date(2025, 6, 30), ref=TODAY,
        )
        self.assertEqual(hist.monthly, Decimal("32.00"))
        self.assertEqual(hist.weekly, Decimal("7.38"))            # 32 / (52/12)
