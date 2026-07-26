"""Phase 3 — Settings → Calendar tab: subscriptions CRUD + test, invite
settings, per-workplace config, and the test-invite button."""
from datetime import date, time
from decimal import Decimal
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
from workplaces.models import ContractTermSet, Workplace, WorkplaceContract


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
                "name": "", "send_invites": "on",
                "recipient": "boss@work.example", "address_onsite": "Main St 1",
            },
        )
        self.assertEqual(resp.status_code, 302)
        cfg = ContractCalendarConfig.objects.get(contract=contract)
        self.assertTrue(cfg.send_invites)
        self.assertEqual(cfg.recipient, "boss@work.example")
        self.assertEqual(cfg.address_onsite, "Main St 1")

    def test_contract_page_requires_recipient_when_invites_on(self):
        wp = Workplace.objects.create(name="JKF", slug="jkf")
        contract = WorkplaceContract.objects.create(workplace=wp)
        resp = self.client.post(
            f"/workplaces/{wp.slug}/contracts/{contract.pk}/edit/",
            {"name": "", "send_invites": "on"},  # no recipient / on-site location
        )
        self.assertEqual(resp.status_code, 200)  # re-render with errors, no redirect
        self.assertFalse(ContractCalendarConfig.objects.filter(contract=contract).exists())

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

        resp = self.client.post("/calendar-sync/invites/test/", follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("me@home.example", mail.outbox[0].to)
        self.assertTrue(CalendarInviteSettings.load().last_test_ok)

    def test_no_address_reports_error(self):
        resp = self.client.post("/calendar-sync/invites/test/", follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
