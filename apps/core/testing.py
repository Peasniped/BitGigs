"""Shared test helpers.

Not a ``test_*`` module, so the runner imports it rather than collecting it.
"""
from django.contrib.auth.models import User
from django.test import TestCase


def login_client(client, user):
    """Sign ``user`` in and mark onboarding done, so OnboardingRequiredMiddleware
    lets normal pages through instead of funnelling to the wizard.

    Standalone for the tests that are anonymous for part of their run and so
    can't take the login in ``setUp`` (see ``core.tests.test_media``)."""
    client.force_login(user)
    session = client.session
    session["onboarding_complete"] = True
    session.save()


class LoggedInTestCase(TestCase):
    """View tests need an authenticated client (site-wide login gate) that has
    already finished onboarding."""

    username = "tester"

    def setUp(self):
        self.user = self.create_user()
        login_client(self.client, self.user)

    def create_user(self):
        """Override where the account itself matters — a staff flag, an e-mail
        (which is also the username in BitGigs) or a display name."""
        return User.objects.create_user(self.username, password="pw")
