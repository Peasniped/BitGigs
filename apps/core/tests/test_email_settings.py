"""Mail configuration: secret storage, the staged connection test, and the
password-reset flow it unlocks."""
import re
import smtplib
import socket
import ssl
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from core import mail as core_mail
from core.crypto import decrypt_secret, encrypt_secret
from core.mail_backend import DbConfiguredEmailBackend
from core.models import EmailLog, EmailSettings, UserSettings
from core.mail import FAILED, OK, SKIPPED


def make_config(**overrides):
    config = EmailSettings.load()
    config.enabled = True
    config.host = "smtp.example.com"
    config.port = 587
    config.security = EmailSettings.SECURITY_STARTTLS
    config.username = "me@example.com"
    config.password = "hunter2"
    config.from_email = "me@example.com"
    config.timeout = 5
    for key, value in overrides.items():
        setattr(config, key, value)
    config.save()
    return config


class SecretStorageTests(TestCase):
    def test_round_trip(self):
        self.assertEqual(decrypt_secret(encrypt_secret("hunter2")), "hunter2")

    def test_ciphertext_is_not_the_plaintext(self):
        self.assertNotIn("hunter2", encrypt_secret("hunter2"))

    def test_empty_stays_empty(self):
        self.assertEqual(encrypt_secret(""), "")
        self.assertEqual(decrypt_secret(""), "")

    def test_rotated_secret_key_is_reported_not_crashed(self):
        token = encrypt_secret("hunter2")
        with override_settings(SECRET_KEY="a-completely-different-key"):
            self.assertIsNone(decrypt_secret(token))

    def test_model_flags_an_undecryptable_password(self):
        config = make_config()
        with override_settings(SECRET_KEY="a-completely-different-key"):
            config.refresh_from_db()
            self.assertTrue(config.password_unreadable)
            self.assertIsNone(config.password)

    def test_environment_override_wins(self):
        config = make_config()
        with override_settings(EMAIL_PASSWORD_OVERRIDE="from-the-env"):
            self.assertEqual(config.password, "from-the-env")
            self.assertTrue(config.password_from_env)


class ConfiguredFlagTests(TestCase):
    def test_disabled_is_not_configured(self):
        self.assertFalse(make_config(enabled=False).is_configured)

    def test_missing_host_is_not_configured(self):
        self.assertFalse(make_config(host="").is_configured)

    def test_from_address_uses_the_display_name(self):
        config = make_config(from_name="BitGigs")
        self.assertEqual(core_mail.from_address(config), "BitGigs <me@example.com>")

    def test_from_address_without_a_name_is_bare(self):
        config = make_config(from_name="")
        self.assertEqual(core_mail.from_address(config), "me@example.com")


