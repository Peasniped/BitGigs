"""The planning page's "Send invites" button state (``invite_pending_count``).

The button has to promise exactly what pressing it does. It used to count every
planned shift on the **grid**, which is padded out to whole weeks and to the union
of every workplace's payroll period — so with an offset (20th→19th) job it saw
next period's shifts and kept reading "Send invites" after everything the send
covers had already gone out. Pressing it again then sent nothing, silently.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.core import mail
from django.test import override_settings

from calendar_sync import invites
from calendar_sync.models import CalendarInviteSettings, ContractCalendarConfig
from core.models import EmailSettings, MailConnection
from core.testing import LoggedInTestCase
from shifts.models import PlannedShift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,
)
class InvitePendingCountTests(LoggedInTestCase):
    """A 20th→19th job, viewed in March: the send covers 20 Feb – 19 Mar."""

    def setUp(self):
        super().setUp()
        mail.outbox = []

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


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,
)
class NoRecipientTests(InvitePendingCountTests):
    """Invites armed at nobody.

    The reported bug: with the contract's work address switched off *and* the
    personal copy off, the button offered a send and then reported that no shifts
    were available. An invite with nowhere to go isn't one — the whole feature is
    effectively off, and the button must not appear at all.
    """

    def _config(self):
        return self.wp.contracts.first().calendar_config

    def _turn_off(self, *, work=True, personal=True):
        if work:
            cfg = self._config()
            cfg.send_to_work = False
            cfg.save()
        if personal:
            s = CalendarInviteSettings.load()
            s.send_to_personal = False
            s.save()

    def _can_send(self):
        resp = self.client.get("/calendar/planning/?year=2035&month=3")
        return resp.context["can_send_invites"]

    def test_the_button_is_not_offered_when_nothing_can_be_reached(self):
        self._planned(10)
        self.assertTrue(self._can_send())
        self._turn_off()
        self.assertFalse(self._can_send())
        self.assertFalse(invites.any_sendable_contract())

    def test_the_personal_copy_alone_keeps_it_on(self):
        """Not wanting to mail the employer is a normal setup — the shift still
        belongs in your own calendar."""
        s = CalendarInviteSettings.load()
        s.send_to_personal, s.owner_address = True, "me@home.example"
        s.save()
        self._turn_off(personal=False)   # work address off, personal still on
        self.assertTrue(invites.any_sendable_contract())
        self.assertTrue(self._can_send())

    def test_a_shift_with_nowhere_to_send_is_not_eligible(self):
        shift = self._planned(10)
        self.assertTrue(invites.eligible(shift))
        self._turn_off()
        self.assertFalse(invites.eligible(shift))
        self.assertEqual(self._pending(), 0)

    def test_the_work_address_alone_keeps_it_on(self):
        self._turn_off(work=False)       # personal off, work address still set
        self.assertTrue(invites.any_sendable_contract())
        self.assertTrue(self._can_send())
