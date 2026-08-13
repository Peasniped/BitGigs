"""The demo dataset has to read as one person's working life, not as noise.

Three rules carry that, and all three were learned by looking at the generated
calendar: jobs that piled up four and five deep, shifts booked on top of each
other, and a holiday at one employer with a shift at another the same day.
"""
from collections import defaultdict
from datetime import date, timedelta

from django.test import TestCase

from core.demo_data import build_demo_data
from core.onboarding import is_setup_complete
from shifts.models import PlannedShift, Shift
from workplaces.models import Workplace

LEAVE = {"vacation", "sick_leave", "paid_absence"}
TODAY = date(2026, 8, 13)


class DemoDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Payroll generation is by far the slowest part and none of these rules
        # depend on it.
        cls.result = build_demo_data(today=TODAY, with_payroll=False)
        cls.shifts = [
            (s.date, s.start_time, s.end_time, s.workplace_id, s.shift_type)
            for s in Shift.objects.all()
        ] + [
            (p.date, p.start_time, p.end_time, p.workplace_id, p.shift_type)
            for p in PlannedShift.objects.all()
        ]
        cls.by_date = defaultdict(list)
        for row in cls.shifts:
            cls.by_date[row[0]].append(row)

    def test_never_more_than_three_jobs_at_once(self):
        workplaces = list(Workplace.objects.prefetch_related("contracts__term_sets"))
        day, worst, worst_day = self.result.first_day, 0, None
        while day <= self.result.last_day:
            active = sum(
                1 for wp in workplaces if wp.active_contract_on(day) is not None
            )
            if active > worst:
                worst, worst_day = active, day
            day += timedelta(days=1)
        self.assertLessEqual(worst, 3, f"{worst} jobs active on {worst_day}")
        # …and the third slot is genuinely used, or the rule is met by accident.
        self.assertEqual(worst, 3)

    def test_no_shifts_overlap_in_time(self):
        clashes = []
        for day, items in self.by_date.items():
            items = sorted(items, key=lambda r: r[1])
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    if a[1] < b[2] and b[1] < a[2]:
                        clashes.append((day, a[1], a[2], b[1], b[2]))
        self.assertEqual(clashes, [])

    def test_leave_is_never_mixed_with_work_on_the_same_day(self):
        mixed = [
            day for day, items in self.by_date.items()
            if {r[4] for r in items} & LEAVE and {r[4] for r in items} - LEAVE
        ]
        self.assertEqual(mixed, [])

    def test_leave_actually_appears(self):
        """Guards the rule above from passing because nothing takes leave."""
        kinds = {r[4] for r in self.shifts}
        self.assertIn("vacation", kinds)
        self.assertIn("sick_leave", kinds)

    def test_history_is_anchored_on_today_not_fixed_dates(self):
        """A fixture pinned to literal years reads as ancient history once the
        year turns; every date must move with `today`."""
        later = build_demo_data(today=TODAY + timedelta(days=365), with_payroll=False)
        self.assertGreater(later.first_day, self.result.first_day)
        self.assertGreater(later.last_day, self.result.last_day)

    def test_leaves_shifts_awaiting_approval_and_a_planned_future(self):
        self.assertGreater(self.result.pending, 0)
        self.assertGreater(self.result.planned, 0)
        self.assertGreater(self.result.approved, 100)
        # Planned work runs past today, which is what analytics needs to show a
        # planned band beside the projected one.
        self.assertGreater(self.result.last_day, TODAY)

    def test_setup_reads_as_complete(self):
        """The demo database must land past onboarding, or it opens on the
        wizard instead of the app."""
        self.assertTrue(is_setup_complete())

    def test_is_reproducible_for_a_given_seed(self):
        first = sorted(self.shifts)
        build_demo_data(today=TODAY, with_payroll=False)
        again = sorted(
            [(s.date, s.start_time, s.end_time, s.workplace_id, s.shift_type)
             for s in Shift.objects.all()]
            + [(p.date, p.start_time, p.end_time, p.workplace_id, p.shift_type)
               for p in PlannedShift.objects.all()]
        )
        # Workplace ids change on a rebuild; compare everything else.
        self.assertEqual(
            [(d, s, e, t) for (d, s, e, _w, t) in first],
            [(d, s, e, t) for (d, s, e, _w, t) in again],
        )
