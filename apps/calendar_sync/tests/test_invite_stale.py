"""Direction 2 — "this invite is out of date".

An invite is sent once and re-sent only on request, so an edited shift leaves its
recipients holding the old details. ``ShiftInvite.content_key`` records what the
last REQUEST actually carried; comparing it with the shift's current content is
what turns "something changed" into "the *invite* changed", so a notes-only edit
never nags. See ``invites.event_fingerprint`` / ``invites.is_stale``.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from calendar_sync import invites
from calendar_sync.models import (
    CalendarInviteSettings,
    ContractCalendarConfig,
    ShiftInvite,
)
from core.models import EmailSettings, MailConnection
from shifts.models import PlannedShift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,  # invite sends are queued — run them inline
)
class InviteStalenessTests(TestCase):
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
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)
        ContractTermSet.objects.create(
            contract=self.contract, effective_from=date(2026, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY,
            hourly_rate=Decimal("200"),
        )
        self.config = ContractCalendarConfig.objects.create(
            contract=self.contract, send_invites=True, recipient="boss@work.example",
        )

    def _planned(self, day=15):
        return PlannedShift.objects.create(
            workplace=self.wp, date=date(2035, 3, day),
            start_time=time(9, 0), end_time=time(17, 0),
        )

    def _sent(self, shift):
        """Activate *shift*'s invite and hand back the stored row."""
        invites.activate(shift)
        shift.refresh_from_db()
        return ShiftInvite.objects.get(invite_uid=shift.invite_uid)

    # ── the fingerprint itself ───────────────────────────────────────────────
    def test_fingerprint_tracks_what_the_invitee_sees(self):
        shift = self._planned()
        original = invites.event_fingerprint(shift)

        # Notes never reach the calendar entry — not a change.
        shift.notes = "remember the badge"
        self.assertEqual(invites.event_fingerprint(shift), original)

        # The end time does.
        shift.end_time = time(18, 0)
        self.assertNotEqual(invites.event_fingerprint(shift), original)

    def test_fingerprint_follows_the_resolved_title(self):
        """The 17-Aug case: the shift didn't change, the contract's title did.
        The invitee still ends up holding the wrong summary, so it counts."""
        shift = self._planned()
        original = invites.event_fingerprint(shift)

        self.config.override_title_onsite = True
        self.config.title_onsite = "Vagt hos {workplace}"
        self.config.save()

        self.assertNotEqual(invites.event_fingerprint(shift), original)

    # ── is_stale ─────────────────────────────────────────────────────────────
    def test_edit_after_send_is_stale_until_resent(self):
        shift = self._planned()
        invite = self._sent(shift)
        self.assertTrue(invite.content_key)
        self.assertFalse(invites.is_stale(shift))

        shift.start_time = time(10, 0)
        shift.save()
        self.assertTrue(invites.is_stale(shift))

        invites.resync(shift)
        self.assertFalse(invites.is_stale(shift))

    def test_notes_only_edit_is_not_stale(self):
        shift = self._planned()
        self._sent(shift)

        shift.notes = "bring the laptop"
        shift.save()

        self.assertFalse(invites.is_stale(shift))

    def test_invite_without_a_fingerprint_is_never_stale(self):
        """Invites sent before content_key existed record nothing, which is
        "unknown" — reading that as stale would light up every live invite on the
        upgrade and offer to re-send the lot."""
        shift = self._planned()
        invite = self._sent(shift)
        ShiftInvite.objects.filter(pk=invite.pk).update(content_key="")

        shift.start_time = time(10, 0)
        shift.save()

        self.assertFalse(invites.is_stale(shift))

    def test_backfill_stamps_invites_that_predate_the_field(self):
        """Without the backfill (run by migration 0004) an existing install sees
        nothing until its next send: every live invite reads as "unknown", so no
        edit ever prompts and the month's button never lights up."""
        shift = self._planned()
        invite = self._sent(shift)
        ShiftInvite.objects.filter(pk=invite.pk).update(content_key="")

        self.assertEqual(invites.backfill_content_keys(), 1)

        invite.refresh_from_db()
        self.assertEqual(invite.content_key, invites.event_fingerprint(shift))
        self.assertFalse(invites.is_stale(shift))  # asserts "matches as it stands"

        # …and from here on an edit is caught.
        shift.end_time = time(18, 0)
        shift.save()
        self.assertTrue(invites.is_stale(shift))

    def test_backfill_skips_orphans_and_already_stamped_invites(self):
        stamped = self._sent(self._planned(10))
        orphan = ShiftInvite.objects.create(workplace=self.wp)  # no shift owns it

        self.assertEqual(invites.backfill_content_keys(), 0)

        orphan.refresh_from_db()
        self.assertEqual(orphan.content_key, "")
        self.assertTrue(stamped.content_key)

    def test_past_shift_is_never_stale(self):
        shift = self._planned()
        self._sent(shift)
        # Move it into the past *and* change it: the invite system stops caring.
        PlannedShift.objects.filter(pk=shift.pk).update(
            date=timezone.localdate() - timedelta(days=3), start_time=time(10, 0),
        )
        shift.refresh_from_db()

        self.assertFalse(invites.is_stale(shift))

    def test_approved_shift_is_never_stale(self):
        """Approving with "Arrived early" rewrites the start time, so the invite
        no longer matches the row — but an approved shift records what happened,
        and correcting that record is not a change of plan to mail about. Dated
        in the future so it is the *approval* being tested, not ``_is_past``."""
        planned = self._planned()
        self._sent(planned)

        session = planned.approve()
        session.start_time = time(8, 30)  # "Arrived early"
        session.save()

        self.assertEqual(session.invite_uid, ShiftInvite.objects.get().invite_uid)
        self.assertFalse(invites.is_stale(session))

    def test_cancel_does_not_refresh_the_fingerprint(self):
        """Only a REQUEST re-states what the invitee holds. A CANCEL ends the
        series, so it must not quietly mark the invite as up to date."""
        shift = self._planned()
        invite = self._sent(shift)
        shift.start_time = time(10, 0)
        shift.save()

        invites.cancel(shift)

        invite.refresh_from_db()
        self.assertEqual(invite.status, ShiftInvite.STATUS_CANCELLED)
        self.assertNotEqual(invite.content_key, invites.event_fingerprint(shift))

    def test_resend_subject_says_update_not_invitation(self):
        """A re-send lands next to the original in the recipient's inbox — it has
        to read as an update to that shift, not a second invitation to it."""
        shift = self._planned()
        self._sent(shift)
        self.assertTrue(mail.outbox[-1].subject.startswith("Invitation: "))

        shift.end_time = time(18, 0)
        shift.save()
        invites.resync(shift)

        self.assertTrue(mail.outbox[-1].subject.startswith("Update: "))

        invites.cancel(shift)
        self.assertTrue(mail.outbox[-1].subject.startswith("Cancelled: "))

    # ── the API flag behind the re-send prompt ───────────────────────────────
    def test_update_api_reports_invite_stale(self):
        shift = self._planned()
        self._sent(shift)

        resp = self.client.post(
            f"/calendar/planning/shifts/{shift.pk}/",
            data='{"end_time": "18:00"}', content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["shift"]["invite_stale"])

    def test_update_api_reports_not_stale_for_an_invisible_change(self):
        shift = self._planned()
        self._sent(shift)

        resp = self.client.post(
            f"/calendar/planning/shifts/{shift.pk}/",
            data='{"notes": "park out back"}', content_type="application/json",
        )
        self.assertFalse(resp.json()["shift"]["invite_stale"])

    def test_session_api_never_reports_invite_stale(self):
        """The reported bug: an approved shift kept its invite_uid, so editing it
        answered ``invite_stale`` and the save popped the re-send prompt for a
        shift that had already been worked."""
        planned = self._planned()
        self._sent(planned)
        session = planned.approve()

        resp = self.client.post(
            f"/calendar/planning/sessions/{session.pk}/",
            data='{"end_time": "18:00"}', content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["shift"]["invite_stale"])

    # ── the bulk sweep picks up what the prompt was declined for ─────────────
    def test_send_invites_resends_stale_invites(self):
        shift = self._planned()
        self._sent(shift)
        self.assertEqual(len(mail.outbox), 1)

        shift.end_time = time(18, 0)
        shift.save()

        resp = self.client.post("/calendar-sync/invites/send/?year=2035&month=3")
        body = resp.json()
        self.assertEqual(body["activated"], 0)  # nothing new to activate
        self.assertEqual(body["resent"], 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertFalse(invites.is_stale(shift))

    def test_send_invites_leaves_a_current_invite_alone(self):
        shift = self._planned()
        self._sent(shift)

        resp = self.client.post("/calendar-sync/invites/send/?year=2035&month=3")
        body = resp.json()
        self.assertEqual((body["activated"], body["resent"]), (0, 0))
        self.assertEqual(len(mail.outbox), 1)
