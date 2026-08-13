"""Every password field gets a reveal control.

The toggle is added at runtime by ``initPasswordReveals`` in app.js rather than
by each template, so what these tests pin is the contract that makes that work:
the pages carrying password inputs also load app.js, and none of them hand-rolls
a competing toggle.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.setup_key import SESSION_FLAG
from core.testing import login_client
from core.tests.test_auth import SetupKeyMixin


class PasswordFieldsLoadTheRevealScriptTest(SetupKeyMixin, TestCase):
    def assert_reveal_available(self, response, where):
        body = response.content.decode()
        self.assertIn('type="password"', body, f"{where}: no password field")
        self.assertIn("js/app.js", body, f"{where}: app.js not loaded")

    def test_login_page(self):
        # An owner has to exist, or the fresh-install funnel sends the login page
        # to the account step instead of rendering it.
        User.objects.create_user("owner@example.com", password="pw")
        self.assert_reveal_available(self.client.get("/accounts/login/"), "login")

    def test_onboarding_account_step(self):
        session = self.client.session
        session[SESSION_FLAG] = True
        session.save()
        self.assert_reveal_available(
            self.client.get(reverse("core:onboarding-account-email")), "account step")

    def test_settings_password_modal(self):
        login_client(self.client, User.objects.create_superuser("me@example.com", password="pw"))
        self.assert_reveal_available(
            self.client.get(reverse("core:settings") + "?tab=signin"), "settings")

    def test_onboarding_review_reuses_the_same_modal(self):
        """Review includes the shared partial, so its fields are covered too."""
        user = User.objects.create_superuser("owner@example.com", password="pw")
        self.client.force_login(user)
        response = self.client.get(reverse("core:onboarding-review"))
        self.assert_reveal_available(response, "review")
        self.assertContains(response, 'id="passwordModal"')
