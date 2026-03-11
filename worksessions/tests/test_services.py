from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from workplaces.models import Workplace
from worksessions.models import WorkSession
from worksessions.services import SessionSummaryService


class SessionSummaryServiceTest(TestCase):
    def setUp(self):
        self.wp = Workplace.objects.create(
            name="Session Test Corp",
            employment_type=Workplace.EmploymentType.SALARIED,
            monthly_salary=Decimal("30000.00"),
            weekly_hours_fixed=Decimal("37.00"),
        )
        self.session1 = WorkSession.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(8, 0),
            end_time=time(12, 0),
            break_minutes=0,
            session_type=WorkSession.SessionType.ON_SITE,
        )
        self.session2 = WorkSession.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(13, 0),
            end_time=time(17, 0),
            break_minutes=0,
            session_type=WorkSession.SessionType.REMOTE,
        )

    def test_daily_summary(self):
        summaries = SessionSummaryService.daily_summary(date(2026, 3, 2))
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual(s.total_hours, Decimal("8.00"))
        self.assertEqual(s.session_count, 2)

    def test_monthly_summary(self):
        # Add another session on a different day
        WorkSession.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 3),
            start_time=time(8, 0),
            end_time=time(16, 0),
            break_minutes=30,
            session_type=WorkSession.SessionType.ON_SITE,
        )
        summaries = SessionSummaryService.monthly_summary(2026, 3)
        self.assertEqual(len(summaries), 1)
        s = summaries[0]
        self.assertEqual(s.working_days, 2)
        # Day 1: 8h, Day 2: 7.5h = 15.5h
        self.assertEqual(s.total_hours, Decimal("15.50"))

    def test_daily_summary_empty(self):
        summaries = SessionSummaryService.daily_summary(date(2026, 1, 1))
        self.assertEqual(len(summaries), 0)


class WorkSessionModelTest(TestCase):
    def setUp(self):
        self.wp = Workplace.objects.create(
            name="Model Test Corp",
            employment_type=Workplace.EmploymentType.HOURLY,
            hourly_rate=Decimal("150.00"),
            weekly_hours_fixed=Decimal("20.00"),
        )

    def test_net_hours_calculation(self):
        session = WorkSession.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(9, 0),
            end_time=time(17, 0),
            break_minutes=30,
        )
        # 8 hours - 30 min = 7.5 hours
        self.assertEqual(session.gross_minutes, 480)
        self.assertEqual(session.net_minutes, 450)
        self.assertEqual(session.net_hours, Decimal("7.5"))

    def test_session_str(self):
        session = WorkSession.objects.create(
            workplace=self.wp,
            date=date(2026, 3, 2),
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        self.assertIn("Model Test Corp", str(session))
        self.assertIn("2026-03-02", str(session))
