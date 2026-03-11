from datetime import date

from django.test import TestCase

from core.models import UserSettings
from workplaces.models import Workplace
from calendar_view.services import CalendarService


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
