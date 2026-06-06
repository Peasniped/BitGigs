"""Tests for the CSV-backed rate loader (core.rate_loaders)."""
import tempfile
from decimal import Decimal
from datetime import date
from pathlib import Path

from django.test import TestCase

from core.models import ATPConfiguration, ATPBracket
from core.rate_loaders import load_atp_rates, read_rate_csv


_HEADER = "effective_from,hours_min,hours_max,employee_amount,employer_amount\n"
_ROWS_2026 = (
    "2026-01-01,0,38.99,0,0\n"
    "2026-01-01,39,77.99,33.00,0\n"
    "2026-01-01,78,116.99,66.00,0\n"
    "2026-01-01,117,,99.00,0\n"
)


def _write_csv(body):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    tmp.write(body)
    tmp.close()
    return tmp.name


class LoadAtpRatesTest(TestCase):
    def setUp(self):
        # post_migrate already seeded the real CSV into the test DB; start clean.
        ATPConfiguration.objects.all().delete()

    def test_creates_config_and_brackets(self):
        counts = load_atp_rates(path=_write_csv(_HEADER + _ROWS_2026))
        self.assertEqual(counts["configs_created"], 1)
        self.assertEqual(counts["brackets_created"], 4)

        config = ATPConfiguration.objects.get(effective_from=date(2026, 1, 1))
        brackets = list(config.brackets.all())
        self.assertEqual(len(brackets), 4)
        # Open-ended top bracket has hours_max = None
        top = brackets[-1]
        self.assertEqual(top.hours_min, Decimal("117"))
        self.assertIsNone(top.hours_max)
        self.assertEqual(top.employee_amount, Decimal("99.00"))

    def test_idempotent_skips_existing(self):
        path = _write_csv(_HEADER + _ROWS_2026)
        load_atp_rates(path=path)
        counts = load_atp_rates(path=path)
        self.assertEqual(counts["configs_created"], 0)
        self.assertEqual(counts["configs_skipped"], 1)
        self.assertEqual(ATPBracket.objects.count(), 4)

    def test_force_replaces_brackets(self):
        load_atp_rates(path=_write_csv(_HEADER + _ROWS_2026))
        changed = _HEADER + "2026-01-01,0,,123.00,45.00\n"
        counts = load_atp_rates(path=_write_csv(changed), force=True)
        self.assertEqual(counts["configs_updated"], 1)
        brackets = list(ATPConfiguration.objects.get(effective_from=date(2026, 1, 1)).brackets.all())
        self.assertEqual(len(brackets), 1)
        self.assertEqual(brackets[0].employee_amount, Decimal("123.00"))
        self.assertEqual(brackets[0].employer_amount, Decimal("45.00"))

    def test_multiple_years(self):
        body = _HEADER + _ROWS_2026 + "2027-01-01,0,,105.00,0\n"
        counts = load_atp_rates(path=_write_csv(body))
        self.assertEqual(counts["configs_created"], 2)
        self.assertEqual(ATPConfiguration.objects.count(), 2)

    def test_missing_file_is_noop(self):
        counts = load_atp_rates(path=str(Path(tempfile.gettempdir()) / "does_not_exist_atp.csv"))
        self.assertEqual(counts["configs_created"], 0)
        self.assertEqual(ATPConfiguration.objects.count(), 0)

    def test_read_rate_csv_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_rate_csv("definitely_not_a_real_file.csv")
