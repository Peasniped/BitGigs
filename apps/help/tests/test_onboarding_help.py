"""Help availability around onboarding: the FAB renders on wizard pages, the
context endpoint serves each step's articles, the manual isn't bounced into the
wizard by OnboardingRequiredMiddleware, and anonymous visitors (the pre-login
account/claim steps) see only public-audience articles."""
import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.tests.test_auth import SetupKeyMixin


class OnboardingHelpTests(SetupKeyMixin, TestCase):
    def test_fab_and_context_on_tax_step(self):
        user = User.objects.create_user("owner", "o@example.com", "x")
        self.client.force_login(user)
        resp = self.client.get("/onboarding/tax/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"help-fab", resp.content)
        self.assertIn(b"helpOffcanvas", resp.content)

        ctx = self.client.get("/help/context/?page=core:onboarding-tax")
        self.assertEqual(ctx.status_code, 200)
        for title in (
            b"The tax profile step",
            b"First-time setup",
            b"Tax profiles",
            b"Danish pay concepts",
        ):
            self.assertIn(title, ctx.content)

        # The manual itself must also survive mid-onboarding.
        manual = self.client.get("/help/")
        self.assertEqual(manual.status_code, 200)

    def test_anonymous_fresh_install_sees_public_help_only(self):
        # No user exists: the claim step renders the FAB, and help serves
        # exactly the public-audience articles.
        resp = self.client.get("/onboarding/account/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"help-fab", resp.content)

        ctx = self.client.get("/help/context/?page=core:onboarding-account")
        self.assertEqual(ctx.status_code, 200)
        self.assertIn(b"Claiming the instance", ctx.content)
        self.assertIn(b"First-time setup", ctx.content)

        index = json.loads(
            self.client.get("/help/search-index.json").content
        )["articles"]
        self.assertEqual(
            sorted(a["slug"] for a in index),
            ["first-time-setup", "onboarding-account", "onboarding-claim"],
        )

        self.assertEqual(self.client.get("/help/").status_code, 200)
        self.assertEqual(
            self.client.get("/help/onboarding-claim/").status_code, 200
        )
        # Non-public articles stay invisible without login.
        self.assertEqual(self.client.get("/help/payroll/").status_code, 404)

    def test_anonymous_after_claim_still_public_only(self):
        User.objects.create_user("owner", "o@example.com", "x")
        index = json.loads(
            self.client.get("/help/search-index.json").content
        )["articles"]
        self.assertEqual(
            sorted(a["slug"] for a in index),
            ["first-time-setup", "onboarding-account", "onboarding-claim"],
        )
        self.assertEqual(self.client.get("/help/payroll/").status_code, 404)
