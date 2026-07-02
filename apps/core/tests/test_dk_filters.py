from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import formats, translation

from core.templatetags.dk_filters import danish_number as dk
from core.utils import parse_danish_decimal


class DkFilterTest(SimpleTestCase):
    """The dk filter formats numbers Danish-style with thousands grouping."""

    def setUp(self):
        # The format module is keyed to the active locale; en resolves to the
        # bitgigs/formats/en override (comma decimals, period thousands).
        cm = translation.override("en-us")
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_default_two_decimals_with_grouping(self):
        self.assertEqual(dk(Decimal("1234.56")), "1.234,56")

    def test_zero_decimals_rounds_half_up(self):
        self.assertEqual(dk(Decimal("1234.5"), 0), "1.235")

    def test_one_decimal(self):
        self.assertEqual(dk(Decimal("1234.56"), 1), "1.234,6")

    def test_small_value_keeps_two_decimals(self):
        self.assertEqual(dk(Decimal("5"), 2), "5,00")

    def test_negative_uses_unicode_minus(self):
        self.assertEqual(dk(Decimal("-1234.56")), "−1.234,56")

    def test_negative_zero_has_no_sign(self):
        self.assertEqual(dk(Decimal("-0.004"), 2), "0,00")

    def test_none_returns_empty_string(self):
        self.assertEqual(dk(None), "")

    def test_empty_string_returns_empty_string(self):
        self.assertEqual(dk(""), "")

    def test_invalid_decimals_arg_falls_back_to_two(self):
        self.assertEqual(dk(Decimal("1234.56"), "x"), "1.234,56")


class ParseDanishDecimalTest(SimpleTestCase):
    def setUp(self):
        cm = translation.override("en-us")
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_parses_danish_formatted(self):
        self.assertEqual(parse_danish_decimal("1.234,56"), Decimal("1234.56"))

    def test_parses_comma_decimal(self):
        self.assertEqual(parse_danish_decimal("37,5"), Decimal("37.5"))

    def test_strips_thousands_separator(self):
        self.assertEqual(parse_danish_decimal("5.000,00"), Decimal("5000.00"))

    def test_plain_integer(self):
        self.assertEqual(parse_danish_decimal("1"), Decimal("1"))

    def test_empty_returns_none(self):
        self.assertIsNone(parse_danish_decimal(""))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_danish_decimal("abc"))


class AutoLocalizationTest(SimpleTestCase):
    """Guards the config: decimals localize automatically; ints never group."""

    def setUp(self):
        cm = translation.override("en-us")
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def test_bare_decimal_gets_comma(self):
        self.assertEqual(formats.localize(Decimal("37.5")), "37,5")

    def test_bare_integer_is_not_grouped(self):
        # Years / database ids must stay plain (USE_THOUSAND_SEPARATOR is off).
        self.assertEqual(formats.localize(2026), "2026")
