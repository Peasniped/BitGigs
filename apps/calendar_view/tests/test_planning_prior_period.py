"""Out-of-period chips on the planning grid.

An offset job (20th→19th cutoff) shows shifts from two payroll periods in one
month, and the ones belonging to the *next* period are greyed and read-only —
they aren't in this month's totals, so offering to edit them here is a trap.

The greying itself is `planning.js` (`markIfPriorPeriod` → `isInPeriod`), which
has no test harness in this repo. What *is* testable is the contract the JS
depends on, and that contract is exactly what broke: approved chips were never
passed through the marking code, so a shift after the cutoff kept the ordinary
blue while planned ones greyed correctly. These tests pin the two server-side
inputs the marking needs — the workplace's period bounds in the page payload,
and `data-workplace-id` on **approved** chips as well as planned ones.
"""
import json
import re
from datetime import date, time
from decimal import Decimal

from core.testing import LoggedInTestCase
from shifts.models import PlannedShift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract

# March 2030 for a 20th-cutoff job: the period runs 20 Feb – 19 Mar, so shifts
# from the 20th onwards belong to the next one.
IN_PERIOD = date(2030, 3, 10)
OUT_OF_PERIOD = date(2030, 3, 25)


class PriorPeriodChipMarkupTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()

        self.wp = Workplace.objects.create(name="Offset", slug="offset")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract, effective_from=date(2029, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("200"), payroll_period_start_day=20,
        )

    def _approved(self, day):
        planned = PlannedShift.objects.create(
            workplace=self.wp, date=day,
            start_time=time(9, 0), end_time=time(17, 0),
        )
        return planned.approve()

    def _planned(self, day):
        return PlannedShift.objects.create(
            workplace=self.wp, date=day,
            start_time=time(9, 0), end_time=time(17, 0),
        )

    def _grid(self):
        resp = self.client.get("/calendar/planning/?year=2030&month=3")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _workplace_payload(self, html):
        """The JSON blob planning.js reads period bounds from."""
        for blob in re.findall(r">(\[\{.*?\}\])<", html, re.S):
            try:
                rows = json.loads(blob)
            except ValueError:
                continue
            if rows and isinstance(rows, list) and "period_start" in rows[0]:
                return rows
        self.fail("no workplace payload carrying period_start on the page")

    def _chips_on(self, html, day):
        """Chip opening tags inside the given day's cell."""
        cell = re.search(
            r'<td[^>]*data-date="%s"(.*?)</td>' % day.isoformat(), html, re.S
        )
        self.assertIsNotNone(cell, f"no calendar cell for {day}")
        return re.findall(r'<div class="shift-chip [^>]*>', cell.group(1))

    def test_the_page_publishes_the_offset_period_bounds(self):
        """isInPeriod() is only as good as these two dates."""
        row = self._workplace_payload(self._grid())[0]
        self.assertEqual(row["period_start"], "2030-02-20")
        self.assertEqual(row["period_end"], "2030-03-19")

    def test_approved_chips_carry_the_workplace_id_the_marking_needs(self):
        """The regression: an approved chip is only greyable if it says which
        workplace it belongs to. Planned chips always did; approved ones must
        too, in *both* periods."""
        self._approved(IN_PERIOD)
        self._approved(OUT_OF_PERIOD)
        html = self._grid()

        for day in (IN_PERIOD, OUT_OF_PERIOD):
            with self.subTest(day=day):
                chips = self._chips_on(html, day)
                self.assertEqual(len(chips), 1)
                self.assertIn("shift-chip--approved", chips[0])
                self.assertIn(f'data-workplace-id="{self.wp.pk}"', chips[0])

    def test_planned_chips_still_carry_it_too(self):
        self._planned(OUT_OF_PERIOD)
        chips = self._chips_on(self._grid(), OUT_OF_PERIOD)
        self.assertEqual(len(chips), 1)
        self.assertIn("shift-chip--planned", chips[0])
        self.assertIn(f'data-workplace-id="{self.wp.pk}"', chips[0])

    def test_out_of_period_shifts_are_on_the_grid_at_all(self):
        """They're deliberately shown (greyed) rather than hidden — the month you
        worked them is where you'd look for them."""
        self._approved(OUT_OF_PERIOD)
        self.assertEqual(len(self._chips_on(self._grid(), OUT_OF_PERIOD)), 1)
