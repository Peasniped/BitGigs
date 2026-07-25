"""Phase 3 — the hidden email step slotted between Workplace and Pay Terms when
the user opts into calendar invites without a mail server yet."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import EmailSettings, OnboardingDraft


def make_config():
    es = EmailSettings.load()
    es.enabled, es.host, es.from_email = True, "smtp.example.com", "me@example.com"
    es.save()
    return es


class OnboardingWorkplaceDetourTests(TestCase):
    """The Workplace step detours to the email step only when advancing with
    invites on and no mail server yet."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)  # mid-onboarding: not marked complete
        self.url = reverse("core:onboarding-workplace")

    def _post(self, **extra):
        data = {"name": "JKF", "slug": "", "contract-name": ""}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_yes_without_email_detours_to_email_step(self):
        resp = self._post(send_invites="true", recipient="b@w.example",
                          address_onsite="Main St 1")
        self.assertRedirects(resp, reverse("core:onboarding-email"),
                             fetch_redirect_response=False)

    def test_no_goes_straight_to_terms(self):
        resp = self._post(send_invites="")
        self.assertRedirects(resp, reverse("core:onboarding-terms"),
                             fetch_redirect_response=False)

    def test_yes_with_email_already_configured_skips_email_step(self):
        make_config()
        resp = self._post(send_invites="true", recipient="b@w.example",
                          address_onsite="Main St 1")
        self.assertRedirects(resp, reverse("core:onboarding-terms"),
                             fetch_redirect_response=False)

    def test_explicit_jump_is_not_overridden_by_the_detour(self):
        resp = self._post(send_invites="true", recipient="b@w.example",
                          address_onsite="Main St 1", onboarding_goto="terms")
        self.assertRedirects(resp, reverse("core:onboarding-terms"),
                             fetch_redirect_response=False)


class OnboardingEmailViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)
        self.url = reverse("core:onboarding-email")

    def opt_in(self):
        OnboardingDraft.objects.update_or_create(
            user=self.user,
            defaults={"data": {"workplace": {"name": "JKF", "send_invites": "true"}}},
        )

    def test_get_renders_the_email_form_when_opted_in(self):
        self.opt_in()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="emailSettingsForm"')

    def test_get_redirects_to_terms_when_invites_not_opted_in(self):
        resp = self.client.get(self.url)
        self.assertRedirects(resp, reverse("core:onboarding-terms"),
                             fetch_redirect_response=False)

    def test_valid_save_stores_config_and_continues_to_terms(self):
        self.opt_in()
        resp = self.client.post(self.url, {
            "enabled": "on", "host": "smtp.example.com", "port": "587",
            "security": "starttls", "username": "me@example.com",
            "password": "hunter2", "from_email": "me@example.com",
            "from_name": "BitGigs", "timeout": "10",
        })
        self.assertRedirects(resp, reverse("core:onboarding-terms"),
                             fetch_redirect_response=False)
        self.assertTrue(EmailSettings.load().is_configured)

    @patch("core.mail.diagnose")
    def test_connection_test_uses_typed_values_without_saving(self, mock_diag):
        # A dry run: the test hits the typed values and persists nothing.
        mock_diag.return_value = SimpleNamespace(as_dict=lambda: {"ok": True, "stages": []})
        resp = self.client.post(reverse("core:onboarding-email-test"), {
            "enabled": "on", "host": "smtp.typed.example", "port": "587",
            "security": "starttls", "username": "me@typed.example",
            "password": "hunter2", "from_email": "me@typed.example",
            "from_name": "BitGigs", "timeout": "10",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        # diagnose saw the typed host, and nothing was written to the stored config.
        self.assertEqual(mock_diag.call_args.args[0].host, "smtp.typed.example")
        self.assertFalse(EmailSettings.load().is_configured)

    def test_connection_test_rejects_incomplete_details(self):
        resp = self.client.post(reverse("core:onboarding-email-test"), {
            "enabled": "on", "host": "", "port": "587", "security": "starttls",
        })
        self.assertEqual(resp.status_code, 400)


class OnboardingResetClearsEmailTests(TestCase):
    """Start over must wipe the mail server the hidden email step saved as it went,
    or a fresh restart lands back on a pre-filled email form (the reported bug)."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)  # mid-onboarding: not marked complete

    def test_start_over_resets_email_settings(self):
        make_config()
        self.assertTrue(EmailSettings.load().is_configured)
        resp = self.client.post(reverse("core:onboarding-reset"))
        self.assertRedirects(resp, reverse("core:onboarding-start"),
                             fetch_redirect_response=False)
        config = EmailSettings.load()
        self.assertFalse(config.is_configured)
        self.assertEqual(config.host, "")


class OnboardingEmailEndpointsReachableTests(TestCase):
    """The test/probe endpoints must be reachable mid-onboarding — under
    /onboarding/ they escape the funnel. A GET hits the (POST-only) view and gets
    405, proving it wasn't 302-redirected back into the wizard."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)

    def test_test_endpoint_not_funnelled(self):
        resp = self.client.get(reverse("core:onboarding-email-test"))
        self.assertEqual(resp.status_code, 405)

    def test_probe_endpoint_not_funnelled(self):
        resp = self.client.get(reverse("core:onboarding-email-probe"))
        self.assertEqual(resp.status_code, 405)
