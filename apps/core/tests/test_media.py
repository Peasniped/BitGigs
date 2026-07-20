"""Serving uploaded media (workplace icons).

Media used to be routed only under ``if settings.DEBUG``, so a containerised
deployment running the production settings 404'd every uploaded icon. The route
is now unconditional — these tests pin that, and that it stays behind the login
gate.
"""
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA)
class MediaServingTest(TestCase):
    def setUp(self):
        icons = Path(_MEDIA) / "workplace_icons"
        icons.mkdir(parents=True, exist_ok=True)
        (icons / "acme_icon.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        self.url = "/media/workplace_icons/acme_icon.png"

    def _login(self):
        self.client.force_login(User.objects.create_user("tester", password="pw"))
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_served_to_logged_in_user(self):
        self._login()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_missing_file_is_404(self):
        self._login()
        self.assertEqual(self.client.get("/media/workplace_icons/no.png").status_code, 404)

    @override_settings(DEBUG=False)
    def test_served_with_debug_off(self):
        """The regression itself: production settings must still serve media."""
        self._login()
        self.assertEqual(self.client.get(self.url).status_code, 200)
