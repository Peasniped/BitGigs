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
    ShiftInvite,
    WorkplaceCalendarConfig,
)
from core.models import EmailSettings
from shifts.models import PlannedShift, Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


def _configure():
    es = EmailSettings.load()
    es.enabled, es.host, es.from_email = True, "smtp.zink.nu", "robot@zink.nu"
    es.save()
    s = CalendarInviteSettings.load()
    s.enabled, s.owner_address = True, "me@home.example"
    s.save()


def _workplace():
    wp = Workplace.objects.create(name="JKF", slug="jkf")
    contract = WorkplaceContract.objects.create(workplace=wp)
    ContractTermSet.objects.create(
        contract=contract, effective_from=date(2026, 1, 1),
        employment_type=ContractTermSet.EmploymentType.HOURLY, hourly_rate=Decimal("200"),
    )
    WorkplaceCalendarConfig.objects.create(
        workplace=wp, send_invites=True, recipients="boss@work.example",
    )
    return wp


def _last_ics():
    ics = ""
    for _, content in mail.outbox[-1].alternatives:
        pass
    for name, content, mtype in mail.outbox[-1].attachments:
        if name == "invite.ics":
            ics = content.decode("utf-8") if isinstance(content, bytes) else content
    return ics


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SignalSyncTests(TestCase):
    def setUp(self):
        mail.outbox = []
        _configure()
        self.wp = _workplace()

    def _planned(self, **kw):
        return PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 3, 15),
            start_time=time(9, 0), end_time=time(17, 0), **kw,
        )

    def test_edit_resends_with_bumped_sequence(self):
        planned = self._planned()
        invite = invites.activate(planned)
        self.assertEqual(len(mail.outbox), 1)  # initial REQUEST, seq 0
        self.assertIn("SEQUENCE:0", _last_ics())

        planned.end_time = time(18, 0)
        planned.save()  # post_save → resync

        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("SEQUENCE:1", _last_ics())
        invite.refresh_from_db()
        self.assertEqual(invite.sequence, 1)

    def test_delete_sends_cancel_and_marks_cancelled(self):
        planned = self._planned()
        invite = invites.activate(planned)
        planned.delete()  # post_delete → cancel

        self.assertIn("METHOD:CANCEL", _last_ics())
        invite.refresh_from_db()
        self.assertEqual(invite.status, ShiftInvite.STATUS_CANCELLED)

    def test_approval_carries_invite_and_keeps_it_active(self):
        planned = self._planned()
        invites.activate(planned)
        uid = planned.invite_uid

        shift = planned.approve()

        # Same event identity moved to the Shift; invite still active.
        self.assertEqual(shift.invite_uid, uid)
        invite = ShiftInvite.objects.get(invite_uid=uid)
        self.assertEqual(invite.status, ShiftInvite.STATUS_ACTIVE)
        # Editing the approved Shift keeps syncing.
        n = len(mail.outbox)
        shift.start_time = time(8, 0)
        shift.save()
        self.assertEqual(len(mail.outbox), n + 1)

    def test_uninvited_shift_triggers_no_mail(self):
        self.wp.calendar_config.send_invites = False
        self.wp.calendar_config.save()
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

    def test_send_failure_does_not_block_save(self):
        planned = PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 3, 15),
            start_time=time(9, 0), end_time=time(17, 0),
        )
        invites.activate(planned)

        with mock.patch(
            "calendar_sync.invites._send_mail", side_effect=RuntimeError("smtp down")
        ):
            planned.end_time = time(20, 0)
            planned.save()  # must not raise despite the send blowing up

        planned.refresh_from_db()
        self.assertEqual(planned.end_time, time(20, 0))  # the edit persisted

    def test_delete_failure_does_not_block_delete(self):
        planned = PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 3, 15),
            start_time=time(9, 0), end_time=time(17, 0),
        )
        invites.activate(planned)
        pk = planned.pk

        with mock.patch(
            "calendar_sync.invites._send_mail", side_effect=RuntimeError("smtp down")
        ):
            planned.delete()  # must not raise

        self.assertFalse(PlannedShift.objects.filter(pk=pk).exists())
