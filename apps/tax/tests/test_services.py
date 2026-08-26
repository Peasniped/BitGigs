"""
Tests for the tax calculation service.
Covers the Danish payroll processing order:
  Gross → ATP → Pension → AM-bidrag → A-skat (with fradrag for hovedkort) → Net
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from tax.models import TaxProfile, ATPConfiguration, ATPBracket
from tax.services import TaxCalculationService, ATPService


class TaxCalculationServiceTest(TestCase):
    def setUp(self):
        self.profile = TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"),
            tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.70"),
            am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2026, 1, 1),
        )

    def test_basic_calculation(self):
        """Test standard Danish tax calculation on 30,000 DKK gross (hovedkort, no ATP/pension)."""
        result = TaxCalculationService.calculate(
            Decimal("30000.00"), profile=self.profile
        )

        # AM-bidrag = 30000 * 0.08 = 2400
        self.assertEqual(result.am_bidrag, Decimal("2400.00"))

        # Income after AM = 30000 - 2400 = 27600
        self.assertEqual(result.income_after_am, Decimal("27600.00"))

        # Taxable income = 27600 - 4000 = 23600 (hovedkort: apply fradrag)
        self.assertEqual(result.taxable_income, Decimal("23600.00"))

        # A-skat = 23600 * (37 + 0.70) / 100 = 23600 * 0.3770 = 8897.20
        self.assertEqual(result.a_skat, Decimal("8897.20"))

        # Net = 30000 - 0 - 0 - 2400 - 8897.20 = 18702.80
        self.assertEqual(result.net_pay, Decimal("18702.80"))

    def test_zero_gross(self):
        result = TaxCalculationService.calculate(
            Decimal("0"), profile=self.profile
        )
        self.assertEqual(result.net_pay, Decimal("0.00"))
        self.assertEqual(result.am_bidrag, Decimal("0.00"))
        self.assertEqual(result.a_skat, Decimal("0.00"))

    def test_low_income_no_tax(self):
        """If income after AM-bidrag is below the deduction, no A-skat is due."""
        result = TaxCalculationService.calculate(
            Decimal("3000.00"), profile=self.profile
        )
        # AM-bidrag = 3000 * 0.08 = 240
        # Income after AM = 2760
        # Taxable income = max(2760 - 4000, 0) = 0
        self.assertEqual(result.taxable_income, Decimal("0.00"))
        self.assertEqual(result.a_skat, Decimal("0.00"))
        # Net = 3000 - 240 = 2760
        self.assertEqual(result.net_pay, Decimal("2760.00"))

    def test_no_church_tax(self):
        """Profile with 0% church tax."""
        profile = TaxProfile.objects.create(
            monthly_deduction=Decimal("4000.00"),
            tax_percent=Decimal("37.00"),
            church_tax_percent=Decimal("0.00"),
            am_bidrag_percent=Decimal("8.00"),
            effective_from=date(2025, 1, 1),
        )
        result = TaxCalculationService.calculate(
            Decimal("30000.00"), profile=profile
        )
        # A-skat = 23600 * 0.37 = 8732.00
        self.assertEqual(result.a_skat, Decimal("8732.00"))
        # Net = 30000 - 2400 - 8732 = 18868.00
        self.assertEqual(result.net_pay, Decimal("18868.00"))

    def test_no_profile_returns_gross(self):
        """Without any profile, the full gross is returned as net."""
        TaxProfile.objects.all().delete()
        result = TaxCalculationService.calculate(Decimal("25000.00"))
        self.assertEqual(result.net_pay, Decimal("25000.00"))
        self.assertEqual(result.am_bidrag, Decimal("0.00"))

    def test_get_active_profile_date_versioning(self):
        """Ensure the correct profile is selected based on date."""
        older_profile = TaxProfile.objects.create(
            monthly_deduction=Decimal("3500.00"),
            tax_percent=Decimal("38.00"),
            effective_from=date(2024, 1, 1),
        )

        # As of 2026-06-01, should get the 2026 profile
        profile = TaxCalculationService.get_active_profile(date(2026, 6, 1))
        self.assertEqual(profile, self.profile)

        # As of 2025-06-01, should get the 2024 profile
        profile = TaxCalculationService.get_active_profile(date(2025, 6, 1))
        self.assertEqual(profile, older_profile)

    def test_bikort_calculation(self):
        """
        Bikort (secondary tax card) — fradrag is NOT applied.
        The test uses the same profile but passes tax_card_type='bikort'.
        """
        result = TaxCalculationService.calculate(
            Decimal("10000.00"),
            profile=self.profile,
            tax_card_type="bikort",
        )
        # AM-bidrag = 10000 * 0.08 = 800
        self.assertEqual(result.am_bidrag, Decimal("800.00"))
        # Income after AM = 9200
        # Bikort: no fradrag → taxable = 9200
        self.assertEqual(result.taxable_income, Decimal("9200.00"))
        # A-skat = 9200 * 0.3770 = 3468.40
        self.assertEqual(result.a_skat, Decimal("3468.40"))
        # Net = 10000 - 800 - 3468.40 = 5731.60
        self.assertEqual(result.net_pay, Decimal("5731.60"))

    def test_with_atp_and_pension(self):
        """Test full processing order: gross → ATP → pension → AM → A-skat → net."""
        result = TaxCalculationService.calculate(
            Decimal("30000.00"),
            profile=self.profile,
            employee_pension=Decimal("600.00"),   # 2% of 30000
            employee_atp=Decimal("99.00"),
        )
        # AM basis = 30000 - 99 - 600 = 29301
        self.assertEqual(result.am_basis, Decimal("29301.00"))
        # AM-bidrag = 29301 * 0.08 = 2344.08
        self.assertEqual(result.am_bidrag, Decimal("2344.08"))
        # Income after AM = 29301 - 2344.08 = 26956.92
        self.assertEqual(result.income_after_am, Decimal("26956.92"))
        # Taxable = 26956.92 - 4000 = 22956.92 (hovedkort)
        self.assertEqual(result.taxable_income, Decimal("22956.92"))
        # A-skat = 22956.92 * 0.3770 = 8654.76 (rounded)
        self.assertEqual(result.a_skat, Decimal("8654.76"))
        # Net = 30000 - 99 - 600 - 2344.08 - 8654.76 = 18302.16
        self.assertEqual(result.net_pay, Decimal("18302.16"))


class ATPServiceBracketTest(TestCase):
    """ATP brackets are lower-bound tiers: fractional hours between integer tier
    edges must resolve to the lower tier, never fall into a gap."""

    def setUp(self):
        # post_migrate seeds the real CSV into the test DB; start from a clean slate.
        ATPConfiguration.objects.all().delete()
        config = ATPConfiguration.objects.create(effective_from=date(2024, 1, 1))
        for h_min, h_max, emp, empr in [
            (0, 38, "0", "0"),
            (39, 77, "33.00", "66.00"),
            (78, 116, "66.00", "132.00"),
            (117, None, "99.00", "198.00"),
        ]:
            ATPBracket.objects.create(
                configuration=config,
                hours_min=Decimal(h_min),
                hours_max=Decimal(h_max) if h_max is not None else None,
                employee_amount=Decimal(emp),
                employer_amount=Decimal(empr),
            )
        self.as_of = date(2024, 6, 1)

    def _emp(self, hours):
        return ATPService.get_contributions(Decimal(hours), as_of=self.as_of)[0]

    def test_tier_edges_and_gaps(self):
        self.assertEqual(self._emp("38"), Decimal("0"))
        self.assertEqual(self._emp("38.5"), Decimal("0"))   # below 39 → 0
        self.assertEqual(self._emp("39"), Decimal("33.00"))
        self.assertEqual(self._emp("77.5"), Decimal("33.00"))  # gap edge, was 0
        self.assertEqual(self._emp("78"), Decimal("66.00"))
        self.assertEqual(self._emp("116.5"), Decimal("66.00"))  # gap edge, was 0
        self.assertEqual(self._emp("117"), Decimal("99.00"))
        self.assertEqual(self._emp("200"), Decimal("99.00"))   # open-ended top

    def test_no_config_returns_zero(self):
        ATPConfiguration.objects.all().delete()
        self.assertEqual(
            ATPService.get_contributions(Decimal("100"), as_of=self.as_of),
            (Decimal("0"), Decimal("0")),
        )
