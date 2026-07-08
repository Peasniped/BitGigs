"""Site-wide login gate (LoginRequiredMiddleware)."""
from django.contrib.auth.models import User
from django.test import TestCase


class LoginGateTest(TestCase):
    """With an account in place, everything anonymous funnels to login."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].startswith("/accounts/login/"))

    def test_login_page_renders_anonymously(self):
        resp = self.client.get("/accounts/login/")
        self.assertEqual(resp.status_code, 200)

    def test_authenticated_user_passes_the_gate(self):
        self.client.force_login(self.user)
        resp = self.client.get("/")
        # Setup middleware may redirect to onboarding, but not to login.
        if resp.status_code == 302:
            self.assertFalse(resp["Location"].startswith("/accounts/login/"))
        else:
            self.assertEqual(resp.status_code, 200)


class FirstUserSetupTest(TestCase):
    """Fresh install: onboarding starts with account creation."""

    def test_everything_redirects_to_account_step_when_no_users(self):
        for path in ("/", "/accounts/login/", "/workplaces/"):
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, path)
            self.assertEqual(resp["Location"], "/setup/user/", path)

    def test_account_step_renders_and_creates_admin_user(self):
        resp = self.client.get("/setup/user/")
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post("/setup/user/", {
            "username": "me",
            "password1": "correct-horse-battery",
            "password2": "correct-horse-battery",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/setup/")
        user = User.objects.get(username="me")
        self.assertTrue(user.is_superuser)
        # The new user is logged in and continues to the tax step.
        resp = self.client.get("/setup/")
        self.assertEqual(resp.status_code, 200)

    def test_account_step_is_gone_once_a_user_exists(self):
        User.objects.create_user("existing", password="pw")
        resp = self.client.get("/setup/user/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/accounts/login/")
