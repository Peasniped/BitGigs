"""The logging configuration and the log lines that carry operational weight.

Django only ever configures a handler for its own ``django`` logger, so before
``LOGGING`` existed an app module's ``logger.info()`` went nowhere at all. These
tests pin the wiring that fixes that — app loggers reach a handler, third-party
noise does not — plus the sign-in trail, which is the one thing a self-hosted
install on the open internet really wants recorded.
"""
import logging

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.crypto import decrypt_secret
from core.utils import client_ip


class LoggingConfigTests(TestCase):
    """The dictConfig in bitgigs/settings/base.py, as actually applied."""

    def test_app_loggers_reach_a_handler(self):
        """Every app in LOCAL_APPS gets a logger that propagates to root's
        handler. This is what makes logger.info() in e.g. calendar_sync/invites.py
        visible at all — the bug the config exists to fix."""
        from django.conf import settings

        root = logging.getLogger()
        self.assertTrue(root.handlers, "root logger has no handler")
        for entry in settings.LOCAL_APPS:
            name = entry.split(".")[0]
            with self.subTest(app=name):
                logger = logging.getLogger(name)
                self.assertTrue(logger.propagate)
                self.assertEqual(
                    logger.getEffectiveLevel(), getattr(logging, settings.LOG_LEVEL),
                )

    def test_module_logger_inherits_its_app_level(self):
        """Modules use getLogger(__name__), which under apps/ is a dotted name
        below the app label — so the app's level has to reach it."""
        from django.conf import settings

        logger = logging.getLogger("calendar_sync.invites")
        self.assertEqual(
            logger.getEffectiveLevel(), getattr(logging, settings.LOG_LEVEL),
        )

    def test_third_party_loggers_stay_at_warning(self):
        """Libraries inherit root, not the app level — routine INFO chatter from
        a dependency must not drown out BitGigs' own lines."""
        self.assertEqual(
            logging.getLogger("some.third.party.library").getEffectiveLevel(),
            logging.WARNING,
        )

    def test_console_handler_is_not_debug_filtered(self):
        """Django's own `console` handler carries require_debug_true, which is
        exactly why nothing was ever visible in production. Redefining the name
        must not inherit that filter."""
        from django.conf import settings

        console = settings.LOGGING["handlers"]["console"]
        self.assertNotIn("filters", console)

    def test_django_logger_does_not_double_log(self):
        """`django` has its own handler, so it must not also propagate to root —
        that would print every framework message twice."""
        self.assertFalse(logging.getLogger("django").propagate)


class SignInLoggingTests(TestCase):
    """BitGigsLoginView's auth trail."""

    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", password="pw")

    def test_failed_sign_in_is_logged_as_a_warning(self):
        with self.assertLogs("core.views", level="WARNING") as captured:
            self.client.post(reverse("login"), {
                "username": "owner@example.com", "password": "wrong",
            })
        self.assertIn("Sign-in failed", captured.output[0])
        self.assertIn("owner@example.com", captured.output[0])

    def test_failed_sign_in_never_logs_the_password(self):
        with self.assertLogs("core.views", level="WARNING") as captured:
            self.client.post(reverse("login"), {
                "username": "owner@example.com", "password": "hunter2-secret",
            })
        self.assertNotIn("hunter2-secret", "\n".join(captured.output))

    def test_successful_sign_in_is_logged_as_info(self):
        with self.assertLogs("core.views", level="INFO") as captured:
            self.client.post(reverse("login"), {
                "username": "owner@example.com", "password": "pw",
            })
        self.assertTrue(
            any("Sign-in succeeded" in line for line in captured.output),
            captured.output,
        )


class ClientIpTests(TestCase):
    """The shared helper behind both the reset rate limiter and the auth log."""

    def _request(self, **meta):
        from django.test import RequestFactory
        return RequestFactory().get("/", **meta)

    def test_uses_remote_addr_by_default(self):
        request = self._request(REMOTE_ADDR="10.0.0.9",
                                HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(client_ip(request), "10.0.0.9")

    @override_settings(TRUST_PROXY_IP=True)
    def test_honours_forwarded_for_only_when_a_proxy_is_declared(self):
        request = self._request(REMOTE_ADDR="10.0.0.9",
                                HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1")
        self.assertEqual(client_ip(request), "1.2.3.4")

    @override_settings(TRUST_PROXY_IP=True)
    def test_falls_back_when_the_proxy_sent_no_header(self):
        request = self._request(REMOTE_ADDR="10.0.0.9")
        self.assertEqual(client_ip(request), "10.0.0.9")

    def test_missing_address_is_named_not_blank(self):
        request = self._request()
        request.META.pop("REMOTE_ADDR")  # RequestFactory supplies 127.0.0.1
        self.assertEqual(client_ip(request), "unknown")


class SecretDecryptionLoggingTests(TestCase):
    """A rotated SECRET_KEY silently unreads every stored secret. The settings
    page asks the owner to re-enter it, but only whoever opens that page sees it
    — the log is what explains a mail server that stopped authenticating."""

    def test_unreadable_secret_warns_without_leaking_the_token(self):
        token = "gAAAAAB-not-a-valid-fernet-token"
        with self.assertLogs("core.crypto", level="WARNING") as captured:
            self.assertIsNone(decrypt_secret(token))
        joined = "\n".join(captured.output)
        self.assertIn("DJANGO_SECRET_KEY", joined)
        self.assertNotIn(token, joined)
