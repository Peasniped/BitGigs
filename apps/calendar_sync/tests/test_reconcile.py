"""Direction 2 — reconciliation: reverse lookup, drift diff, the explicit sync
migration, and the self-withdrawing test invite."""
from datetime import date, time
from decimal import Decimal

from django.core import mail
from django.test import TestCase, override_settings

from calendar_sync import invites, reconcile
from calendar_sync.models import (
    CalendarInviteSettings,
    ContractCalendarConfig,
    ShiftInvite,
)
from core.models import EmailSettings, MailConnection
from core.testing import LoggedInTestCase
from shifts.models import PlannedShift, Shift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


def _configure_mail(enabled=True):
    MailConnection.objects.create(
        name="Default", host="smtp.zink.nu", from_email="robot@zink.nu",
        from_name="BitGigs", is_default=True,
    )
    es = EmailSettings.load()
    es.enabled = enabled
    es.save()
    return es


def _configure_invites(enabled=True, owner="me@home.example", personal=True):
    s = CalendarInviteSettings.load()
    s.enabled = enabled
    s.send_to_personal = personal
    s.owner_address = owner
    s.save()
    return s


def _workplace_with_config(send_invites=True, recipient="boss@work.example"):
    wp = Workplace.objects.create(name="JKF", slug="jkf")
    contract = WorkplaceContract.objects.create(workplace=wp)
    ContractTermSet.objects.create(
        contract=contract, effective_from=date(2026, 1, 1),
        employment_type=ContractTermSet.EmploymentType.HOURLY, hourly_rate=Decimal("200"),
    )
    ContractCalendarConfig.objects.create(
        contract=contract, send_invites=send_invites, recipient=recipient,
    )
    return wp


def _cfg(wp):
    return wp.contracts.first().calendar_config


FUTURE = date(2035, 3, 15)   # invites are future-only
PAST = date(2020, 3, 15)


def _shift(wp, shift_type="on_site", day=FUTURE):
    return Shift.objects.create(
        workplace=wp, date=day,
        start_time=time(9, 0), end_time=time(17, 0), shift_type=shift_type,
    )


def _link_active_invite(wp, shift, last_recipients):
    """An active ShiftInvite tied to *shift*, pre-seeded with who it was last
    sent to. The uid is attached with ``.update()`` so the post_save resync
    signal (which would overwrite last_recipients) never fires during setup."""
    invite = ShiftInvite.objects.create(
        workplace=wp, uid="bitgigs-shift-abc@zink.nu",
        last_recipients=last_recipients, status=ShiftInvite.STATUS_ACTIVE,
    )
    type(shift).objects.filter(pk=shift.pk).update(invite_uid=invite.invite_uid)
    shift.refresh_from_db()
    return invite


class ShiftLookupTests(TestCase):
    def setUp(self):
        self.wp = _workplace_with_config()

    def test_finds_planned_shift(self):
        invite = ShiftInvite.objects.create(workplace=self.wp)
        planned = PlannedShift.objects.create(
            workplace=self.wp, date=date(2026, 3, 15),
            start_time=time(9, 0), end_time=time(17, 0),
        )
        PlannedShift.objects.filter(pk=planned.pk).update(invite_uid=invite.invite_uid)
        found = reconcile.shift_for_invite(invite)
        self.assertIsInstance(found, PlannedShift)
        self.assertEqual(found.pk, planned.pk)

    def test_prefers_shift_after_approval(self):
        invite = ShiftInvite.objects.create(workplace=self.wp)
        shift = _shift(self.wp)
        Shift.objects.filter(pk=shift.pk).update(invite_uid=invite.invite_uid)
        found = reconcile.shift_for_invite(invite)
        self.assertIsInstance(found, Shift)
        self.assertEqual(found.pk, shift.pk)

    def test_none_when_orphaned(self):
        invite = ShiftInvite.objects.create(workplace=self.wp)
        self.assertIsNone(reconcile.shift_for_invite(invite))


