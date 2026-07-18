from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import UserSettings


class SettingsTabsTest(TestCase):
    """The settings page renders one tab at a time, so each tab's Save posts only
    that tab's fields. The other tabs' values must survive that partial POST."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_display_tab_shows_only_its_own_fields(self):
        resp = self.client.get("/settings/?tab=display")
        self.assertContains(resp, 'name="week_start"')
        self.assertNotContains(resp, 'name="projection_method"')

    def test_analytics_tab_shows_only_its_own_fields(self):
        resp = self.client.get("/settings/?tab=analytics")
        self.assertContains(resp, 'name="projection_method"')
        self.assertNotContains(resp, 'name="week_start"')

    def test_unknown_tab_falls_back_to_the_first(self):
        resp = self.client.get("/settings/?tab=nonsense")
        self.assertContains(resp, 'name="week_start"')

    def test_signin_tab_is_offered_without_an_idp(self):
        # Standalone installs still need somewhere to change the password, and
        # somewhere to learn that SSO exists.
        resp = self.client.get("/settings/?tab=display")
        self.assertContains(resp, "tab=signin")

    def test_signin_tab_without_an_idp_explains_how_to_enable_it(self):
        resp = self.client.get("/settings/?tab=signin")
        self.assertContains(resp, "Not configured")
        self.assertContains(resp, "OIDC_CLIENT_SECRET")

    def test_password_can_be_managed_without_an_idp(self):
        # The set/change-password modal used to be gated behind sso_enabled,
        # which left standalone owners with no in-app way to change it.
        resp = self.client.get("/settings/?tab=signin")
        self.assertContains(resp, 'id="passwordModal"')
        self.assertContains(resp, 'value="set_password"')
        # Turning the password off needs a linked IdP to fall back on, so that
        # action must stay hidden here.
        self.assertNotContains(resp, "Turn off password sign-in")

    def test_password_change_works_without_an_idp(self):
        resp = self.client.post("/settings/sign-in/", {
            "action": "set_password",
            "new_password1": "Str0ng!Passw0rd",
            "new_password2": "Str0ng!Passw0rd",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("tab=signin", resp["Location"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Str0ng!Passw0rd"))

    def test_saving_one_tab_leaves_the_other_untouched(self):
        settings_row = UserSettings.load()
        settings_row.projection_trailing_months = 9
        settings_row.projection_method = "avg"
        settings_row.save()

        resp = self.client.post("/settings/", {
            "tab": "display",
            "week_start": "6",
            "show_shift_type_colors": "on",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn("tab=display", resp["Location"])

        settings_row = UserSettings.load()
        self.assertEqual(settings_row.week_start, 6)
        # Absent from a display POST, so it must keep its stored value rather
        # than falling back to the field default.
        self.assertEqual(settings_row.projection_trailing_months, 9)
        self.assertEqual(settings_row.projection_method, "avg")

    def test_unchecked_box_on_the_active_tab_still_clears(self):
        # The flip side: a checkbox the active tab *does* render is genuinely
        # absent when unticked, and must be written as False.
        settings_row = UserSettings.load()
        settings_row.show_help_button = True
        settings_row.save()

        self.client.post("/settings/", {"tab": "display", "week_start": "0"})

        settings_row = UserSettings.load()
        self.assertFalse(settings_row.show_help_button)
        self.assertFalse(settings_row.show_shift_type_colors)
