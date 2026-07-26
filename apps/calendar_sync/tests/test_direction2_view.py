"""Phase 2d — the "Send invites" endpoint: bulk-activate planned shifts, idempotent."""
from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from calendar_sync.models import (
    CalendarInviteSettings,
    ContractCalendarConfig,
    ShiftInvite,
)
from core.models import EmailSettings, MailConnection
from shifts.models import PlannedShift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SendInvitesEndpointTests(TestCase):
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
        s.enabled, s.send_to_personal, s.owner_address = True, True, "me@home.example"
        s.save()

        self.wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=contract, effective_from=date(2026, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY, hourly_rate=Decimal("200"),
        )
        ContractCalendarConfig.objects.create(
            contract=contract, send_invites=True, recipient="boss@work.example",
        )

    def _planned(self, day=15):
        # Future month — invites are future-only (eligible() rejects past shifts).
        return PlannedShift.objects.create(
            workplace=self.wp, date=date(2035, 3, day),
            start_time=time(9, 0), end_time=time(17, 0),
        )

    def _post(self):
        return self.client.post(
            "/calendar-sync/invites/send/?start=2035-03-01&end=2035-03-31"
        )

    def test_activates_planned_shifts_and_is_idempotent(self):
        shift = self._planned()

        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["activated"], 1)
        self.assertEqual(len(mail.outbox), 1)
        shift.refresh_from_db()
        self.assertIsNotNone(shift.invite_uid)
        self.assertTrue(
            ShiftInvite.objects.filter(
                invite_uid=shift.invite_uid, status=ShiftInvite.STATUS_ACTIVE
            ).exists()
        )

        # Second press: already synced → nothing new sent.
        resp2 = self._post()
        self.assertEqual(resp2.json()["activated"], 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_disabled_contract_activates_nothing(self):
        cfg = self.wp.contracts.first().calendar_config
        cfg.send_invites = False
        cfg.save()
        self._planned()
        resp = self._post()
        self.assertEqual(resp.json()["activated"], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_end_before_start_is_400(self):
        resp = self.client.post(
            "/calendar-sync/invites/send/?start=2035-03-31&end=2035-03-01"
        )
        self.assertEqual(resp.status_code, 400)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ShiftInviteEndpointTests(SendInvitesEndpointTests):
    """The per-shift Send / Re-send endpoint behind the edit-modal control."""

    def _invite(self, shift):
        return self.client.post(f"/calendar-sync/invites/shift/{shift.pk}/")

    def test_first_post_sends_and_second_resends(self):
        shift = self._planned()

        resp = self._invite(shift)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "sent")
        self.assertEqual(len(mail.outbox), 1)
        shift.refresh_from_db()
        invite = ShiftInvite.objects.get(invite_uid=shift.invite_uid)
        self.assertEqual(invite.sequence, 0)

        # Editing sends nothing on its own; re-sending is explicit.
        shift.end_time = time(18, 0)
        shift.save()
        self.assertEqual(len(mail.outbox), 1)

        resp2 = self._invite(shift)
        self.assertEqual(resp2.json()["action"], "resent")
        self.assertEqual(len(mail.outbox), 2)
        invite.refresh_from_db()
        self.assertEqual(invite.sequence, 1)  # bumped

    def test_ineligible_shift_is_400(self):
        cfg = self.wp.contracts.first().calendar_config
        cfg.send_invites = False
        cfg.save()
        shift = self._planned()
        resp = self._invite(shift)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_past_shift_is_400(self):
        past = PlannedShift.objects.create(
            workplace=self.wp, date=date(2020, 3, 15),
            start_time=time(9, 0), end_time=time(17, 0),
        )
        resp = self._invite(past)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
