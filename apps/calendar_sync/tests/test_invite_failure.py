"""Direction 2 — a send that was **rejected**.

Invites are queued, so "handed to the scheduler" is not "delivered": a message
the mail server refuses (a bad address, or a host rate limit) used to leave the
shift wearing an "invite sent" marker and be skipped by every later sweep, for an
email nobody ever received. The outcome is now written back onto the
``ShiftInvite`` — and clearing the failed row on Settings → Jobs is what dismisses
it, which means something different depending on whether anything was ever
delivered. See ``invites.mark_send_failed`` / ``invites.clear_send_failure``.
"""
from datetime import date, time
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from calendar_sync import invites
from calendar_sync.models import (
    CalendarInviteSettings,
    ContractCalendarConfig,
    ShiftInvite,
)
from core.models import EmailLog, EmailSettings, MailConnection
from scheduler.models import ScheduledTask
from shifts.models import PlannedShift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


class Rejected(Exception):
    """Stands in for the SMTPDataError a rate limit or bad address produces."""


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,  # invite sends are queued — run them inline
)
class InviteSendFailureTests(TestCase):
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

    # ── helpers ──────────────────────────────────────────────────────────────
    def _planned(self, day=15):
        return PlannedShift.objects.create(
            workplace=self.wp, date=date(2035, 3, day),
            start_time=time(9, 0), end_time=time(17, 0),
        )

    def _invite(self, shift):
        shift.refresh_from_db()
        return ShiftInvite.objects.filter(invite_uid=shift.invite_uid).first()

    def _failing(self):
        """Every SMTP send inside this context is rejected."""
        return mock.patch.object(
            invites, "_send_mail_now", side_effect=Rejected("451 rate limited")
        )

    def _clear_failed(self):
        return self.client.post(reverse("scheduler:tasks-clear"), {"scope": "failed"})

    # ── the failure is recorded, not assumed away ────────────────────────────
    def test_rejected_first_send_is_marked_and_claims_no_delivery(self):
        shift = self._planned()
        with self._failing():
            invites.activate(shift)

        invite = self._invite(shift)
        self.assertTrue(invite.send_failed)
        self.assertIn("451 rate limited", invite.send_error)
        self.assertIsNone(invite.delivered_at)
        # Nothing was delivered, so nothing out there matches this shift.
        self.assertEqual(invite.content_key, "")
        # And the queue row carries the reason, which is where the owner sees it.
        task = ScheduledTask.objects.get(task="calendar.send_invite_mail")
        self.assertEqual(task.status, ScheduledTask.FAILED)
        self.assertIn("451 rate limited", task.last_error)

    def test_successful_send_records_delivery(self):
        shift = self._planned()
        invites.activate(shift)

        invite = self._invite(shift)
        self.assertFalse(invite.send_failed)
        self.assertIsNotNone(invite.delivered_at)
        self.assertTrue(invite.content_key)

    def test_rejected_update_keeps_what_the_invitee_actually_holds(self):
        """A failed *re-send* is not "never invited" — they hold the old event."""
        shift = self._planned()
        invites.activate(shift)
        delivered_key = self._invite(shift).content_key

        shift.start_time = time(10, 0)
        shift.save()
        with self._failing():
            invites.resync(shift)

        invite = self._invite(shift)
        self.assertTrue(invite.send_failed)
        # The fingerprint rolled back to the delivered version, so the shift
        # reads as out of date rather than as carrying the new times.
        self.assertEqual(invite.content_key, delivered_key)
        self.assertTrue(invites.is_stale(shift))

    # ── a failed invite is sendable again ────────────────────────────────────
    def test_failed_invite_needs_sending_again(self):
        shift = self._planned()
        with self._failing():
            invites.activate(shift)
        self.assertTrue(invites.needs_send(shift))

    def test_retry_of_a_never_delivered_invite_is_not_an_update(self):
        """SEQUENCE > 0 tells the client "you already have this" — wrong when the
        first send never left, and the subject would read "Update:" for an
        invitation nobody received."""
        shift = self._planned()
        with self._failing():
            invites.activate(shift)

        invites.resync(shift)  # the retry, this time succeeding
        invite = self._invite(shift)
        self.assertEqual(invite.sequence, 0)
        self.assertFalse(invite.send_failed)
        self.assertIsNotNone(invite.delivered_at)
        self.assertTrue(mail.outbox[-1].subject.startswith("Invitation:"))

    def test_retry_after_a_delivered_send_is_an_update(self):
        shift = self._planned()
        invites.activate(shift)
        shift.start_time = time(10, 0)
        shift.save()
        invites.resync(shift)

        self.assertEqual(self._invite(shift).sequence, 1)
        self.assertTrue(mail.outbox[-1].subject.startswith("Update:"))

    def test_a_retry_is_labelled_as_one_in_the_queue(self):
        shift = self._planned()
        with self._failing():
            invites.activate(shift)
        invites.resync(shift)

        labels = [t.label for t in ScheduledTask.objects.order_by("id")]
        self.assertEqual(labels, ["Send calendar invite", "Send calendar invite (retry)"])

    def test_per_shift_endpoint_retries_a_failed_invite(self):
        shift = self._planned()
        with self._failing():
            invites.activate(shift)

        resp = self.client.post(reverse("calendar_sync:invite-shift", args=[shift.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertFalse(self._invite(shift).send_failed)

    # ── clearing the failed row is the dismissal ─────────────────────────────
    def test_clearing_a_failed_first_send_returns_the_shift_to_not_invited(self):
        shift = self._planned()
        with self._failing():
            invites.activate(shift)

        self._clear_failed()
        self.assertIsNone(self._invite(shift))  # nobody holds it → drop the row
        self.assertFalse(ScheduledTask.objects.exists())

    def test_clearing_a_failed_update_keeps_the_invite_and_leaves_it_stale(self):
        shift = self._planned()
        invites.activate(shift)
        shift.start_time = time(10, 0)
        shift.save()
        with self._failing():
            invites.resync(shift)

        self._clear_failed()
        invite = self._invite(shift)
        self.assertIsNotNone(invite)  # they hold the old event — never drop it
        self.assertFalse(invite.send_failed)
        self.assertTrue(invites.is_stale(shift))

    # ── a withdrawal that failed ─────────────────────────────────────────────
    #
    # Deleting a shift is a local fact — it never "comes back" because the CANCEL
    # bounced. What breaks is the *invitee*, who keeps an event for a shift that no
    # longer exists, and who has no chip, modal or sweep left to fix it: the shift
    # the app would hang a retry off is gone. The queue row's Retry button is the
    # whole answer, which is why it must survive the shift.
    def test_a_failed_cancel_leaves_a_retryable_row_after_the_shift_is_gone(self):
        shift = self._planned()
        invites.activate(shift)
        self.assertEqual(len(mail.outbox), 1)

        with self._failing():
            shift.delete()  # post_delete → CANCEL

        self.assertFalse(PlannedShift.objects.exists())  # deletion is unconditional
        failed = ScheduledTask.objects.filter(status=ScheduledTask.FAILED).get()
        self.assertEqual(failed.payload["method"], "CANCEL")

        # Retry re-queues the same withdrawal, and this time it goes out.
        resp = self.client.post(reverse("scheduler:task-retry"), {"id": failed.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ScheduledTask.objects.filter(pk=failed.pk).exists())
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(mail.outbox[1].subject.startswith("Cancelled:"))
        self.assertEqual(
            ScheduledTask.objects.filter(status=ScheduledTask.FAILED).count(), 0
        )

    def test_clearing_done_tasks_leaves_invites_alone(self):
        shift = self._planned()
        invites.activate(shift)

        self.client.post(reverse("scheduler:tasks-clear"), {"scope": "done"})
        invite = self._invite(shift)
        self.assertIsNotNone(invite)
        self.assertIsNotNone(invite.delivered_at)

    # ── the circuit breaker ──────────────────────────────────────────────────
    #
    # These run against the **real** mail backend with SMTP itself refusing, so
    # the EmailLog rows the breaker reads are written by the code that really
    # writes them — the streak is derived state, and faking it would test
    # nothing.
    @override_settings(
        SCHEDULER_TASK_EAGER=False,  # we want a real pending queue to drain
        EMAIL_BACKEND="core.mail_backend.DbConfiguredEmailBackend",
    )
    def test_the_breaker_stops_the_batch_after_three_refusals(self):
        """One press queues a month of invites; if the server is refusing them,
        the rest have nothing to gain by asking."""
        from scheduler import services

        shifts = [self._planned(day) for day in range(1, 7)]  # six queued sends
        for shift in shifts:
            invites.activate(shift)

        with mock.patch(
            "django.core.mail.backends.smtp.EmailBackend.send_messages",
            side_effect=Rejected("451 rate limited"),
        ) as smtp:
            services.run_pending_tasks()

        # Three messages were put on the wire, not six.
        self.assertEqual(smtp.call_count, 3)
        self.assertEqual(EmailLog.objects.filter(ok=False).count(), 3)

        errors = list(
            ScheduledTask.objects.order_by("id").values_list("last_error", flat=True)
        )
        self.assertEqual(len(errors), 6)
        self.assertTrue(all("451 rate limited" in e for e in errors[:3]))
        self.assertTrue(all("Skipped —" in e for e in errors[3:]))
        # The shift itself gets the plain reason, without the exception class the
        # queue row keeps.
        self.assertTrue(self._invite(shifts[-1]).send_error.startswith("Skipped —"))

        # Every shift in the batch reads as a failed invite either way — nobody
        # got one — so the whole lot clears in one press and re-sends in one.
        for shift in shifts:
            invite = self._invite(shift)
            self.assertTrue(invite.send_failed)
            self.assertIsNone(invite.delivered_at)
            self.assertTrue(invites.needs_send(shift))

    @override_settings(
        SCHEDULER_TASK_EAGER=False,
        EMAIL_BACKEND="core.mail_backend.DbConfiguredEmailBackend",
    )
    def test_two_refusals_are_not_a_broken_connection(self):
        """One rejected address doesn't stop the queue — the threshold is three."""
        from scheduler import services

        for day in (1, 2):
            invites.activate(self._planned(day))

        with mock.patch(
            "django.core.mail.backends.smtp.EmailBackend.send_messages",
            side_effect=Rejected("550 no such user"),
        ) as smtp:
            services.run_pending_tasks()

        self.assertEqual(smtp.call_count, 2)  # both were still attempted

    def test_a_send_queued_after_the_failures_is_still_attempted(self):
        """The breaker must not block the retry that could clear it: only a
        success breaks a streak, so a message queued *after* the failures — one
        somebody asked for knowing they happened — always goes."""
        for _ in range(3):
            EmailLog.record(to="boss@work.example", subject="Invitation: x",
                            ok=False, connection_name="Default")

        shift = self._planned()
        invites.activate(shift)  # eager: runs inline against locmem, i.e. sends

        self.assertIsNotNone(self._invite(shift).delivered_at)

    # ── what the UI reads ────────────────────────────────────────────────────
    def test_chip_flags_report_the_failure(self):
        from calendar_view.views import _shift_invite_flags

        shift = self._planned()
        with self._failing():
            invites.activate(shift)

        flags = _shift_invite_flags(PlannedShift.objects.get(pk=shift.pk))
        self.assertTrue(flags["has_active_invite"])
        self.assertTrue(flags["invite_failed"])
        self.assertFalse(flags["invite_delivered"])
        self.assertIn("451 rate limited", flags["invite_error"])
