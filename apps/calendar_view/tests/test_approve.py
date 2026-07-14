from datetime import date, time

from django.test import TestCase

from calendar_view.services import approve_planned_shifts
from shifts.models import PlannedShift, Shift
from workplaces.models import Workplace


class ApprovePlannedShiftsTest(TestCase):
    def setUp(self):
        self.workplace = Workplace.objects.create(name="Cafe")
        self.shift = PlannedShift.objects.create(
            workplace=self.workplace,
            date=date(2026, 3, 2),
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=0,
        )

    def test_inline_edits_are_applied_before_approval(self):
        count, _ = approve_planned_shifts(
            [self.shift.pk],
            edits={
                str(self.shift.pk): {
                    "start_time": "10:00",
                    "end_time": "16:00",
                    "break_minutes": "30",
                    "shift_type": "remote",
                }
            },
        )

        self.assertEqual(count, 1)
        session = Shift.objects.get(workplace=self.workplace, date=date(2026, 3, 2))
        self.assertEqual(session.start_time, time(10, 0))
        self.assertEqual(session.end_time, time(16, 0))
        self.assertEqual(session.break_minutes, 30)
        self.assertEqual(session.shift_type, "remote")

    def test_unparseable_break_keeps_the_existing_value(self):
        self.shift.break_minutes = 45
        self.shift.save()

        approve_planned_shifts(
            [self.shift.pk],
            edits={str(self.shift.pk): {"break_minutes": "not a number"}},
        )

        session = Shift.objects.get(workplace=self.workplace, date=date(2026, 3, 2))
        self.assertEqual(session.break_minutes, 45)
