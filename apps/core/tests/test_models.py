from datetime import date
from decimal import Decimal

from django.test import TestCase

from core.models import TaxProfile, UserSettings


class TaxProfileModelTest(TestCase):
    def test_str_representation(self):
        profile = TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"),
            tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.70"),
            am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )
        self.assertIn("2026-01-01", str(profile))
        self.assertIn("37.00%", str(profile))

    def test_ordering_by_effective_from_desc(self):
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4000"),
            tax_percent=Decimal("37"),
            effective_from=date(2025, 1, 1),
        )
        TaxProfile.objects.create(
            monthly_deduction=Decimal("4200"),
            tax_percent=Decimal("36"),
            effective_from=date(2026, 1, 1),
        )
        profiles = list(TaxProfile.objects.all())
        self.assertEqual(profiles[0].effective_from, date(2026, 1, 1))
        self.assertEqual(profiles[1].effective_from, date(2025, 1, 1))


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
                "week_start": 0,
                "projection_method": "ema",
                "projection_trailing_months": 6,
            },
            instance=settings,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertFalse(UserSettings.load().show_shift_type_colors)