class DiagnoseTests(TestCase):
    """Each test forces one failure mode and asserts the report stops there —
    the point of the feature is that the first ✗ names the wrong setting."""

    def stages(self, result):
        return {s.key: s for s in result.stages}

    def test_incomplete_config_fails_at_the_first_stage(self):
        result = core_mail.diagnose(make_config(host=""))
        stages = self.stages(result)
        self.assertFalse(result.ok)
        self.assertEqual(stages["config"].status, FAILED)
        self.assertIn("hostname", stages["config"].detail)
        self.assertEqual(stages["dns"].status, SKIPPED)

    def test_undecryptable_password_is_explained(self):
        config = make_config()
        with override_settings(SECRET_KEY="rotated"):
            config.refresh_from_db()
            result = core_mail.diagnose(config)
        stages = self.stages(result)
        self.assertEqual(stages["config"].status, FAILED)
        self.assertIn("DJANGO_SECRET_KEY", stages["config"].hint)

    @mock.patch("core.mail.socket.getaddrinfo", side_effect=socket.gaierror("nope"))
    def test_dns_failure_stops_before_connecting(self, _resolve):
        result = core_mail.diagnose(make_config())
        stages = self.stages(result)
        self.assertEqual(stages["dns"].status, FAILED)
        self.assertEqual(stages["connect"].status, SKIPPED)

    @mock.patch("core.mail.socket.create_connection", side_effect=ConnectionRefusedError)
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_refused_port_suggests_the_right_ports(self, _resolve, _connect):
        stages = self.stages(core_mail.diagnose(make_config()))
        self.assertEqual(stages["connect"].status, FAILED)
        self.assertIn("587", stages["connect"].hint)
        self.assertEqual(stages["tls"].status, SKIPPED)

    @mock.patch("core.mail.socket.create_connection", side_effect=TimeoutError)
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_timeout_blames_the_firewall(self, _resolve, _connect):
        stages = self.stages(core_mail.diagnose(make_config()))
        self.assertEqual(stages["connect"].status, FAILED)
        self.assertIn("firewall", stages["connect"].hint)

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_missing_starttls_support_suggests_implicit_tls(self, _r, _c, smtp):
        smtp.return_value.has_extn.return_value = False
        stages = self.stages(core_mail.diagnose(make_config()))
        self.assertEqual(stages["tls"].status, FAILED)
        self.assertIn("465", stages["tls"].hint)
        self.assertEqual(stages["auth"].status, SKIPPED)

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_tls_handshake_failure_blames_the_mode(self, _r, _c, smtp):
        smtp.return_value.starttls.side_effect = ssl.SSLError("wrong version number")
        stages = self.stages(core_mail.diagnose(make_config()))
        self.assertEqual(stages["tls"].status, FAILED)
        self.assertIn("security mode", stages["tls"].hint)

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_bad_credentials_quote_the_server_and_mention_app_passwords(self, _r, _c, smtp):
        smtp.return_value.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"5.7.8 Username and Password not accepted"
        )
        stages = self.stages(core_mail.diagnose(make_config()))
        self.assertEqual(stages["auth"].status, FAILED)
        self.assertIn("Username and Password not accepted", stages["auth"].detail)
        self.assertIn("app-specific password", stages["auth"].hint)

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_anonymous_config_skips_auth(self, _r, _c, smtp):
        result = core_mail.diagnose(make_config(username="", password=""))
        stages = self.stages(result)
        self.assertEqual(stages["auth"].status, SKIPPED)
        self.assertTrue(result.ok)
        smtp.return_value.login.assert_not_called()

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_everything_ok(self, _r, _c, smtp):
        result = core_mail.diagnose(make_config())
        self.assertTrue(result.ok)
        self.assertEqual(self.stages(result)["auth"].status, OK)

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_refused_sender_only_shows_up_on_a_real_send(self, _r, _c, smtp):
        smtp.return_value.send_message.side_effect = smtplib.SMTPSenderRefused(
            553, b"5.7.1 Sender address rejected", "me@example.com"
        )
        result = core_mail.diagnose(make_config(), send_to="you@example.com")
        stages = self.stages(result)
        # Everything up to the send passed — which is exactly why the optional
        # send stage exists.
        self.assertEqual(stages["auth"].status, OK)
        self.assertEqual(stages["send"].status, FAILED)
        self.assertIn("me@example.com", stages["send"].hint)

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_run_and_record_stores_the_outcome(self, _r, _c, smtp):
        make_config()
        core_mail.run_and_record()
        config = EmailSettings.load()
        self.assertTrue(config.last_test_ok)
        self.assertIsNotNone(config.last_test_at)


class EmailSettingsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", password="pw")
        self.user.email = "owner@example.com"
        self.user.save()
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_tab_renders(self):
        response = self.client.get(reverse("core:settings"), {"tab": "email"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Outgoing mail")

    def test_saving_stores_the_password_encrypted(self):
        self.client.post(reverse("core:email-settings"), {
            "enabled": "on", "host": "smtp.example.com", "port": "587",
            "security": "starttls", "username": "me@example.com",
            "password": "hunter2", "from_email": "me@example.com",
            "from_name": "BitGigs", "timeout": "10", "allow_password_reset": "on",
        })
        config = EmailSettings.load()
        self.assertEqual(config.password, "hunter2")
        self.assertNotIn("hunter2", config.password_encrypted)

    def test_blank_password_keeps_the_stored_one(self):
        make_config()
        self.client.post(reverse("core:email-settings"), {
            "enabled": "on", "host": "smtp.example.com", "port": "587",
            "security": "starttls", "username": "me@example.com",
            "password": "", "from_email": "me@example.com",
            "from_name": "", "timeout": "10",
        })
        self.assertEqual(EmailSettings.load().password, "hunter2")

    def test_clear_password_removes_it(self):
        make_config()
        self.client.post(reverse("core:email-settings"), {
            "enabled": "on", "host": "smtp.example.com", "port": "587",
            "security": "starttls", "username": "me@example.com",
            "password": "", "clear_password": "on", "from_email": "me@example.com",
            "from_name": "", "timeout": "10",
        })
        self.assertEqual(EmailSettings.load().password, "")

    def test_enabling_without_a_host_is_rejected(self):
        response = self.client.post(reverse("core:email-settings"), {
            "enabled": "on", "host": "", "port": "587", "security": "starttls",
            "username": "", "password": "", "from_email": "me@example.com",
            "from_name": "", "timeout": "10",
        })
        self.assertEqual(response.status_code, 200)  # re-rendered with errors
        self.assertFalse(EmailSettings.load().enabled)

    def test_test_endpoint_rejects_a_bad_recipient(self):
        make_config()
        response = self.client.post(reverse("core:email-test"), {"send_to": "not-an-email"})
        self.assertEqual(response.status_code, 400)

    def test_test_endpoint_returns_stages(self):
        make_config(host="")
        response = self.client.post(reverse("core:email-test"))
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stages"][0]["key"], "config")

    def test_test_endpoint_requires_a_login(self):
        self.client.logout()
        response = self.client.post(reverse("core:email-test"))
        self.assertEqual(response.status_code, 302)

    def test_test_endpoint_reports_unseen_failure_flag(self):
        make_config(host="")  # fails at the config stage, nothing sent → no failure logged
        payload = self.client.post(reverse("core:email-test")).json()
        self.assertIn("failures_unseen", payload)
        self.assertFalse(payload["failures_unseen"])


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "owner@example.com", email="owner@example.com", password="OldPw!2345x"
        )
        UserSettings.load()

    def test_hidden_while_mail_is_off(self):
        response = self.client.get("/accounts/password_reset/")
        self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)

    def test_hidden_when_the_operator_turned_reset_off(self):
        make_config(allow_password_reset=False)
        response = self.client.get("/accounts/password_reset/")
        self.assertRedirects(response, "/accounts/login/", fetch_redirect_response=False)

    def test_login_page_offers_it_only_when_available(self):
        response = self.client.get("/accounts/login/")
        self.assertNotContains(response, "Email me a reset link")
        make_config()
        response = self.client.get("/accounts/login/")
        self.assertContains(response, "Email me a reset link")

    def test_end_to_end(self):
        make_config()
        response = self.client.post(
            "/accounts/password_reset/", {"email": "owner@example.com"}
        )
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "BitGigs <me@example.com>")

        link = re.search(r"/accounts/reset/\S+", message.body).group(0)
        # Django swaps the token for a session-held one and redirects.
        self.client.get(link, follow=True)
        response = self.client.post(
            link.replace(link.split("/")[-2], "set-password"),
            {"new_password1": "Qx7#vantage", "new_password2": "Qx7#vantage"},
            follow=True,
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Qx7#vantage"))

    def test_link_uses_the_request_host_not_the_sites_framework(self):
        make_config()
        self.client.post(
            "/accounts/password_reset/", {"email": "owner@example.com"},
            HTTP_HOST="bitgigs.example.dk",
        )
        self.assertIn("bitgigs.example.dk", mail.outbox[0].body)
        self.assertNotIn("example.com/accounts/reset", mail.outbox[0].body)

    def test_unknown_address_reveals_nothing(self):
        make_config()
        response = self.client.post(
            "/accounts/password_reset/", {"email": "stranger@example.com"}
        )
        self.assertRedirects(response, "/accounts/password_reset/done/")
        self.assertEqual(len(mail.outbox), 0)

    def test_rate_limited(self):
        from django.core.cache import cache
        cache.clear()
        make_config()
        for _ in range(5):
            self.client.post("/accounts/password_reset/", {"email": "owner@example.com"})
        self.assertEqual(len(mail.outbox), 5)
        # The sixth is turned away without sending.
        self.client.post("/accounts/password_reset/", {"email": "owner@example.com"})
        self.assertEqual(len(mail.outbox), 5)
        cache.clear()


class EmailLogModelTests(TestCase):
    def test_record_marks_success_seen_and_failure_unseen(self):
        ok_row = EmailLog.record("a@b.com", "Hi", ok=True)
        fail_row = EmailLog.record("a@b.com", "Hi", ok=False, error="nope")
        self.assertIsNotNone(ok_row.acknowledged_at)   # successes never need dismissing
        self.assertIsNone(fail_row.acknowledged_at)
        self.assertQuerySetEqual(EmailLog.objects.failures_unseen(), [fail_row])

    def test_record_prunes_to_the_cap(self):
        with mock.patch.object(EmailLog, "PRUNE_KEEP", 3):
            for i in range(6):
                EmailLog.record("a@b.com", f"msg {i}", ok=True)
        self.assertEqual(EmailLog.objects.count(), 3)
        # The most recent survive.
        self.assertEqual(EmailLog.objects.first().subject, "msg 5")

    def test_backend_logs_a_successful_send(self):
        make_config()
        with mock.patch(
            "django.core.mail.backends.smtp.EmailBackend.send_messages", return_value=1
        ):
            backend = DbConfiguredEmailBackend()
            backend.send_messages([mail.EmailMessage(subject="Welcome", to=["you@x.com"])])
        row = EmailLog.objects.get()
        self.assertTrue(row.ok)
        self.assertEqual(row.subject, "Welcome")
        self.assertEqual(row.to, "you@x.com")
        self.assertEqual(row.kind, EmailLog.KIND_SENT)

    def test_backend_logs_a_failed_send_and_reraises(self):
        make_config()
        with mock.patch(
            "django.core.mail.backends.smtp.EmailBackend.send_messages",
            side_effect=smtplib.SMTPServerDisconnected("gone"),
        ):
            backend = DbConfiguredEmailBackend()
            with self.assertRaises(smtplib.SMTPServerDisconnected):
                backend.send_messages([mail.EmailMessage(subject="Nope", to=["you@x.com"])])
        row = EmailLog.objects.get()
        self.assertFalse(row.ok)
        self.assertIn("gone", row.error)

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_run_and_record_logs_a_test_send(self, _r, _c, smtp):
        make_config()
        core_mail.run_and_record(send_to="you@example.com")
        row = EmailLog.objects.get()
        self.assertTrue(row.ok)
        self.assertEqual(row.kind, EmailLog.KIND_TEST)
        self.assertEqual(row.to, "you@example.com")

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_run_and_record_logs_a_failed_test_send_with_reason(self, _r, _c, smtp):
        smtp.return_value.send_message.side_effect = smtplib.SMTPSenderRefused(
            553, b"5.7.1 Sender address rejected", "me@example.com"
        )
        make_config()
        core_mail.run_and_record(send_to="you@example.com")
        row = EmailLog.objects.get()
        self.assertFalse(row.ok)
        self.assertIn("Sender address rejected", row.error)

    def test_connection_only_test_writes_no_log(self):
        make_config(host="")   # fails at config stage, no send requested
        core_mail.run_and_record()
        self.assertEqual(EmailLog.objects.count(), 0)


class EmailLogViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_log_page_renders_entries(self):
        EmailLog.record("a@b.com", "A subject", ok=False, error="it broke")
        response = self.client.get(reverse("core:email-log"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A subject")
        self.assertContains(response, "it broke")

    def test_ack_clears_unseen_failures(self):
        EmailLog.record("a@b.com", "A", ok=False, error="x")
        self.assertTrue(EmailLog.objects.failures_unseen().exists())
        response = self.client.post(reverse("core:email-log-ack"))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EmailLog.objects.failures_unseen().exists())

    def test_ack_honours_a_same_origin_next(self):
        EmailLog.record("a@b.com", "A", ok=False, error="x")
        response = self.client.post(
            reverse("core:email-log-ack"), {"next": reverse("core:dashboard")}
        )
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_dashboard_banner_reflects_unseen_failures(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertFalse(response.context["email_failures_unseen"])
        EmailLog.record("a@b.com", "A", ok=False, error="x")
        response = self.client.get(reverse("core:dashboard"))
        self.assertTrue(response.context["email_failures_unseen"])

    def test_clear_resets_the_configuration(self):
        make_config()
        response = self.client.post(reverse("core:email-clear"))
        self.assertEqual(response.status_code, 302)
        config = EmailSettings.load()
        self.assertFalse(config.enabled)
        self.assertEqual(config.host, "")
        self.assertEqual(config.from_email, "")
        self.assertEqual(config.password, "")
        self.assertIsNone(config.last_test_at)
