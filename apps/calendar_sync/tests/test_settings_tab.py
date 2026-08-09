"""Phase 3 — Settings → Calendar tab: subscriptions CRUD + test, invite
settings, per-workplace config, and the test-invite button."""
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from calendar_sync.models import (
    CalendarInviteSettings,
    CalendarSubscription,
    ContractCalendarConfig,
)
from calendar_sync.services import build_calendar, build_event
from core.models import EmailSettings, MailConnection
from workplaces.models import Workplace, WorkplaceContract


class CalendarTabBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()


class TabRenderTests(CalendarTabBase):
    def test_calendar_tab_renders(self):
        resp = self.client.get("/settings/?tab=calendar")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Calendars you read")
        self.assertContains(resp, "Invites you send")


class SubscriptionCrudTests(CalendarTabBase):
    def test_create_requires_url_then_saves_encrypted(self):
        # Missing URL on create → no row, error re-render.
        resp = self.client.post("/calendar-sync/subscriptions/save/", {
            "label": "Personal", "url": "", "color": "#3366ff", "enabled": "on",
        })
        self.assertEqual(resp.status_code, 200)  # re-render, not redirect
        self.assertEqual(CalendarSubscription.objects.count(), 0)

        resp = self.client.post("/calendar-sync/subscriptions/save/", {
            "label": "Personal", "url": "https://cal.example.com/p.ics",
            "color": "#3366ff", "enabled": "on",
        })
        self.assertEqual(resp.status_code, 302)
        sub = CalendarSubscription.objects.get()
        self.assertEqual(sub.label, "Personal")
        self.assertEqual(sub.url, "https://cal.example.com/p.ics")
        self.assertNotIn("cal.example.com", sub.url_encrypted)

    def test_edit_blank_url_keeps_stored(self):
        sub = CalendarSubscription.objects.create(label="P", color="#111111")
        sub.url = "https://keep.example.com/a.ics"
        sub.save()

        resp = self.client.post("/calendar-sync/subscriptions/save/", {
            "id": sub.pk, "label": "Renamed", "url": "", "color": "#222222", "enabled": "on",
        })
        self.assertEqual(resp.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.label, "Renamed")
        self.assertEqual(sub.url, "https://keep.example.com/a.ics")  # unchanged

    def test_delete(self):
        sub = CalendarSubscription.objects.create(label="Gone")
        resp = self.client.post("/calendar-sync/subscriptions/delete/", {"id": sub.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(CalendarSubscription.objects.exists())

    def test_test_button_reports_via_fetch(self):
        sub = CalendarSubscription.objects.create(label="P")
        sub.url = "https://cal.example.com/p.ics"
        sub.save()
        now = timezone.now()
        feed = build_calendar(build_event(uid="e@x", summary="Busy", start=now, end=now))
        with mock.patch("calendar_sync.services.fetch_ical", return_value=feed):
            resp = self.client.post(
                "/calendar-sync/subscriptions/test/", {"id": sub.pk}, follow=True
            )
        self.assertEqual(resp.status_code, 200)
        sub.refresh_from_db()
        self.assertTrue(sub.last_fetch_ok)


class InviteConfigTests(CalendarTabBase):
    def test_save_global_invite_settings(self):
        resp = self.client.post("/calendar-sync/invites/settings/", {
            "enabled": "on", "owner_address": "me@home.example",
            "default_remote_address": "Home office",
        })
        self.assertEqual(resp.status_code, 302)
        s = CalendarInviteSettings.load()
        self.assertTrue(s.enabled)
        self.assertEqual(s.owner_address, "me@home.example")

    def test_bad_owner_address_rerenders(self):
        resp = self.client.post("/calendar-sync/invites/settings/", {
            "enabled": "on", "owner_address": "not-an-email",
        })
        self.assertEqual(resp.status_code, 200)  # errors shown, no redirect
        self.assertFalse(CalendarInviteSettings.load().enabled)

    def test_contract_page_saves_calendar_config(self):
        # Per-contract config now lives on the contract edit page.
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=wp)
        resp = self.client.post(
            f"/workplaces/{wp.slug}/contracts/{contract.pk}/edit/",
            {
                "name": "", "send_invites": "on", "send_to_work": "on",
                "recipient": "boss@work.example", "address_onsite": "Main St 1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        cfg = ContractCalendarConfig.objects.get(contract=contract)
        self.assertTrue(cfg.send_invites)
        self.assertTrue(cfg.send_to_work)
        self.assertEqual(cfg.recipient, "boss@work.example")
        self.assertEqual(cfg.address_onsite, "Main St 1")

    def test_contract_page_requires_recipient_when_invites_on(self):
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=wp)
        resp = self.client.post(
            f"/workplaces/{wp.slug}/contracts/{contract.pk}/edit/",
            # invites + work address on, but neither value filled in
            {"name": "", "send_invites": "on", "send_to_work": "on"},
        )
        self.assertEqual(resp.status_code, 200)  # re-render with errors, no redirect
        self.assertFalse(ContractCalendarConfig.objects.filter(contract=contract).exists())

    def test_work_address_can_be_switched_off_like_the_personal_one(self):
        """Inviting the employer's mailbox is a separate decision from wanting the
        shift in your own calendar — off means no work recipient is required and
        none is resolved, so the invite goes to the personal copy alone."""
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=wp)
        resp = self.client.post(
            f"/workplaces/{wp.slug}/contracts/{contract.pk}/edit/",
            # send_to_work omitted = the switch is off; no recipient given
            {"name": "", "send_invites": "on", "address_onsite": "Main St 1"},
        )
        self.assertEqual(resp.status_code, 302)
        cfg = ContractCalendarConfig.objects.get(contract=contract)
        self.assertTrue(cfg.send_invites)
        self.assertFalse(cfg.send_to_work)
        self.assertEqual(cfg.resolved_recipient(), "")
        self.assertEqual(cfg.recipient_list(), [])

    def test_switching_the_work_address_off_keeps_the_stored_one(self):
        """Resolution, not storage, is what the switch gates: the hidden input stays
        in the DOM and posts its value (the same rule the override toggles follow),
        so turning the switch back on doesn't make the owner retype the address."""
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=wp)
        base = {
            "name": "", "send_invites": "on", "address_onsite": "Main St 1",
            "recipient": "boss@work.example",
        }
        self.client.post(
            f"/workplaces/{wp.slug}/contracts/{contract.pk}/edit/",
            {**base, "send_to_work": "on"},
        )
        # Same POST minus the switch — what unchecking it actually submits.
        self.client.post(f"/workplaces/{wp.slug}/contracts/{contract.pk}/edit/", base)
        cfg = ContractCalendarConfig.objects.get(contract=contract)
        self.assertFalse(cfg.send_to_work)
        self.assertEqual(cfg.recipient, "boss@work.example")
        self.assertEqual(cfg.resolved_recipient(), "")

    def test_calendar_tab_names_contracts_that_would_reach_nobody(self):
        """A contract with no work address of its own is carried by the personal
        copy alone — the tab has to say which ones, since switching that off is
        what silently leaves them with no recipient."""
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=wp, name="Weekday")
        ContractCalendarConfig.objects.create(
            contract=contract, send_invites=True, send_to_work=False,
        )
        resp = self.client.get("/settings/?tab=calendar")
        self.assertContains(resp, 'id="calNoRecipientsGlobal"')
        self.assertContains(resp, "JKF — Weekday")
        self.assertContains(
            resp, f"/workplaces/{wp.slug}/contracts/{contract.pk}/edit/"
        )

    def test_a_contract_with_a_work_address_raises_no_warning(self):
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=wp)
        ContractCalendarConfig.objects.create(
            contract=contract, send_invites=True, recipient="boss@work.example",
        )
        self.assertNotContains(
            self.client.get("/settings/?tab=calendar"), 'id="calNoRecipientsGlobal"'
        )

    def test_the_overview_only_claims_personal_only_while_that_is_on(self):
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=wp)
        ContractCalendarConfig.objects.create(
            contract=contract, send_invites=True, send_to_work=False,
        )
        self.assertContains(
            self.client.get("/settings/?tab=calendar"), "Personal calendar only"
        )
        s = CalendarInviteSettings.load()
        s.send_to_personal = False
        s.save()
        resp = self.client.get("/settings/?tab=calendar")
        self.assertNotContains(resp, "Personal calendar only")
        self.assertContains(resp, "No recipient")

    def test_calendar_overview_lists_contracts_readonly(self):
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        WorkplaceContract.objects.create(workplace=wp, name="Weekday")
        resp = self.client.get("/settings/?tab=calendar")
        self.assertContains(resp, "Per contract")
        self.assertContains(resp, "Weekday")
        # Edit links point at the contract page, not an inline form.
        self.assertContains(resp, f"/workplaces/{wp.slug}/contracts/")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TestInviteButtonTests(CalendarTabBase):
    def test_sends_test_invite_to_owner(self):
        mail.outbox = []
        MailConnection.objects.create(name="Default", host="smtp.zink.nu",
                                      from_email="robot@zink.nu", is_default=True)
        es = EmailSettings.load()
        es.enabled = True
        es.save()
        s = CalendarInviteSettings.load()
        s.enabled, s.owner_address = True, "me@home.example"
        s.save()

        from scheduler import services
        from scheduler.models import ScheduledTask

        resp = self.client.post("/calendar-sync/invites/test/", follow=True)
        self.assertEqual(resp.status_code, 200)
        # The button now hands off to the scheduler queue instead of blocking the
        # request on two SMTP round-trips — so nothing is sent yet.
        self.assertEqual(len(mail.outbox), 0)
        task = ScheduledTask.objects.get(task="calendar.test_invite")
        self.assertEqual(task.payload["to"], "me@home.example")

        # Draining the queue is what actually sends: a REQUEST then an immediate
        # withdraw (CANCEL), so it doesn't linger as an unanswered invitation.
        services.run_pending_tasks()
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("me@home.example", mail.outbox[0].to)
        self.assertIn("METHOD:REQUEST", mail.outbox[0].alternatives[0][0])
        self.assertIn("METHOD:CANCEL", mail.outbox[1].alternatives[0][0])
        self.assertTrue(CalendarInviteSettings.load().last_test_ok)
        task.refresh_from_db()
        self.assertEqual(task.status, ScheduledTask.DONE)

    def test_no_address_reports_error(self):
        resp = self.client.post("/calendar-sync/invites/test/", follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
