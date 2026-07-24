"""Theme (light/dark/auto) and accent-colour settings."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.forms import UserSettingsForm
from core.models import UserSettings
from core.utils import hex_to_rgb_str


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


class SetThemeViewTest(LoggedInTestCase):
    def test_valid_values_persist(self):
        for value in ("dark", "auto", "light"):
            response = self.client.post(
                reverse("core:set-theme"), {"theme": value, "next": "/"}
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(UserSettings.load().theme, value)

    def test_invalid_value_ignored(self):
        settings = UserSettings.load()
        settings.theme = "dark"
        settings.save()
        self.client.post(reverse("core:set-theme"), {"theme": "zebra", "next": "/"})
        self.assertEqual(UserSettings.load().theme, "dark")

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse("core:set-theme")).status_code, 405)

    def test_same_origin_next_honoured(self):
        response = self.client.post(
            reverse("core:set-theme"), {"theme": "dark", "next": "/planning/"}
        )
        self.assertEqual(response.url, "/planning/")

    def test_offsite_next_refused(self):
        response = self.client.post(
            reverse("core:set-theme"), {"theme": "dark", "next": "//evil.com"}
        )
        self.assertEqual(response.url, f"{reverse('core:settings')}?tab=display")


class ThemeRenderingTest(LoggedInTestCase):
    def _set(self, **fields):
        settings = UserSettings.load()
        for name, value in fields.items():
            setattr(settings, name, value)
        settings.save()

    def test_dark_attribute_rendered(self):
        self._set(theme="dark")
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, 'data-bs-theme="dark"')

    def test_auto_renders_light_plus_prepaint_script(self):
        self._set(theme="auto")
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, 'data-bs-theme="light"')
        self.assertContains(response, "data-theme-auto")
        self.assertContains(response, "prefers-color-scheme")

    def test_light_has_no_auto_marker(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, 'data-bs-theme="light"')
        self.assertNotContains(response, "data-theme-auto")

    def test_default_accent_renders_no_inline_override(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertNotContains(response, "--primary:#")

    def test_custom_accent_rendered_inline(self):
        self._set(accent_color="#14b8a6")
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "--primary:#14b8a6")
        self.assertContains(response, "--primary-rgb:20,184,166")

    def test_more_menu_toggle_states(self):
        response = self.client.get(reverse("core:dashboard"))
        self.assertContains(response, "Dark mode")  # light active → offer dark
        self._set(theme="dark")
        self.assertContains(self.client.get(reverse("core:dashboard")), "Light mode")
        self._set(theme="auto")
        self.assertContains(self.client.get(reverse("core:dashboard")), "Auto theme active")


class SettingsFormTest(LoggedInTestCase):
    DISPLAY_POST = {
        "tab": "display", "theme": "dark", "accent_color": "#EC4899",
        "secondary_color": "#9FD6FB",
        "week_start": "0", "show_shift_type_colors": "on", "show_help_button": "on",
    }

    def test_display_tab_saves_theme_and_accent(self):
        response = self.client.post(reverse("core:settings"), self.DISPLAY_POST)
        self.assertEqual(response.status_code, 302)
        settings = UserSettings.load()
        self.assertEqual(settings.theme, "dark")
        # normalised to lowercase on clean
        self.assertEqual(settings.accent_color, "#ec4899")

    def test_display_tab_does_not_clobber_analytics(self):
        settings = UserSettings.load()
        settings.projection_trailing_months = 9
        settings.save()
        self.client.post(reverse("core:settings"), self.DISPLAY_POST)
        self.assertEqual(UserSettings.load().projection_trailing_months, 9)

    def test_analytics_tab_does_not_clobber_theme_or_accent(self):
        settings = UserSettings.load()
        settings.theme = "dark"
        settings.accent_color = "#14b8a6"
        settings.save()
        self.client.post(reverse("core:settings"), {
            "tab": "analytics", "projection_method": "ema",
            "projection_trailing_months": "6", "use_planned_shifts": "on",
        })
        settings = UserSettings.load()
        self.assertEqual(settings.theme, "dark")
        self.assertEqual(settings.accent_color, "#14b8a6")

    def test_invalid_accent_rejected(self):
        for bad in ("zzz", "#12345", "6366f1", "#12345g"):
            form = UserSettingsForm(
                {**self.DISPLAY_POST, "accent_color": bad}, tab="display",
                instance=UserSettings.load(),
            )
            self.assertFalse(form.is_valid(), bad)
            self.assertIn("accent_color", form.errors)

    def test_accent_picker_only_on_display_tab(self):
        response = self.client.get(reverse("core:settings") + "?tab=display")
        self.assertContains(response, "data-accent-picker")
        response = self.client.get(reverse("core:settings") + "?tab=analytics")
        self.assertNotContains(response, "data-accent-picker")


class HexToRgbStrTest(TestCase):
    def test_conversion(self):
        self.assertEqual(hex_to_rgb_str("#6366f1"), "99,102,241")
        self.assertEqual(hex_to_rgb_str("#000000"), "0,0,0")
        self.assertEqual(hex_to_rgb_str("ffffff"), "255,255,255")
