"""Mail configuration: connections, secret storage, the staged connection test,
and the password-reset flow it unlocks."""
import re
import smtplib
import socket
import ssl
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import mail as core_mail
from core.crypto import decrypt_secret, encrypt_secret
from core.mail_backend import DbConfiguredEmailBackend
from core.testing import LoggedInTestCase
from core.models import EmailLog, EmailSettings, MailConnection, UserSettings
from core.mail import FAILED, OK, SKIPPED


def make_config(*, enabled=True, allow_password_reset=True, **overrides):
    """Create a default ``MailConnection`` and, unless disabled, turn mail on with
    it as the fallback for every role. Returns the connection.

    ``enabled`` / ``allow_password_reset`` land on the ``EmailSettings`` singleton;
    everything else is a connection field."""
    password = overrides.pop("password", "hunter2")
    fields = dict(
        name="Default", host="smtp.example.com", port=587,
        security=MailConnection.SECURITY_STARTTLS, username="me@example.com",
        from_email="me@example.com", from_name="BitGigs", timeout=5, is_default=True,
    )
    fields.update(overrides)
    conn = MailConnection(**fields)
    if password:
        conn.password = password
    conn.save()
    es = EmailSettings.load()
    es.enabled = enabled
    es.allow_password_reset = allow_password_reset
    es.save()
    return conn


# A full, valid connection-save POST body (the connection modal's form).
def conn_post(**overrides):
    body = {
        "name": "Default", "host": "smtp.example.com", "port": "587",
        "security": "starttls", "username": "me@example.com", "password": "hunter2",
        "from_email": "me@example.com", "from_name": "BitGigs", "timeout": "10",
    }
    body.update(overrides)
    return body


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
        conn = make_config()
        with override_settings(SECRET_KEY="a-completely-different-key"):
            conn.refresh_from_db()
            self.assertTrue(conn.password_unreadable)
            self.assertIsNone(conn.password)

    def test_environment_override_wins(self):
        conn = make_config()
        with override_settings(EMAIL_PASSWORD_OVERRIDE="from-the-env"):
            self.assertEqual(conn.password, "from-the-env")
            self.assertTrue(conn.password_from_env)


class ConfiguredFlagTests(TestCase):
    def test_disabled_is_not_configured(self):
        make_config(enabled=False)
        self.assertFalse(EmailSettings.load().is_configured)

    def test_missing_host_is_not_configured(self):
        make_config(host="")
        self.assertFalse(EmailSettings.load().is_configured)

    def test_configured_when_enabled_with_a_usable_connection(self):
        make_config()
        self.assertTrue(EmailSettings.load().is_configured)
        self.assertTrue(EmailSettings.load().is_configured_for(EmailSettings.ROLE_CALENDAR))

    def test_role_uses_its_assigned_connection(self):
        make_config()
        other = MailConnection.objects.create(name="Personal", host="smtp.p.com",
                                               from_email="me@p.com")
        es = EmailSettings.load()
        es.calendar_connection = other
        es.save()
        self.assertEqual(es.connection_for(EmailSettings.ROLE_CALENDAR), other)
        self.assertEqual(es.connection_for(EmailSettings.ROLE_SYSTEM).from_email,
                         "me@example.com")

    def test_from_address_uses_the_display_name(self):
        conn = make_config(from_name="BitGigs")
        self.assertEqual(core_mail.from_address(conn), "BitGigs <me@example.com>")

    def test_from_address_without_a_name_is_bare(self):
        conn = make_config(from_name="")
        self.assertEqual(core_mail.from_address(conn), "me@example.com")


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
        conn = make_config()
        with override_settings(SECRET_KEY="rotated"):
            conn.refresh_from_db()
            result = core_mail.diagnose(conn)
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
        self.assertEqual(stages["auth"].status, OK)
        self.assertEqual(stages["send"].status, FAILED)
        self.assertIn("me@example.com", stages["send"].hint)

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_run_and_record_stores_the_outcome(self, _r, _c, smtp):
        conn = make_config()
        core_mail.run_and_record()
        conn.refresh_from_db()
        self.assertTrue(conn.last_test_ok)
        self.assertIsNotNone(conn.last_test_at)


