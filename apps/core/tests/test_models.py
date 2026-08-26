from decimal import Decimal

from django.test import TestCase

from core.models import UserSettings


class UserSettingsModelTest(TestCase):
    def test_singleton_behavior(self):
        s1 = UserSettings.load()
        s1.week_start = 6
        s1.save()

        s2 = UserSettings.load()
        self.assertEqual(s2.pk, 1)
        self.assertEqual(s2.week_start, 6)

        # Saving again still uses pk=1
        s2.week_start = 0
        s2.save()
        self.assertEqual(UserSettings.objects.count(), 1)

    def test_show_shift_type_colors_defaults_on_and_roundtrips(self):
        from core.forms import UserSettingsForm

        settings = UserSettings.load()
        self.assertTrue(settings.show_shift_type_colors)  # on by default

        # An unchecked checkbox is absent from the POST → turns the setting off.
        form = UserSettingsForm(
            data={
                "theme": "light",
                "accent_color": "#6366f1",
                "secondary_color": "#9fd6fb",
                "week_start": 0,
                "projection_method": "ema",
                "projection_trailing_months": 6,
            },
            instance=settings,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertFalse(UserSettings.load().show_shift_type_colors)
