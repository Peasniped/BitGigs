"""Phase 2b — Direction 2 send service: build the invite .ics, eligibility
gating, recipients, the SMTP attachment path, and EmailLog logging."""
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
from core.models import EmailLog, EmailSettings
from shifts.models import Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


def _configure_mail():
    es = EmailSettings.load()
    es.enabled = True
    es.host = "smtp.zink.nu"
    es.from_email = "robot@zink.nu"
    es.from_name = "BitGigs"
    es.save()
    return es


def _configure_invites(owner="me@home.example"):
    s = CalendarInviteSettings.load()
    s.enabled = True
    s.owner_address = owner
    s.save()
    return s


def _workplace_with_config(send_invites=True, recipients="boss@work.example"):
    wp = Workplace.objects.create(name="JKF", slug="jkf")
    contract = WorkplaceContract.objects.create(workplace=wp)
    ContractTermSet.objects.create(
        contract=contract, effective_from=date(2026, 1, 1),
        employment_type=ContractTermSet.EmploymentType.HOURLY, hourly_rate=Decimal("200"),
    )
    WorkplaceCalendarConfig.objects.create(
        workplace=wp, send_invites=send_invites, recipients=recipients,
    )
    return wp


def _shift(wp, shift_type="on_site"):
    return Shift.objects.create(
        workplace=wp, date=date(2026, 3, 15),
        start_time=time(9, 0), end_time=time(17, 0), shift_type=shift_type,
    )


class EligibilityTests(TestCase):
    def setUp(self):
        _configure_mail()
        _configure_invites()
        self.wp = _workplace_with_config()

    def test_eligible_when_all_switches_on(self):
        self.assertTrue(invites.eligible(_shift(self.wp)))

    def test_blocked_by_master_switch(self):
        s = CalendarInviteSettings.load(); s.enabled = False; s.save()
        self.assertFalse(invites.eligible(_shift(self.wp)))

    def test_blocked_by_workplace_switch(self):
        self.wp.calendar_config.send_invites = False
        self.wp.calendar_config.save()
        self.assertFalse(invites.eligible(_shift(self.wp)))

    def test_blocked_for_non_inviteable_type(self):
        self.assertFalse(invites.eligible(_shift(self.wp, shift_type="vacation")))

    def test_blocked_when_mail_not_configured(self):
        es = EmailSettings.load(); es.enabled = False; es.save()
        self.assertFalse(invites.eligible(_shift(self.wp)))

    def test_recipients_include_owner_and_dedupe(self):
        s = CalendarInviteSettings.load(); s.owner_address = "boss@work.example"; s.save()
        # owner duplicates the work address → one entry
        self.assertEqual(invites.recipients_for(_shift(self.wp)), ["boss@work.example"])


class BuildInviteTests(TestCase):
    def setUp(self):
        _configure_mail()
        _configure_invites(owner="me@home.example")
        self.wp = _workplace_with_config(recipients="boss@work.example")

    def _ics(self, shift_type="on_site", method="REQUEST", status="CONFIRMED", seq=0):
        shift = _shift(self.wp, shift_type)
        invite = ShiftInvite.objects.create(
            workplace=self.wp, uid="bitgigs-shift-abc@zink.nu", sequence=seq,
            last_recipients="boss@work.example, me@home.example",
        )
        return invites.build_invite_calendar(
            shift, invite, method=method, status=status
        ).decode("utf-8")

    def test_request_has_method_uid_sequence_and_utc_times(self):
        ics = self._ics(seq=2)
        self.assertIn("METHOD:REQUEST", ics)
        self.assertIn("UID:bitgigs-shift-abc@zink.nu", ics)
        self.assertIn("SEQUENCE:2", ics)
        # 09:00 Europe/Copenhagen in March (CET, +01) → 08:00Z
        self.assertIn("DTSTART:20260315T080000Z", ics)

    def test_title_and_location_by_type(self):
        onsite = self._ics(shift_type="on_site")
        self.assertIn("SUMMARY:På arbejde hos JKF", onsite)
        self.assertIn("LOCATION:JKF", onsite)  # on-site falls back to workplace name
        remote = self._ics(shift_type="remote")
        self.assertIn("SUMMARY:Arbejder hjemme\\, JKF", remote)  # comma escaped per RFC

    def test_organizer_and_attendees(self):
        ics = self._ics()
        self.assertIn("ORGANIZER", ics)
        self.assertIn("robot@zink.nu", ics)          # organizer address
        self.assertIn("boss@work.example", ics)      # work recipient
        self.assertIn("me@home.example", ics)        # owner's own address

    def test_cancel_addresses_last_recipients(self):
        ics = self._ics(method="CANCEL", status="CANCELLED")
        self.assertIn("METHOD:CANCEL", ics)
        self.assertIn("boss@work.example", ics)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ActivateSendTests(TestCase):
    def setUp(self):
        mail.outbox = []
        _configure_mail()
        _configure_invites(owner="me@home.example")
        self.wp = _workplace_with_config(recipients="boss@work.example")

    def test_activate_sends_message_with_ics(self):
        shift = _shift(self.wp)
        invite = invites.activate(shift)

        self.assertIsNotNone(invite)
        self.assertTrue(invite.is_active)
        self.assertTrue(invite.uid.startswith("bitgigs-shift-"))
        shift.refresh_from_db()
        self.assertIsNotNone(shift.invite_uid)

        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(sorted(msg.to), ["boss@work.example", "me@home.example"])
        self.assertIn("robot@zink.nu", msg.from_email)
        # a text/calendar alternative + a .ics file attachment
        self.assertTrue(any("text/calendar" in mt for _, mt in msg.alternatives))
        self.assertTrue(any(name == "invite.ics" for name, _, _ in msg.attachments))

    def test_ineligible_shift_sends_nothing(self):
        self.wp.calendar_config.send_invites = False
        self.wp.calendar_config.save()
        self.assertIsNone(invites.activate(_shift(self.wp)))
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND="core.mail_backend.DbConfiguredEmailBackend")
class InviteEmailLogTests(TestCase):
    """Routing through the default backend (DbConfiguredEmailBackend) writes an
    EmailLog row — the same trail every other message leaves. Django's test
    runner swaps EMAIL_BACKEND to locmem, so restore the real one here (with the
    SMTP transport patched out) to exercise the logging path."""

    def setUp(self):
        _configure_mail()
        _configure_invites()
        self.wp = _workplace_with_config()

    def test_send_is_logged(self):
        shift = _shift(self.wp)
        with mock.patch(
            "django.core.mail.backends.smtp.EmailBackend.send_messages",
            return_value=1,
        ):
            invite = invites.activate(shift)
        self.assertIsNotNone(invite.sent_at)
        row = EmailLog.objects.filter(kind=EmailLog.KIND_SENT).first()
        self.assertIsNotNone(row)
        self.assertTrue(row.ok)
        self.assertIn("boss@work.example", row.to)