class MailConnectionViewTests(TestCase):
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
        self.client.post(reverse("core:mail-connection-save"), conn_post())
        conn = MailConnection.objects.get()
        self.assertEqual(conn.password, "hunter2")
        self.assertNotIn("hunter2", conn.password_encrypted)

    def test_first_connection_becomes_default(self):
        self.client.post(reverse("core:mail-connection-save"), conn_post())
        self.assertTrue(MailConnection.objects.get().is_default)

    def test_changing_the_config_clears_the_stored_test_result(self):
        conn = make_config(last_test_ok=True, last_test_at=timezone.now())
        self.client.post(reverse("core:mail-connection-save"),
                         conn_post(pk=conn.pk, host="smtp.changed.com", password=""))
        conn.refresh_from_db()
        self.assertEqual(conn.host, "smtp.changed.com")
        self.assertIsNone(conn.last_test_ok)
        self.assertIsNone(conn.last_test_at)

    def test_save_and_test_redirects_with_the_test_flag(self):
        response = self.client.post(reverse("core:mail-connection-save"),
                                    conn_post(run_test="1"))
        pk = MailConnection.objects.get().pk
        self.assertIn(f"test={pk}", response["Location"])

    def test_plain_save_carries_no_test_flag(self):
        response = self.client.post(reverse("core:mail-connection-save"), conn_post())
        self.assertNotIn("test=", response["Location"])

    def test_blank_password_keeps_the_stored_one(self):
        conn = make_config()
        self.client.post(reverse("core:mail-connection-save"),
                         conn_post(pk=conn.pk, password=""))
        conn.refresh_from_db()
        self.assertEqual(conn.password, "hunter2")

    def test_clear_password_removes_it(self):
        conn = make_config()
        self.client.post(reverse("core:mail-connection-save"),
                         conn_post(pk=conn.pk, password="", clear_password="on"))
        conn.refresh_from_db()
        self.assertEqual(conn.password, "")

    def test_incomplete_connection_is_rejected(self):
        response = self.client.post(reverse("core:mail-connection-save"),
                                    conn_post(host=""))
        self.assertEqual(response.status_code, 200)  # re-rendered with errors
        self.assertFalse(MailConnection.objects.exists())

    def test_delete_promotes_a_new_default(self):
        a = make_config()
        b = MailConnection.objects.create(name="B", host="smtp.b.com",
                                          from_email="b@b.com")
        self.client.post(reverse("core:mail-connection-delete"), {"pk": a.pk})
        b.refresh_from_db()
        self.assertFalse(MailConnection.objects.filter(pk=a.pk).exists())
        self.assertTrue(b.is_default)

    def test_make_default_moves_the_flag(self):
        a = make_config()
        b = MailConnection.objects.create(name="B", host="smtp.b.com",
                                          from_email="b@b.com")
        self.client.post(reverse("core:mail-connection-default"), {"pk": b.pk})
        a.refresh_from_db(); b.refresh_from_db()
        self.assertTrue(b.is_default)
        self.assertFalse(a.is_default)

    def test_master_enable_needs_a_usable_connection(self):
        # No connection yet → enabling is rejected.
        response = self.client.post(reverse("core:email-settings"),
                                    {"enabled": "on", "allow_password_reset": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EmailSettings.load().enabled)

    def test_master_enable_with_a_connection(self):
        make_config(enabled=False)
        self.client.post(reverse("core:email-settings"),
                         {"enabled": "on", "allow_password_reset": "on"})
        self.assertTrue(EmailSettings.load().enabled)

    def test_role_assignment_saves(self):
        make_config()
        other = MailConnection.objects.create(name="Personal", host="smtp.p.com",
                                              from_email="me@p.com")
        self.client.post(reverse("core:email-settings"), {
            "enabled": "on", "allow_password_reset": "on",
            "calendar_connection": other.pk,
        })
        self.assertEqual(EmailSettings.load().calendar_connection, other)

    def test_section_saves_are_independent(self):
        # The master switch and the role map are separate cards/forms; saving one
        # must not clear the other's fields (they share one model row).
        make_config()  # enabled=True
        other = MailConnection.objects.create(name="Personal", host="smtp.p.com",
                                              from_email="me@p.com")
        # Save only the role map → enabled must survive.
        self.client.post(reverse("core:email-settings"),
                         {"section": "roles", "calendar_connection": other.pk})
        es = EmailSettings.load()
        self.assertTrue(es.enabled)
        self.assertEqual(es.calendar_connection, other)
        # Save only the switches → the role map must survive.
        self.client.post(reverse("core:email-settings"),
                         {"section": "switches", "enabled": "on"})
        es = EmailSettings.load()
        self.assertEqual(es.calendar_connection, other)
        self.assertFalse(es.allow_password_reset)  # absent checkbox = off, as rendered

    def test_test_endpoint_rejects_a_bad_recipient(self):
        make_config()
        response = self.client.post(reverse("core:email-test"), {"send_to": "not-an-email"})
        self.assertEqual(response.status_code, 400)

    def test_test_endpoint_returns_stages(self):
        conn = make_config(host="")
        response = self.client.post(reverse("core:email-test"), {"connection": conn.pk})
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["stages"][0]["key"], "config")

    def test_test_endpoint_requires_a_login(self):
        self.client.logout()
        response = self.client.post(reverse("core:email-test"))
        self.assertEqual(response.status_code, 302)

    def test_test_endpoint_reports_unseen_failure_flag(self):
        conn = make_config(host="")  # fails at config, nothing sent → no failure logged
        payload = self.client.post(reverse("core:email-test"),
                                   {"connection": conn.pk}).json()
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

    def test_recovery_link_shows_even_without_mail(self):
        # With no mail server the emailed-link button is hidden, but the recovery
        # link + console instructions must still be there — changepassword always
        # works, and hiding recovery entirely would strand a standalone owner.
        response = self.client.get("/accounts/login/")
        self.assertContains(response, "Forgot your password?")
        self.assertContains(response, "changepassword")
        self.assertNotContains(response, "Email me a reset link")

    def test_login_page_never_leaks_the_owner_username(self):
        # The login page is public; the console-recovery hint must use a
        # placeholder, never the owner's real address.
        response = self.client.get("/accounts/login/")
        self.assertNotContains(response, "owner@example.com")

    def test_end_to_end(self):
        make_config()
        response = self.client.post(
            "/accounts/password_reset/", {"email": "owner@example.com"}
        )
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.from_email, "BitGigs <me@example.com>")

        link = re.search(r"/accounts/reset/\S+", message.body).group(0)
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
        self.client.post("/accounts/password_reset/", {"email": "owner@example.com"})
        self.assertEqual(len(mail.outbox), 5)
        cache.clear()


