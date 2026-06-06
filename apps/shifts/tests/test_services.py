from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from workplaces.models import Workplace, WorkplaceContract, ContractTermSet
from shifts.models import Shift
from shifts.services import ShiftSummaryService


class ShiftSummaryServiceTest(TestCase):
    def setUp(self):
        self.wp = Workplace.objects.create(name="Test Corp")
        contract = WorkplaceContract.objects.create(
            workplace=self.wp, start_date=date(2000, 1, 1),
        )
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2000, 1, 1),
            employment_type=ContractTermSet.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"),
            weekly_hours_fixed=Decimal("37.00"),
        )
        self.shift1 = Shift.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(8, 0),
            end_time=time(12, 0),
            break_minutes=0,
            shift_type=Shift.ShiftType.ON_SITE,
        )
        self.shift2 = Shift.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(13, 0),
            end_time=time(17, 0),
            break_minutes=0,
            shift_type=Shift.ShiftType.REMOTE,
        )

    def test_daily_summary(self):
        summaries = ShiftSummaryService.daily_summary(date(2026, 3, 2))
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual(s.total_hours, Decimal("8.00"))
        self.assertEqual(s.shift_count, 2)

    def test_monthly_summary(self):
        Shift.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 3),
            start_time=time(8, 0),
            end_time=time(16, 0),
            break_minutes=30,
            shift_type=Shift.ShiftType.ON_SITE,
        )
        summaries = ShiftSummaryService.monthly_summary(2026, 3)
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual(s.working_days, 2)
        self.assertEqual(s.total_hours, Decimal("15.50"))

    def test_daily_summary_empty(self):
        summaries = ShiftSummaryService.daily_summary(date(2026, 1, 1))
        self.assertEqual(len(summaries), 0)


class ShiftModelTest(TestCase):
    def setUp(self):
        self.wp = Workplace.objects.create(name="Model Test Corp")
        contract = WorkplaceContract.objects.create(
            workplace=self.wp, start_date=date(2000, 1, 1),
        )
        ContractTermSet.objects.create(
            contract=contract,
            effective_from=date(2000, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
            weekly_hours_fixed=Decimal("20.00"),
        )

    def test_net_hours_calculation(self):
        shift = Shift.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=30,
        )
        self.assertEqual(shift.gross_minutes, 480)
        self.assertEqual(shift.net_minutes, 450)
        self.assertEqual(shift.net_hours, Decimal("7.5"))

    def test_shift_str(self):
        shift = Shift.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        self.assertIn("Model Test Corp", str(shift))
        self.assertIn("2026-03-02", str(shift))
