"""Phase 2c — invites stay current via signals across every edit path, and a
mail failure never blocks the save/delete that triggered it."""
from datetime import date, time
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings

from calendar_sync import invites
from calendar_sync.models import (
    CalendarInviteSettings,
    ContractCalendarConfig,
    ShiftInvite,
)
from core.models import EmailSettings, MailConnection
from shifts.models import PlannedShift, Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


def _configure():
    MailConnection.objects.create(name="Default", host="smtp.zink.nu",
                                  from_email="robot@zink.nu", is_default=True)
    es = EmailSettings.load()
    es.enabled = True
    es.save()
    s = CalendarInviteSettings.load()
    s.enabled, s.send_to_personal, s.owner_address = True, True, "me@home.example"
    s.save()


def _workplace():
    wp = Workplace.objects.create(name="JKF", slug="jkf")
    contract = WorkplaceContract.objects.create(workplace=wp)
    ContractTermSet.objects.create(
        contract=contract, effective_from=date(2026, 1, 1),
        employment_type=ContractTermSet.EmploymentType.HOURLY, hourly_rate=Decimal("200"),
    )
    ContractCalendarConfig.objects.create(
        contract=contract, send_invites=True, recipient="boss@work.example",
    )
    return wp


def _cfg(wp):
    return wp.contracts.first().calendar_config


def _last_ics():
    ics = ""
    for _, content in mail.outbox[-1].alternatives:
        pass
    for name, content, mtype in mail.outbox[-1].attachments:
        if name == "invite.ics":
            ics = content.decode("utf-8") if isinstance(content, bytes) else content
    return ics


FUTURE = date(2035, 3, 15)   # invites are future-only; past shifts are ignored
PAST = date(2020, 3, 15)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SignalSyncTests(TestCase):
    def setUp(self):
        mail.outbox = []
        _configure()
        self.wp = _workplace()

    def _planned(self, day=FUTURE, **kw):
        return PlannedShift.objects.create(
            workplace=self.wp, date=day,
            start_time=time(9, 0), end_time=time(17, 0), **kw,
        )

    def test_edit_does_not_resend(self):
        """Invites send once — editing a synced shift no longer re-sends (that
        used to spam the recipient on every save)."""
        planned = self._planned()
        invite = invites.activate(planned)
        self.assertEqual(len(mail.outbox), 1)  # initial REQUEST only

        planned.end_time = time(18, 0)
        planned.save()  # no post_save resend anymore

        self.assertEqual(len(mail.outbox), 1)  # still just the one
        invite.refresh_from_db()
        self.assertEqual(invite.sequence, 0)

    def test_delete_sends_cancel_and_marks_cancelled(self):
        planned = self._planned()
        invite = invites.activate(planned)
        planned.delete()  # post_delete → cancel

        self.assertIn("METHOD:CANCEL", _last_ics())
        invite.refresh_from_db()
        self.assertEqual(invite.status, ShiftInvite.STATUS_CANCELLED)

    def test_past_shift_delete_sends_no_cancel(self):
        """A finished shift is out of scope — deleting it withdraws nothing."""
        planned = self._planned(day=PAST)
        invite = ShiftInvite.objects.create(
            workplace=self.wp, uid="bitgigs-shift-past@zink.nu",
            last_recipients="boss@work.example",
        )
        PlannedShift.objects.filter(pk=planned.pk).update(invite_uid=invite.invite_uid)
        planned.refresh_from_db()

        mail.outbox = []
        planned.delete()  # post_delete → cancel, but the shift is past → no send
        self.assertEqual(len(mail.outbox), 0)

    def test_approval_carries_invite_but_does_not_resend(self):
        planned = self._planned()
        invites.activate(planned)
        uid = planned.invite_uid
        n = len(mail.outbox)

        shift = planned.approve()

        # Same event identity moved to the Shift; invite still active; no re-send.
        self.assertEqual(shift.invite_uid, uid)
        invite = ShiftInvite.objects.get(invite_uid=uid)
        self.assertEqual(invite.status, ShiftInvite.STATUS_ACTIVE)
        self.assertEqual(len(mail.outbox), n)  # approval sent nothing extra

        shift.start_time = time(8, 0)
        shift.save()
        self.assertEqual(len(mail.outbox), n)  # editing the Shift sent nothing

    def test_uninvited_shift_triggers_no_mail(self):
        cfg = _cfg(self.wp); cfg.send_invites = False; cfg.save()
        planned = self._planned()
        planned.end_time = time(19, 0)
        planned.save()
        planned.delete()
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SignalFailSoftTests(TestCase):
    def setUp(self):
        mail.outbox = []
        _configure()
        self.wp = _workplace()

    def test_delete_failure_does_not_block_delete(self):
        planned = PlannedShift.objects.create(
            workplace=self.wp, date=FUTURE,
            start_time=time(9, 0), end_time=time(17, 0),
        )
        invites.activate(planned)
        pk = planned.pk

        with mock.patch(
            "calendar_sync.invites._send_mail", side_effect=RuntimeError("smtp down")
        ):
            planned.delete()  # must not raise

        self.assertFalse(PlannedShift.objects.filter(pk=pk).exists())
