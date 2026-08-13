"""Phase 2d — the "Send invites" endpoint: bulk-activate planned shifts, idempotent."""
import re
from datetime import date, time
from decimal import Decimal

from django.core import mail
from django.test import override_settings

from calendar_sync.models import (
    CalendarInviteSettings,
    ContractCalendarConfig,
    ShiftInvite,
)
from core.models import EmailSettings, MailConnection
from core.testing import LoggedInTestCase
from shifts.models import PlannedShift
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,  # invite sends are queued now — run them inline
)
class SendInvitesEndpointTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        mail.outbox = []

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
        return self.client.post("/calendar-sync/invites/send/?year=2035&month=3")

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

    def test_manual_per_shift_send_then_bulk_does_not_resend(self):
        """Repro: invite one shift from the edit modal, then hit bulk 'Send
        invites' for the month — the already-invited shift must NOT be re-sent."""
        shift = self._planned()
        r = self.client.post(
            f"/calendar-sync/invites/shift/{shift.pk}/",
            data="{}", content_type="application/json",
        )
        self.assertTrue(r.json()["ok"])
        self.assertEqual(len(mail.outbox), 1)  # manual REQUEST

        resp = self._post()
        self.assertEqual(resp.json()["activated"], 0)  # skipped, not re-activated
        self.assertEqual(len(mail.outbox), 1)          # no duplicate send

    def test_disabled_contract_activates_nothing(self):
        cfg = self.wp.contracts.first().calendar_config
        cfg.send_invites = False
        cfg.save()
        self._planned()
        resp = self._post()
        self.assertEqual(resp.json()["activated"], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_month_is_400(self):
        resp = self.client.post("/calendar-sync/invites/send/?year=2035&month=13")
        self.assertEqual(resp.status_code, 400)

    def test_only_shifts_in_the_months_period_are_sent(self):
        """A shift outside the viewed month's payroll period isn't swept in —
        even a whole month over, it's the next period's send, not this one."""
        self._planned(day=15)  # March 2035 — in period
        PlannedShift.objects.create(  # April 2035 — a different period
            workplace=self.wp, date=date(2035, 4, 15),
            start_time=time(9, 0), end_time=time(17, 0),
        )
        resp = self._post()  # year=2035&month=3
        self.assertEqual(resp.json()["activated"], 1)  # only the March shift
        self.assertEqual(len(mail.outbox), 1)

    def test_offset_period_next_period_shift_is_excluded(self):
        """The JKF case: a 20th→19th job's shift after the 20th belongs to the
        *next* payroll period, so viewing this month doesn't sweep it."""
        wp = Workplace.objects.create(name="Offset", slug="offset")
        c = WorkplaceContract.objects.create(workplace=wp)
        ContractTermSet.objects.create(
            contract=c, effective_from=date(2030, 1, 1),
            employment_type=ContractTermSet.EmploymentType.HOURLY, hourly_rate=Decimal("200"),
            payroll_period_start_day=20,
        )
        ContractCalendarConfig.objects.create(
            contract=c, send_invites=True, recipient="boss@offset.example",
        )
        # March period for a 20th-start job = Feb 20 – Mar 19.
        in_period = PlannedShift.objects.create(
            workplace=wp, date=date(2035, 3, 10),
            start_time=time(9, 0), end_time=time(17, 0),
        )
        next_period = PlannedShift.objects.create(
            workplace=wp, date=date(2035, 3, 25),  # belongs to April payroll
            start_time=time(9, 0), end_time=time(17, 0),
        )
        resp = self._post()  # year=2035&month=3
        self.assertEqual(resp.json()["activated"], 1)
        in_period.refresh_from_db()
        next_period.refresh_from_db()
        self.assertIsNotNone(in_period.invite_uid)   # sent
        self.assertIsNone(next_period.invite_uid)    # left for April


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,
)
class ChipInviteMarkerTests(SendInvitesEndpointTests):
    """The invite marker on a shift chip is a **planning** signal — "does this
    still need an invite?" — so it belongs to planned chips only, like the
    modal's invite control.

    The marker is the chip's **ring** (`shift-chip--invited`). It used to be an
    envelope icon as well, dropped when the chip ran out of width; the ring costs
    none. Either way the rule is the same, and it's the rule that broke: the icon
    sat outside the planned/approved branch of the template, so approval left it
    behind for good.

    ``PlannedShift.approve()`` deliberately carries ``invite_uid`` onto the new
    ``Shift`` (the event has to follow the approval instead of being orphaned),
    so ``has_active_invite`` stays true afterwards. That's correct data — only
    the chip should stop drawing it.
    """

    def _chip_tags(self):
        """Chip opening tags from the calendar cells only.

        Not the whole page: the help panel's shift legend now wears the very same
        ring classes on its sample swatches (so it can't drift from what the grid
        draws), which means a page-wide assertContains would pass whether or not
        any chip carries the marker.
        """
        resp = self.client.get("/calendar/planning/?year=2035&month=3")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        cells = re.findall(r"<td[^>]*data-date=\"[^\"]+\"(.*?)</td>", html, re.S)
        return re.findall(r'<div class="shift-chip [^>]*>', "".join(cells))

    def test_a_planned_chip_shows_the_marker_once_invited(self):
        self._planned()
        chips = self._chip_tags()
        self.assertEqual(len(chips), 1)
        self.assertNotIn("shift-chip--invited", chips[0])

        self._post()
        chips = self._chip_tags()
        self.assertEqual(len(chips), 1)
        self.assertIn("shift-chip--invited", chips[0])
        # The state's wording moved into the chip's tooltip when the icon went.
        self.assertIn("Calendar invite sent.", chips[0])

    def test_approving_an_invited_shift_drops_the_marker(self):
        shift = self._planned()
        self._post()
        shift.refresh_from_db()
        uid = shift.invite_uid
        self.assertIsNotNone(uid)

        approved = shift.approve()

        # The data is untouched on purpose — the uid moved to the Shift and the
        # invite is still active, because the invitee still holds the event.
        self.assertEqual(approved.invite_uid, uid)
        self.assertTrue(
            ShiftInvite.objects.filter(
                invite_uid=uid, status=ShiftInvite.STATUS_ACTIVE
            ).exists()
        )

        # Only the chip changes.
        chips = self._chip_tags()
        self.assertEqual(len(chips), 1)
        self.assertIn("shift-chip--approved", chips[0])
        self.assertNotIn("shift-chip--invited", chips[0])
        self.assertNotIn("Calendar invite sent.", chips[0])


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,
)
class SendInvitesPreviewTests(SendInvitesEndpointTests):
    """``GET`` on the send endpoint — what the confirm modal shows. It must
    describe the same plan the POST then performs, or the dialog promises sends
    that get skipped."""

    def _preview(self):
        return self.client.get("/calendar-sync/invites/send/?year=2035&month=3").json()

    def test_preview_names_the_workplace_counts_and_recipients(self):
        self._planned()
        data = self._preview()
        self.assertEqual(data["total"], 1)
        self.assertEqual((data["new"], data["updates"]), (1, 0))
        row = data["workplaces"][0]
        self.assertEqual(row["name"], "JKF")
        self.assertEqual(row["new"], 1)
        self.assertEqual(
            sorted(row["recipients"]), ["boss@work.example", "me@home.example"]
        )

    def test_preview_matches_what_the_post_actually_sends(self):
        self._planned(day=15)
        self._planned(day=16)
        promised = self._preview()["total"]
        result = self._post().json()
        self.assertEqual(promised, result["activated"] + result["resent"])
        # And afterwards there is nothing left to promise.
        self.assertEqual(self._preview()["total"], 0)

    def test_an_edited_shift_previews_as_an_update_not_a_new_invite(self):
        shift = self._planned()
        self._post()
        shift.refresh_from_db()  # the send stamped invite_uid on the DB row
        shift.end_time = time(18, 0)
        shift.save()
        data = self._preview()
        self.assertEqual((data["new"], data["updates"]), (0, 1))

    def test_a_contract_with_no_recipient_is_not_offered(self):
        """``activate`` refuses a shift with nowhere to send, so counting it would
        offer a send that quietly does nothing."""
        s = CalendarInviteSettings.load()
        s.send_to_personal = False
        s.save()
        cfg = self.wp.contracts.first().calendar_config
        cfg.send_to_work = False
        cfg.save()
        self._planned()
        self.assertEqual(self._preview()["total"], 0)

    def test_invalid_month_is_400(self):
        resp = self.client.get("/calendar-sync/invites/send/?year=2035&month=13")
        self.assertEqual(resp.status_code, 400)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SCHEDULER_TASK_EAGER=True,
)
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
