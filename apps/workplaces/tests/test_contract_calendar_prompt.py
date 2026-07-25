"""The contract-create form forces an explicit Yes/No on calendar invites and
warns (without blocking) when invites can't actually send yet. Contract edit is
deliberately left as a plain switch."""
from django.test import TestCase
from django.urls import reverse

from calendar_sync.models import CalendarInviteSettings, ContractCalendarConfig
from core.models import EmailSettings
from workplaces.models import Workplace, WorkplaceContract

from .test_contract_overlap import LoggedInTestCase


class ContractCreateInvitePromptTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.wp = Workplace.objects.create(name="JKF", slug="jkf")
        self.create_url = reverse("workplaces:contract-create", args=[self.wp.slug])

    def test_create_shows_forced_radio_not_switch(self):
        resp = self.client.get(self.create_url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Forced Yes/No radios, both required, neither pre-selected on a fresh form.
        self.assertIn('id="id_send_invites_yes"', html)
        self.assertIn('id="id_send_invites_no"', html)
        self.assertNotIn("checked", html.split("id_send_invites_yes")[1][:120])
        # The plain edit switch must not appear on create.
        self.assertNotIn('id="id_send_invites"', html)

    def test_yes_creates_config_enabled(self):
        resp = self.client.post(self.create_url, {
            "name": "",
            "send_invites": "true",
            "recipient": "boss@work.example",
            "address_onsite": "Main St 1",
        })
        self.assertEqual(resp.status_code, 302)
        contract = self.wp.contracts.get()
        cfg = contract.calendar_config
        self.assertTrue(cfg.send_invites)
        self.assertEqual(cfg.recipient, "boss@work.example")

    def test_no_creates_config_disabled_without_requiring_recipient(self):
        resp = self.client.post(self.create_url, {
            "name": "",
            "send_invites": "",  # the "No" radio submits an empty value
        })
        self.assertEqual(resp.status_code, 302)
        cfg = self.wp.contracts.get().calendar_config
        self.assertFalse(cfg.send_invites)

    def test_yes_without_recipient_is_rejected(self):
        resp = self.client.post(self.create_url, {
            "name": "",
            "send_invites": "true",
            "recipient": "",
            "address_onsite": "",
        })
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertFalse(WorkplaceContract.objects.filter(workplace=self.wp).exists())

    def test_warns_when_email_not_configured(self):
        resp = self.client.get(self.create_url)
        self.assertContains(resp, "isn't set up yet")
        self.assertContains(resp, "?tab=email")

    def test_warns_when_master_switch_off_but_email_ready(self):
        es = EmailSettings.load()
        es.enabled, es.host, es.from_email = True, "smtp.example", "robot@example"
        es.save()
        s = CalendarInviteSettings.load()
        s.enabled = False
        s.save()
        resp = self.client.get(self.create_url)
        self.assertContains(resp, "turned off globally")
        self.assertContains(resp, "?tab=calendar")


class ContractEditUsesButtonsTests(LoggedInTestCase):
    """Edit uses the same segmented button toggle as create — no separate switch —
    but pre-set to the saved value, so it reflects the current setting rather than
    forcing a blank choice."""

    def setUp(self):
        super().setUp()
        self.wp = Workplace.objects.create(name="JKF", slug="jkf")
        self.contract = WorkplaceContract.objects.create(workplace=self.wp)

    def _edit_url(self):
        return reverse("workplaces:contract-update", args=[self.wp.slug, self.contract.pk])

    def test_edit_uses_button_toggle_not_switch(self):
        ContractCalendarConfig.objects.create(contract=self.contract, send_invites=False)
        html = self.client.get(self._edit_url()).content.decode()
        self.assertIn('id="id_send_invites_yes"', html)
        self.assertNotIn('id="id_send_invites"', html)  # the old switch is gone

    def test_edit_preselects_saved_value(self):
        ContractCalendarConfig.objects.create(
            contract=self.contract, send_invites=True,
            recipient="boss@work.example", address_onsite="Main St 1",
        )
        html = self.client.get(self._edit_url()).content.decode()
        self.assertIn("checked", html.split('id="id_send_invites_yes"')[1][:90])