class EmailLogModelTests(TestCase):
    def test_record_marks_success_seen_and_failure_unseen(self):
        ok_row = EmailLog.record("a@b.com", "Hi", ok=True)
        fail_row = EmailLog.record("a@b.com", "Hi", ok=False, error="nope")
        self.assertIsNotNone(ok_row.acknowledged_at)
        self.assertIsNone(fail_row.acknowledged_at)
        self.assertQuerySetEqual(EmailLog.objects.failures_unseen(), [fail_row])

    def test_record_keeps_the_connection_name(self):
        row = EmailLog.record("a@b.com", "Hi", ok=True, connection_name="No-reply")
        self.assertEqual(row.connection_name, "No-reply")

    def test_record_prunes_to_the_cap(self):
        with mock.patch.object(EmailLog, "PRUNE_KEEP", 3):
            for i in range(6):
                EmailLog.record("a@b.com", f"msg {i}", ok=True)
        self.assertEqual(EmailLog.objects.count(), 3)
        self.assertEqual(EmailLog.objects.first().subject, "msg 5")

    def test_backend_logs_a_successful_send_with_the_connection_name(self):
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
        self.assertEqual(row.connection_name, "Default")

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

    def test_backend_role_selects_the_connection(self):
        make_config()
        personal = MailConnection.objects.create(name="Personal", host="smtp.p.com",
                                                 from_email="me@p.com")
        es = EmailSettings.load()
        es.calendar_connection = personal
        es.save()
        backend = DbConfiguredEmailBackend(role=EmailSettings.ROLE_CALENDAR)
        self.assertEqual(backend.host, "smtp.p.com")
        self.assertEqual(backend.connection_name, "Personal")

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
        make_config(host="")
        core_mail.run_and_record()
        self.assertEqual(EmailLog.objects.count(), 0)


