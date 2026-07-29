"""Save-on-change: the settings panes carry no Save button, so one endpoint
writes one field at a time (``core.settings_fields`` + ``SettingsFieldView``).

The interesting part isn't that a field saves — it's what a single-field POST is
*allowed* to touch. A whole-form submit is normally what bounds that; here the
bound is each scope's own field set, so most of these tests are about a request
that names a real field on a real model through the wrong scope.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from calendar_sync.models import CalendarInviteSettings, TITLE_ONSITE_DEFAULT
from core.models import EmailSettings, MailConnection, UserSettings
from core.settings_fields import SettingsFieldError, save_field


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()
        self.url = reverse("core:settings-field")

    def save(self, scope, field, value=None, **extra):
        data = {"scope": scope, "field": field, **extra}
        if value is not None:
            data[field] = value
        return self.client.post(self.url, data)


class ScopedSaveTests(LoggedInTestCase):
    def test_a_display_switch_saves(self):
        UserSettings.load()  # ensure the singleton exists
        resp = self.save("display", "show_help_button")   # nothing posted = off
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertFalse(UserSettings.load().show_help_button)

        resp = self.save("display", "show_help_button", "on")
        self.assertTrue(resp.json()["ok"])
        self.assertTrue(UserSettings.load().show_help_button)

    def test_a_feature_switch_saves(self):
        resp = self.save("features", "feature_analytics")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(UserSettings.load().feature_analytics)

    def test_saving_one_field_leaves_its_neighbours_alone(self):
        """The whole point of scoping: a single-field POST must not blank every
        other field the way a partial form submit would."""
        settings = UserSettings.load()
        settings.week_start = 6
        settings.show_shift_type_colors = False
        settings.save()

        self.save("display", "show_help_button", "on")

        settings = UserSettings.load()
        self.assertEqual(settings.week_start, 6)
        self.assertFalse(settings.show_shift_type_colors)

    def test_a_calendar_setting_saves(self):
        resp = self.save("calendar", "send_to_personal", "on")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(CalendarInviteSettings.load().send_to_personal)

    def test_the_stored_value_comes_back_when_the_form_normalised_it(self):
        """A blank invite title falls back to the built-in default, so the
        control has to be told what actually landed — otherwise it sits there
        empty, describing a setting that isn't blank."""
        resp = self.save("calendar", "default_title_onsite", "")
        self.assertEqual(resp.json()["value"], TITLE_ONSITE_DEFAULT)
        self.assertEqual(
            CalendarInviteSettings.load().default_title_onsite, TITLE_ONSITE_DEFAULT
        )

    def test_a_role_assignment_saves(self):
        conn = MailConnection.objects.create(
            name="Post", host="smtp.example.com", port=587,
            from_email="bitgigs@example.com", is_default=True,
        )
        resp = self.save("email_roles", "calendar_connection", str(conn.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(EmailSettings.load().calendar_connection, conn)


class AllowlistTests(LoggedInTestCase):
    """A scope's surviving ``form.fields`` is the allowlist. These all name real
    fields on the real model — they're refused because the *scope* doesn't own
    them, which is what stops one pane writing another pane's settings."""

    def test_unknown_scope_is_refused(self):
        resp = self.save("nonsense", "show_help_button", "on")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])

    def test_a_field_from_another_tab_is_refused(self):
        resp = self.save("display", "feature_payroll")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(UserSettings.load().feature_payroll)

    def test_a_field_from_another_email_section_is_refused(self):
        """The Email tab's two cards are two scopes: the master switch can't be
        used to reassign a role, or vice versa."""
        resp = self.save("email", "system_connection", "")
        self.assertEqual(resp.status_code, 400)

        # Turned off first, so "still off" afterwards means the refused write
        # genuinely didn't land — the field's own default is True, which would
        # make an assertion against a fresh row prove nothing.
        config = EmailSettings.load()
        config.allow_password_reset = False
        config.save()

        resp = self.save("email_roles", "allow_password_reset", "on")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(EmailSettings.load().allow_password_reset)

    def test_save_field_raises_rather_than_guessing(self):
        with self.assertRaises(SettingsFieldError):
            save_field("display", "feature_payroll", {})
        with self.assertRaises(SettingsFieldError):
            save_field("nope", "show_help_button", {})


class ValidationTests(LoggedInTestCase):
    def test_mail_cannot_be_enabled_without_a_connection(self):
        """The form's own rule, unchanged by saving one field at a time — the
        message has to come back so the switch can explain why it moved back."""
        resp = self.save("email", "enabled", "on")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("connection", resp.json()["error"].lower())
        self.assertFalse(EmailSettings.load().enabled)

    def test_mail_can_be_enabled_once_a_connection_exists(self):
        MailConnection.objects.create(
            name="Post", host="smtp.example.com", port=587,
            from_email="bitgigs@example.com", is_default=True,
        )
        resp = self.save("email", "enabled", "on")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(EmailSettings.load().enabled)

    def test_an_invalid_value_is_reported_and_not_stored(self):
        settings = UserSettings.load()
        before = settings.projection_trailing_months
        resp = self.save("features", "projection_trailing_months", "not-a-number")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            UserSettings.load().projection_trailing_months, before
        )


class PaneMarkupTests(LoggedInTestCase):
    """The panes have to actually be wired to the endpoint — and to have lost
    their Save buttons, which is what the wiring replaces."""

    def test_each_pane_carries_the_endpoint_and_autosave_controls(self):
        for tab in ("display", "features", "email", "calendar", "signin"):
            with self.subTest(tab=tab):
                resp = self.client.get(f"/settings/?tab={tab}")
                self.assertContains(resp, "data-settings-autosave-url")
                self.assertContains(resp, "data-autosave=")

    def test_the_panes_lost_their_save_buttons(self):
        """Named per pane rather than looking for any submit button — base.html
        has its own (log out, the theme toggle), so a blanket check would pass
        or fail for the wrong reason."""
        gone = {
            # Without a ?next there is no Back link either, so the row itself
            # should be absent.
            "display": "settings-save-row",
            "features": "settings-save-row",
            "email": "Save settings",
            "calendar": "Save invite settings",
        }
        for tab, needle in gone.items():
            with self.subTest(tab=tab):
                resp = self.client.get(f"/settings/?tab={tab}")
                self.assertNotContains(resp, needle)

    def test_a_next_still_leaves_a_way_back(self):
        resp = self.client.get("/settings/?tab=display&next=/dashboard/")
        self.assertContains(resp, "settings-save-row")
        self.assertContains(resp, "Back")

    def test_password_reset_renders_as_a_switch_not_a_bare_checkbox(self):
        resp = self.client.get("/settings/?tab=email")
        self.assertContains(resp, 'id="id_allow_password_reset"')
        # role="switch" is what makes it the app's on/off switch rather than
        # crispy's default checkbox.
        self.assertContains(resp, 'role="switch"')
