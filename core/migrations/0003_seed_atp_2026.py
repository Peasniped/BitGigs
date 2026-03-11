"""
Data migration: seed default 2026 Danish ATP employee rates.

ATP-satser 2026 for lønmodtager:
  117+ timer/md:   99,00 kr.
  78–116 timer/md: 66,00 kr.
  39–77 timer/md:  33,00 kr.
  Under 39 timer/md: 0 kr.
"""

from datetime import date
from decimal import Decimal

from django.db import migrations


def seed_atp_2026(apps, schema_editor):
    ATPConfiguration = apps.get_model("core", "ATPConfiguration")
    ATPBracket = apps.get_model("core", "ATPBracket")

    config, created = ATPConfiguration.objects.get_or_create(
        effective_from=date(2026, 1, 1),
    )

    if not created:
        # Already seeded — skip to allow re-running safely
        return

    brackets = [
        # (hours_min, hours_max, employee_amount, employer_amount)
        (Decimal("0"),   Decimal("38.99"),  Decimal("0"),     Decimal("0")),
        (Decimal("39"),  Decimal("77.99"),  Decimal("33.00"), Decimal("0")),
        (Decimal("78"),  Decimal("116.99"), Decimal("66.00"), Decimal("0")),
        (Decimal("117"), None,              Decimal("99.00"), Decimal("0")),
    ]

    for h_min, h_max, emp, empr in brackets:
        ATPBracket.objects.create(
            configuration=config,
            hours_min=h_min,
            hours_max=h_max,
            employee_amount=emp,
            employer_amount=empr,
        )


def remove_atp_2026(apps, schema_editor):
    ATPConfiguration = apps.get_model("core", "ATPConfiguration")
    ATPConfiguration.objects.filter(
        effective_from=date(2026, 1, 1),
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_atpconfiguration_atpbracket"),
    ]

    operations = [
        migrations.RunPython(seed_atp_2026, remove_atp_2026),
    ]
