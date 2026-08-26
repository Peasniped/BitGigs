from datetime import date
from decimal import Decimal

from django.test import TestCase

from tax.models import TaxProfile


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
