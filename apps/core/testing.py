"""Shared test helpers.

Not a ``test_*`` module, so the runner imports it rather than collecting it.
"""
from django.contrib.auth.models import User
from django.test import TestCase


class LoggedInTestCase(TestCase):
    """View tests need an authenticated client (site-wide login gate) that has
    already finished onboarding, so the OnboardingRequiredMiddleware lets normal
    pages through instead of funnelling to the wizard."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()
