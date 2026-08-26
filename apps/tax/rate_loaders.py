"""
Load editable reference-rate data from CSV files in DATA_DIR into the database.

The CSV is the shipped/editable source; the DB tables remain the runtime source
of truth (so the admin UI and date-versioning keep working). `read_rate_csv` is
generic and meant to be reused by future rate tables (e.g. SU rates).
"""
import csv
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction


def read_rate_csv(filename):
    """Read DATA_DIR/<filename> and return a list of row dicts (DictReader).

    Raises FileNotFoundError with a clear message if the file is missing.
    """
    path = settings.DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Rate data file not found: {path}")
    with open(path, newline="", encoding="utf-8") as fh:
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(fh)
        ]


def _dec(value):
    return Decimal(value) if value not in (None, "") else None


@transaction.atomic
def load_atp_rates(*, path=None, force=False):
    """Seed ATPConfiguration/ATPBracket rows from a CSV.

    Rows are grouped by `effective_from`. Each group becomes one ATPConfiguration
    with its brackets. Idempotent: existing configurations are skipped unless
    `force=True`, in which case their brackets are replaced to match the CSV.
    No-ops gracefully if the file is missing or empty.

    `path` overrides the default DATA_DIR/atp_rates.csv (used by tests).
    Returns a dict of counts.
    """
    from .models import ATPConfiguration, ATPBracket

    counts = {"configs_created": 0, "configs_updated": 0, "configs_skipped": 0, "brackets_created": 0}

    try:
        if path is not None:
            with open(path, newline="", encoding="utf-8") as fh:
                rows = [
                    {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                    for row in csv.DictReader(fh)
                ]
        else:
            rows = read_rate_csv("atp_rates.csv")
    except FileNotFoundError:
        return counts

    # Group rows by effective_from
    groups = {}
    for row in rows:
        eff = row.get("effective_from")
        if not eff:
            continue
        groups.setdefault(eff, []).append(row)

    for eff_str, bracket_rows in groups.items():
        eff = date.fromisoformat(eff_str)
        config, created = ATPConfiguration.objects.get_or_create(effective_from=eff)

        if not created and not force:
            counts["configs_skipped"] += 1
            continue

        if not created:
            # force: replace this config's brackets to match the CSV
            config.brackets.all().delete()
            counts["configs_updated"] += 1
        else:
            counts["configs_created"] += 1

        for row in bracket_rows:
            ATPBracket.objects.create(
                configuration=config,
                hours_min=_dec(row.get("hours_min")) or Decimal("0"),
                hours_max=_dec(row.get("hours_max")),
                employee_amount=_dec(row.get("employee_amount")) or Decimal("0"),
                employer_amount=_dec(row.get("employer_amount")) or Decimal("0"),
            )
            counts["brackets_created"] += 1

    return counts