class DriftDiffTests(TestCase):
    def setUp(self):
        _configure_mail()
        _configure_invites(owner="me@home.example")
        self.wp = _workplace_with_config(recipient="boss@work.example")

    def test_recipient_change_shows_added_and_removed(self):
        shift = _shift(self.wp)
        invite = _link_active_invite(
            self.wp, shift, "oldboss@work.example, me@home.example"
        )
        drift = reconcile.invite_drift(invite)
        self.assertIsNotNone(drift)
        self.assertEqual(drift.added, ["boss@work.example"])
        self.assertEqual(drift.removed, ["oldboss@work.example"])

    def test_identical_sets_are_not_drift(self):
        shift = _shift(self.wp)
        invite = _link_active_invite(
            self.wp, shift, "boss@work.example, me@home.example"
        )
        self.assertIsNone(reconcile.invite_drift(invite))

    def test_case_insensitive_no_drift(self):
        shift = _shift(self.wp)
        invite = _link_active_invite(
            self.wp, shift, "BOSS@work.example, Me@Home.Example"
        )
        self.assertIsNone(reconcile.invite_drift(invite))

    def test_personal_address_change_drifts_every_invite(self):
        shift = _shift(self.wp)
        invite = _link_active_invite(
            self.wp, shift, "boss@work.example, old-me@home.example"
        )
        drift = reconcile.invite_drift(invite)
        self.assertIsNotNone(drift)
        self.assertIn("me@home.example", drift.added)
        self.assertIn("old-me@home.example", drift.removed)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,  # invite sends are queued now — run them inline
)
class SyncMigrationTests(TestCase):
    def setUp(self):
        mail.outbox = []
        _configure_mail()
        _configure_invites(owner="me@home.example")
        self.wp = _workplace_with_config(recipient="boss@work.example")

    def test_move_cancels_old_and_requests_new(self):
        shift = _shift(self.wp)
        invite = _link_active_invite(
            self.wp, shift, "oldboss@work.example, me@home.example"
        )
        counts = reconcile.sync_all()
        self.assertEqual(counts["moved"], 1)
        self.assertEqual(len(mail.outbox), 2)

        cancel, request = mail.outbox[0], mail.outbox[1]
        # CANCEL goes only to the dropped address…
        self.assertEqual(cancel.to, ["oldboss@work.example"])
        self.assertIn("METHOD:CANCEL", cancel.alternatives[0][0])
        # …the REQUEST to the current full set.
        self.assertEqual(sorted(request.to), ["boss@work.example", "me@home.example"])
        self.assertIn("METHOD:REQUEST", request.alternatives[0][0])

        invite.refresh_from_db()
        self.assertTrue(invite.is_active)
        self.assertEqual(
            reconcile.parse_addresses(invite.last_recipients),
            ["boss@work.example", "me@home.example"],
        )

    def test_contract_opt_out_withdraws(self):
        shift = _shift(self.wp)
        invite = _link_active_invite(self.wp, shift, "boss@work.example, me@home.example")
        cfg = _cfg(self.wp); cfg.send_invites = False; cfg.save()

        counts = reconcile.sync_all()
        self.assertEqual(counts["withdrawn"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("METHOD:CANCEL", mail.outbox[0].alternatives[0][0])
        invite.refresh_from_db()
        self.assertEqual(invite.status, ShiftInvite.STATUS_CANCELLED)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class FootgunGuardTests(TestCase):
    def setUp(self):
        mail.outbox = []
        self.wp = _workplace_with_config(recipient="boss@work.example")

    def _drifted_invite(self):
        shift = _shift(self.wp)
        return _link_active_invite(self.wp, shift, "oldboss@work.example")

    def test_master_arm_off_is_no_drift_and_noop(self):
        _configure_mail()
        _configure_invites(enabled=False)
        self._drifted_invite()
        self.assertEqual(reconcile.drift_details(), [])
        self.assertEqual(reconcile.sync_all(),
                         {"moved": 0, "withdrawn": 0, "failed": 0})
        self.assertEqual(len(mail.outbox), 0)

    def test_mail_unconfigured_is_no_drift(self):
        _configure_mail(enabled=False)
        _configure_invites(enabled=True)
        self._drifted_invite()
        self.assertEqual(reconcile.drift_details(), [])
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SyncViewTests(LoggedInTestCase):
    """The review modal drives the sync over fetch and renders its own status, so
    the endpoint answers JSON on an XHR (rather than the redirect + flash a plain
    POST gets)."""

    def setUp(self):
        super().setUp()
        mail.outbox = []
        _configure_mail()
        _configure_invites(owner="me@home.example")
        self.wp = _workplace_with_config(recipient="boss@work.example")

    def test_ajax_sync_returns_json_counts(self):
        shift = _shift(self.wp)
        _link_active_invite(self.wp, shift, "oldboss@work.example, me@home.example")
        resp = self.client.post(
            "/calendar-sync/invites/sync/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")
        self.assertEqual(resp.json(), {"moved": 1, "withdrawn": 0, "failed": 0})

    def test_plain_post_redirects(self):
        resp = self.client.post("/calendar-sync/invites/sync/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("tab=calendar", resp["Location"])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TestInviteWithdrawTests(TestCase):
    def setUp(self):
        mail.outbox = []
        _configure_mail()
        _configure_invites()

    def test_test_invite_sends_request_then_cancel_same_uid(self):
        ok, error = invites.send_test_invite("me@home.example")
        self.assertTrue(ok, error)
        self.assertEqual(len(mail.outbox), 2)

        req_ics = mail.outbox[0].alternatives[0][0]
        cancel_ics = mail.outbox[1].alternatives[0][0]
        self.assertIn("METHOD:REQUEST", req_ics)
        self.assertIn("METHOD:CANCEL", cancel_ics)

        # Same UID so the CANCEL withdraws the very event the REQUEST created.
        def _uid(ics):
            for line in ics.splitlines():
                if line.startswith("UID:"):
                    return line[4:]
            return None
        self.assertEqual(_uid(req_ics), _uid(cancel_ics))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class FutureOnlyTests(TestCase):
    """The invite system ignores shifts whose day has passed."""

    def setUp(self):
        mail.outbox = []
        _configure_mail()
        _configure_invites(owner="me@home.example")
        self.wp = _workplace_with_config(recipient="boss@work.example")

    def test_past_shift_not_eligible(self):
        self.assertTrue(invites.eligible(_shift(self.wp, day=FUTURE)))
        self.assertFalse(invites.eligible(_shift(self.wp, day=PAST)))

    def test_past_shift_never_drifts(self):
        shift = _shift(self.wp, day=PAST)
        invite = _link_active_invite(self.wp, shift, "oldboss@work.example")
        self.assertIsNone(reconcile.invite_drift(invite))
        self.assertEqual(reconcile.drift_details(), [])


class GroupedDriftTests(TestCase):
    """drift_details collapses identical changes across many shifts into one row."""

    def setUp(self):
        _configure_mail()
        _configure_invites(owner="me@home.example")
        self.wp = _workplace_with_config(recipient="boss@work.example")

    def test_same_change_groups_with_sorted_dates(self):
        s1 = _shift(self.wp, day=date(2035, 3, 20))
        s2 = _shift(self.wp, day=date(2035, 3, 5))
        _link_active_invite(self.wp, s1, "oldboss@work.example, me@home.example")
        _link_active_invite(self.wp, s2, "oldboss@work.example, me@home.example")

        groups = reconcile.drift_details()
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["count"], 2)
        self.assertEqual(group["removed"], ["oldboss@work.example"])
        self.assertEqual(group["added"], ["boss@work.example"])
        self.assertEqual(group["dates"], [date(2035, 3, 5), date(2035, 3, 20)])
