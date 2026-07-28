"""The planning page's "Send invites" button state (``invite_pending_count``).

The button has to promise exactly what pressing it does. It used to count every
planned shift on the **grid**, which is padded out to whole weeks and to the union
of every workplace's payroll period — so with an offset (20th→19th) job it saw
next period's shifts and kept reading "Send invites" after everything the send
covers had already gone out. Pressing it again then sent nothing, silently.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from calendar_sync import invites
from calendar_sync.models import CalendarInviteSettings, ContractCalendarConfig
from core.models import EmailSettings, MailConnection
from shifts.models import PlannedShift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,
)
class InvitePendingCountTests(TestCase):
    """A 20th→19th job, viewed in March: the send covers 20 Feb – 19 Mar."""

    def setUp(self):
        mail.outbox = []
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

        MailConnection.objects.create(name="Default", host="smtp.zink.nu",
                                      from_email="robot@zink.nu", is_default=True)
        es = EmailSettings.load()
        es.enabled = True
        es.save()
        s = CalendarInviteSettings.load()
        s.enabled = True
        s.save()

        self.wp = Workplace.objects.create(name="Offset", slug="offset")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract, effective_from=date(2030, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("200"), payroll_period_start_day=20,
        )
        ContractCalendarConfig.objects.create(
            contract=contract, send_invites=True, recipient="boss@work.example",
        )

    def _planned(self, day, month=3):
        return PlannedShift.objects.create(
            workplace=self.wp, date=date(2035, month, day),
            start_time=time(9, 0), end_time=time(17, 0),
        )

    def _pending(self):
        resp = self.client.get("/calendar/planning/?year=2035&month=3")
        self.assertEqual(resp.status_code, 200)
        return resp.context["invite_pending_count"]

    def test_counts_only_shifts_the_send_would_cover(self):
        self._planned(10)            # 20 Feb – 19 Mar → this month's send
        self._planned(25)            # 20 Mar – 19 Apr → next month's send
        self.assertEqual(self._pending(), 1)

    def test_all_in_period_sent_reads_as_none_pending(self):
        """The reported bug: with next period's shifts visible on the same grid,
        the button stayed on "Send invites" after the period was fully sent."""
        in_period = self._planned(10)
        self._planned(25)
        invites.activate(in_period)

        self.assertEqual(self._pending(), 0)

    def test_a_stale_invite_counts_as_pending(self):
        """Declining the post-edit re-send prompt must leave the month's button
        offering to fix it."""
        shift = self._planned(10)
        invites.activate(shift)
        self.assertEqual(self._pending(), 0)

        shift.refresh_from_db()
        shift.end_time = time(18, 0)
        shift.save()

        self.assertEqual(self._pending(), 1)

    def test_grid_shows_the_stale_marker(self):
        shift = self._planned(10)
        invites.activate(shift)
        shift.refresh_from_db()
        shift.start_time = time(7, 0)
        shift.save()

        html = self.client.get("/calendar/planning/?year=2035&month=3").content.decode()
        self.assertIn("shift-chip--invite-stale", html)

    def test_past_shifts_are_not_pending(self):
        """eligible() rejects a finished shift, so it must not keep the button lit."""
        from django.utils import timezone

        yesterday = timezone.localdate() - timedelta(days=1)
        PlannedShift.objects.create(
            workplace=self.wp, date=yesterday,
            start_time=time(9, 0), end_time=time(17, 0),
        )
        resp = self.client.get(
            f"/calendar/planning/?year={yesterday.year}&month={yesterday.month}"
        )
        self.assertEqual(resp.context["invite_pending_count"], 0)