class EmailLogViewTests(LoggedInTestCase):

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
        self.assertEqual(MailConnection.objects.count(), 0)


class MessageIdTests(TestCase):
    """A Message-ID whose domain is the container hostname reads as spam, so
    every send path derives it from the From address instead."""

    def _stamped(self, from_email):
        message = mail.EmailMultiAlternatives(from_email=from_email)
        core_mail.stamp_message_id(message)
        return message.extra_headers["Message-ID"]

    def test_helper_uses_the_from_domain(self):
        self.assertTrue(self._stamped("robot@zink.nu").endswith("@zink.nu>"))

    def test_helper_reads_the_domain_out_of_a_display_name_form(self):
        self.assertTrue(self._stamped("BitGigs <robot@zink.nu>").endswith("@zink.nu>"))

    def test_helper_keeps_an_explicit_message_id(self):
        message = mail.EmailMultiAlternatives(from_email="robot@zink.nu")
        message.extra_headers["Message-ID"] = "<kept@elsewhere>"
        core_mail.stamp_message_id(message)
        self.assertEqual(message.extra_headers["Message-ID"], "<kept@elsewhere>")

    def test_send_mail_stamps_the_from_domain(self):
        connection = mail.get_connection(
            "django.core.mail.backends.locmem.EmailBackend"
        )
        core_mail.send_mail("Subj", "Body", "to@example.com",
                            config=make_config(from_email="robot@zink.nu"),
                            connection=connection)
        self.assertTrue(mail.outbox[0].message()["Message-ID"].endswith("@zink.nu>"))

    @mock.patch("core.mail.smtplib.SMTP")
    @mock.patch("core.mail.socket.create_connection")
    @mock.patch("core.mail.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("10.0.0.1", 587))])
    def test_diagnostic_test_send_stamps_the_from_domain(self, _r, _c, smtp):
        core_mail.diagnose(make_config(from_email="robot@zink.nu"),
                           send_to="dest@example.com")
        sent = smtp.return_value.send_message.call_args.args[0]
        self.assertTrue(sent["Message-ID"].endswith("@zink.nu>"))

    def test_db_backend_stamps_django_mail(self):
        make_config(from_email="robot@zink.nu")
        with mock.patch.object(
            DbConfiguredEmailBackend, "_log_message"
        ), mock.patch(
            "django.core.mail.backends.smtp.EmailBackend.send_messages",
            return_value=1,
        ):
            message = mail.EmailMessage(
                "Subj", "Body", "robot@zink.nu", ["to@example.com"],
            )
            DbConfiguredEmailBackend().send_messages([message])
        self.assertTrue(message.extra_headers["Message-ID"].endswith("@zink.nu>"))


class FailureStreakTests(TestCase):
    """"This connection keeps refusing" — derived from the send log, not kept as
    a counter, so it can't drift and a success needs no reset step."""

    def _log(self, ok, name="Default"):
        EmailLog.record(to="to@example.com", subject="s", ok=ok, connection_name=name)

    def test_streak_counts_only_the_unbroken_run_of_failures(self):
        self._log(False)
        self._log(True)
        self._log(False)
        self._log(False)
        self.assertEqual(core_mail.failure_streak("Default"), 2)
        self.assertFalse(core_mail.connection_is_failing("Default"))

    def test_three_in_a_row_is_a_failing_connection(self):
        for _ in range(3):
            self._log(False)
        self.assertTrue(core_mail.connection_is_failing("Default"))

    def test_a_success_clears_it(self):
        for _ in range(3):
            self._log(False)
        self._log(True)
        self.assertEqual(core_mail.failure_streak("Default"), 0)

    def test_other_connections_are_counted_separately(self):
        for _ in range(3):
            self._log(False, name="Work")
        self.assertFalse(core_mail.connection_is_failing("Default"))
        self.assertEqual(core_mail.failure_streak(""), 0)
