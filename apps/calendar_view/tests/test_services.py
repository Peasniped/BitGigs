from datetime import date, time
from decimal import Decimal
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import TestCase

from core.models import UserSettings
from calendar_view.services import CalendarService, CalendarDay


class CalendarServiceTest(TestCase):
    def setUp(self):
        UserSettings.objects.create(pk=1, week_start=0)

    def test_month_calendar_structure(self):
        """Month calendar should produce full weeks."""
        grid = CalendarService.month_calendar(2026, 3)
        self.assertEqual(grid.title, "March 2026")
        # Each week has 7 days
        for week in grid.weeks:
            self.assertEqual(len(week.days), 7)
        # March 1 2026 is a Sunday. With Monday start, the grid starts on Feb 23.
        first_day = grid.weeks[0].days[0].date
        self.assertEqual(first_day.weekday(), 0)  # Monday

    def test_sunday_week_start(self):
        settings = UserSettings.load()
        settings.week_start = 6
        settings.save()

        grid = CalendarService.month_calendar(2026, 3)
        first_day = grid.weeks[0].days[0].date
        self.assertEqual(first_day.weekday(), 6)  # Sunday

    def test_days_outside_period_marked(self):
        grid = CalendarService.month_calendar(2026, 3)
        # First day of grid might be before March 1
        first_day = grid.weeks[0].days[0]
        if first_day.date < date(2026, 3, 1):
            self.assertFalse(first_day.is_in_period)

    def test_week_numbers_are_iso(self):
        """Each week row carries the ISO 8601 week number of its Thursday."""
        grid = CalendarService.month_calendar(2026, 3)
        for week in grid.weeks:
            thursday = next(d for d in week.days if d.date.weekday() == 3)
            self.assertEqual(week.week_number, thursday.date.isocalendar()[1])

    def test_week_number_year_boundary(self):
        """ISO week 1 of 2026 spans the 2025/2026 boundary (2026-01-01 is a
        Thursday, so its week is week 1)."""
        grid = CalendarService.month_calendar(2026, 1)
        first_week = grid.weeks[0]
        # The row containing 2026-01-01 should be numbered week 1.
        jan1_week = next(
            w for w in grid.weeks
            if any(d.date == date(2026, 1, 1) for d in w.days)
        )
        self.assertEqual(jan1_week.week_number, 1)
        # And the row's Thursday is indeed 2026-01-01.
        self.assertIn(date(2026, 1, 1), [d.date for d in first_week.days])

    def test_week_number_independent_of_week_start(self):
        """The ISO number is the Thursday's, so it is identical whether the grid
        starts on Monday or Sunday."""
        mon_grid = CalendarService.month_calendar(2026, 3)
        settings = UserSettings.load()
        settings.week_start = 6
        settings.save()
        sun_grid = CalendarService.month_calendar(2026, 3)

        def thursday_weeks(grid):
            return {
                next(d for d in w.days if d.date.weekday() == 3).date: w.week_number
                for w in grid.weeks
            }

        mon_map = thursday_weeks(mon_grid)
        sun_map = thursday_weeks(sun_grid)
        # Every Thursday common to both grids has the same week number.
        for thu, num in mon_map.items():
            if thu in sun_map:
                self.assertEqual(sun_map[thu], num)

    def test_sorted_shifts_merges_and_orders_by_start_time(self):
        approved = SimpleNamespace(start_time=time(12, 0))
        planned_early = SimpleNamespace(start_time=time(8, 0))
        planned_late = SimpleNamespace(start_time=time(15, 0))
        day = CalendarDay(
            date=date(2026, 3, 2),
            is_in_period=True,
            is_today=False,
            approved_shifts=[approved],
            planned_shifts=[planned_late, planned_early],
        )

        result = day.sorted_shifts

        self.assertEqual(
            [s.start_time for s in result],
            [time(8, 0), time(12, 0), time(15, 0)],
        )
        self.assertTrue(planned_early.is_planned)
        self.assertTrue(planned_late.is_planned)
        self.assertFalse(approved.is_planned)


class ShiftChipRenderTest(TestCase):
    """Render the shared chip partial directly to check the type/break markup."""

    def _chip(self, show_colors, shift_type="sick_leave", break_minutes=30):
        wp = SimpleNamespace(
            avatar_color="#123456", custom_icon=None, icon="",
            avatar_initials="AB", name="Acme", accent_color="", color="",
        )
        item = SimpleNamespace(
            workplace=wp, workplace_id=1, pk=5, shift_type=shift_type,
            break_minutes=break_minutes, start_time=time(8, 0),
            end_time=time(16, 0), net_hours=Decimal("7.5"),
        )
        return render_to_string(
            "calendar_view/_shift_chip.html",
            {
                "item": item, "is_planned": True, "draggable": True,
                "show_shift_type_colors": show_colors,
            },
        )

    def test_type_class_and_sick_symbol_only_when_enabled(self):
        on = self._chip(show_colors=True)
        self.assertIn("shift-chip--type-sick_leave", on)  # band colour comes from this
        self.assertIn("shift-chip__sym--sick", on)  # biohazard

        off = self._chip(show_colors=False)
        self.assertNotIn("shift-chip--type-", off)
        self.assertNotIn("shift-chip__sym", off)

    def test_symbols_only_for_their_types(self):
        on_site = self._chip(show_colors=True, shift_type="on_site")
        self.assertIn("shift-chip--type-on_site", on_site)  # band for every type
        self.assertNotIn("shift-chip__sym", on_site)  # no symbol for on-site

        vacation = self._chip(show_colors=True, shift_type="vacation")
        self.assertIn("shift-chip__sym--vacation", vacation)  # palms
        self.assertNotIn("shift-chip__sym--sick", vacation)

    def test_coffee_cup_tracks_break_minutes_regardless_of_setting(self):
        # Break cup shows even with the colour setting off...
        self.assertIn("bi-cup-hot", self._chip(show_colors=False, break_minutes=15))
        # ...and is absent when there is no break.
        self.assertNotIn("bi-cup-hot", self._chip(show_colors=True, break_minutes=0))
