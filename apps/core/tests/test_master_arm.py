from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import EmailSettings, MailConnection


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()


class MasterArmStateTests(LoggedInTestCase):
    """The master-arm box reports whether a subsystem can actually do its job.

    Its tint is applied by settings.js from ``data-arm-ready`` — the *downstream*
    half of the question (is there something to send through?), kept separate
    from the switch itself so toggling the switch re-tints without a save.
    """

    def _connection(self):
        return MailConnection.objects.create(
            name="Default", host="smtp.example.com", port=587,
            from_email="bitgigs@example.com", is_default=True,
        )

    def test_email_arm_is_not_ready_without_a_connection(self):
        resp = self.client.get("/settings/?tab=email")
        self.assertContains(resp, 'data-arm-ready="0"')
        # The warning is rendered but hidden — settings.js reveals it only while
        # the switch is on, since a missing connection doesn't matter while
        # nothing is being sent.
        self.assertContains(resp, "data-arm-warn")

    def test_email_arm_is_ready_once_a_connection_exists(self):
        self._connection()
        resp = self.client.get("/settings/?tab=email")
        self.assertContains(resp, 'data-arm-ready="1"')
        self.assertNotContains(resp, "data-arm-warn")

    def test_email_arm_readiness_ignores_the_master_switch(self):
        """Keyed on is_configured (which folds the switch in), the box would sit
        red until the very switch it reports on had already been saved."""
        self._connection()
        config = EmailSettings.load()
        config.enabled = False
        config.save()
        resp = self.client.get("/settings/?tab=email")
        self.assertContains(resp, 'data-arm-ready="1"')

    def test_calendar_arm_warning_names_the_missing_piece(self):
        """A fresh install has *both* problems — no connection and mail off.
        The connection has to win, or the warning sends the owner to flip a
        switch the form refuses to accept until a connection exists."""
        resp = self.client.get("/settings/?tab=calendar")
        self.assertContains(resp, 'data-arm-ready="0"')
        self.assertContains(resp, "No mail connection is set up")
        self.assertNotContains(resp, "Outgoing mail is switched off")

        # A connection exists, but outgoing mail is switched off — a different
        # problem, and now the actionable one.
        self._connection()
        config = EmailSettings.load()
        config.enabled = False
        config.save()
        resp = self.client.get("/settings/?tab=calendar")
        self.assertContains(resp, 'data-arm-ready="0"')
        self.assertContains(resp, "Outgoing mail is switched off")

    def test_calendar_arm_is_ready_when_mail_can_carry_invites(self):
        self._connection()
        config = EmailSettings.load()
        config.enabled = True
        config.save()
        resp = self.client.get("/settings/?tab=calendar")
        self.assertContains(resp, 'data-arm-ready="1"')


class PasswordResetMirrorTests(LoggedInTestCase):
    """allow_password_reset lives on EmailSettings but is a sign-in concern, so
    the Sign-in tab edits the same field rather than linking to the Email tab."""

    def test_signin_tab_renders_it_as_an_editable_switch(self):
        resp = self.client.get("/settings/?tab=signin")
        self.assertContains(resp, 'name="allow_password_reset"')
        # Saves through the same scope as the Email tab — one field, one writer.
        self.assertContains(resp, 'data-autosave="email"')

    def test_toggling_it_from_signin_writes_email_settings(self):
        config = EmailSettings.load()
        config.allow_password_reset = True
        config.save()

        # An unchecked switch posts no value at all.
        self.client.post(reverse("core:password-signin"), {"action": "password_reset"})
        config.refresh_from_db()
        self.assertFalse(config.allow_password_reset)

        self.client.post(reverse("core:password-signin"),
                         {"action": "password_reset", "allow_password_reset": "on"})
        config.refresh_from_db()
        self.assertTrue(config.allow_password_reset)

    def test_it_returns_to_the_signin_tab(self):
        resp = self.client.post(reverse("core:password-signin"),
                                {"action": "password_reset"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("tab=signin", resp.headers["Location"])

    def test_warns_when_it_is_on_but_no_mail_server_exists(self):
        config = EmailSettings.load()
        config.allow_password_reset = True
        config.save()
        resp = self.client.get("/settings/?tab=signin")
        self.assertContains(resp, "no working mail server")
        self.assertContains(resp, "data-signin-reset-warn>")

    def test_the_warning_is_rendered_but_hidden_while_it_is_off(self):
        """Hidden rather than absent: the switch saves without a reload, so
        settings.js has to be able to reveal it the moment it's turned on."""
        config = EmailSettings.load()
        config.allow_password_reset = False
        config.save()
        resp = self.client.get("/settings/?tab=signin")
        self.assertContains(resp, "data-signin-reset-warn hidden")
