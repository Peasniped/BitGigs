from datetime import date as _date
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


SENTINEL_DATE = _date(2000, 1, 1)


def migrate_to_contracts(apps, schema_editor):
    Workplace = apps.get_model("workplaces", "Workplace")
    WorkplaceContract = apps.get_model("workplaces", "WorkplaceContract")
    ContractTermSet = apps.get_model("workplaces", "ContractTermSet")
    PayRate = apps.get_model("workplaces", "PayRate")

    for wp in Workplace.objects.all():
        start_date = wp.contract_start_date or SENTINEL_DATE

        contract = WorkplaceContract.objects.create(
            workplace=wp,
            name="",
            start_date=start_date,
            end_date=wp.contract_end_date,
        )

        base_fields = dict(
            contract=contract,
            effective_from=start_date,
            employment_type=wp.employment_type,
            hourly_rate=wp.hourly_rate,
            monthly_salary=wp.monthly_salary,
            weekly_hours_fixed=wp.weekly_hours_fixed,
            weekly_hours_min=wp.weekly_hours_min,
            weekly_hours_max=wp.weekly_hours_max,
            payroll_period_start_day=wp.payroll_period_start_day,
            tax_card_type=wp.tax_card_type,
            tax_pull_day=wp.tax_pull_day,
            vacation_type=wp.vacation_type,
            pension_employee_percent=wp.pension_employee_percent,
            pension_employer_percent=wp.pension_employer_percent,
            fritvalgskonto_enabled=wp.fritvalgskonto_enabled,
            fritvalgskonto_percent=wp.fritvalgskonto_percent,
            fritvalgskonto_payout_type=wp.fritvalgskonto_payout_type,
            ferietillaeg_enabled=wp.ferietillaeg_enabled,
            ferietillaeg_percent=wp.ferietillaeg_percent,
            ferietillaeg_payout_months=wp.ferietillaeg_payout_months,
            default_shift_start_time=wp.default_shift_start_time,
            default_shift_end_time=wp.default_shift_end_time,
            default_shift_break_minutes=wp.default_shift_break_minutes,
            default_shift_type=wp.default_shift_type,
            hour_goal_type=wp.hour_goal_type,
            hour_goal_min=wp.hour_goal_min,
            hour_goal_max=wp.hour_goal_max,
        )

        # If there's a PayRate with the same date as start_date, use its rate.
        try:
            initial_rate = PayRate.objects.get(workplace=wp, effective_from=start_date)
            base_fields["hourly_rate"] = initial_rate.hourly_rate
            base_fields["monthly_salary"] = initial_rate.monthly_salary
        except PayRate.DoesNotExist:
            pass

        ContractTermSet.objects.create(**base_fields)

        # Additional termsets for every other PayRate date.
        for rate in PayRate.objects.filter(workplace=wp).order_by("effective_from"):
            if rate.effective_from == start_date:
                continue
            extra = dict(base_fields)
            extra["effective_from"] = rate.effective_from
            extra["hourly_rate"] = rate.hourly_rate
            extra["monthly_salary"] = rate.monthly_salary
            ContractTermSet.objects.create(**extra)


def reverse_migrate(apps, schema_editor):
    apps.get_model("workplaces", "WorkplaceContract").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workplaces", "0003_workplace_contract_dates"),
    ]

    operations = [
        # ── 1. Create WorkplaceContract ──────────────────────────────────
        migrations.CreateModel(
            name="WorkplaceContract",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, max_length=200, help_text="Optional label, e.g. 'Physics Lab' or 'Adjunkt 2024'.")),
                ("start_date", models.DateField(help_text="Date this employment arrangement starts.")),
                ("end_date", models.DateField(blank=True, null=True, help_text="Date this arrangement ends (leave blank if still active).")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("workplace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="contracts", to="workplaces.workplace")),
            ],
            options={"ordering": ["workplace", "start_date"]},
        ),

        # ── 2. Create ContractTermSet ────────────────────────────────────
        migrations.CreateModel(
            name="ContractTermSet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("effective_from", models.DateField(help_text="These terms apply from this date forward within the contract.")),
                ("employment_type", models.CharField(
                    choices=[("hourly", "Hourly"), ("salaried", "Salaried")],
                    default="salaried", max_length=10,
                )),
                ("hourly_rate", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, help_text="Hourly rate in DKK (for hourly employment).")),
                ("monthly_salary", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, help_text="Monthly gross salary in DKK (for salaried employment).")),
                ("weekly_hours_fixed", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, help_text="Fixed weekly hours. Leave blank if using min/max range.")),
                ("weekly_hours_min", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, help_text="Minimum weekly hours (range mode).")),
                ("weekly_hours_max", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, help_text="Maximum weekly hours (range mode).")),
                ("payroll_period_start_day", models.IntegerField(
                    default=1,
                    validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(31)],
                    help_text="Day of month when payroll period starts.",
                )),
                ("tax_card_type", models.CharField(
                    choices=[("hovedkort", "Hovedkort (primary)"), ("bikort", "Bikort (secondary)")],
                    default="hovedkort", max_length=10,
                )),
                ("tax_pull_day", models.IntegerField(
                    default=18,
                    validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(28)],
                    help_text="Day of the month when the employer pulls your tax card from SKAT.",
                )),
                ("vacation_type", models.CharField(
                    choices=[("feriekonto", "Paid to FerieKonto"), ("accrued", "Accrued as leave balance")],
                    default="feriekonto", max_length=10,
                )),
                ("pension_employee_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5, help_text="Employee's own pension contribution (%).")),
                ("pension_employer_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5, help_text="Employer's pension contribution (%).")),
                ("fritvalgskonto_enabled", models.BooleanField(default=False)),
                ("fritvalgskonto_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5, help_text="Fritvalgskonto percentage of gross salary.")),
                ("fritvalgskonto_payout_type", models.CharField(
                    choices=[("accrues", "Accrues (saved up)"), ("paid_monthly", "Paid out every month")],
                    default="accrues", max_length=15,
                )),
                ("ferietillaeg_enabled", models.BooleanField(default=False)),
                ("ferietillaeg_percent", models.DecimalField(decimal_places=2, default=Decimal("1.00"), max_digits=5, help_text="Ferietillæg as % of yearly gross, typically ~1%.")),
                ("ferietillaeg_payout_months", models.CharField(blank=True, default="5,8", max_length=50, help_text="Comma-separated month numbers for payout.")),
                ("default_shift_start_time", models.TimeField(blank=True, null=True)),
                ("default_shift_end_time", models.TimeField(blank=True, null=True)),
                ("default_shift_break_minutes", models.PositiveIntegerField(default=0)),
                ("default_shift_type", models.CharField(
                    choices=[("on_site", "On-site"), ("remote", "Remote"), ("sick_leave", "Sick leave (with pay)"), ("paid_absence", "Paid absence"), ("vacation", "Vacation")],
                    default="on_site", max_length=15,
                )),
                ("hour_goal_type", models.CharField(
                    choices=[("weekly", "Per week"), ("monthly", "Per month")],
                    blank=True, default="", max_length=10,
                )),
                ("hour_goal_min", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ("hour_goal_max", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("contract", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="term_sets", to="workplaces.workplacecontract")),
            ],
            options={
                "ordering": ["-effective_from"],
                "constraints": [
                    models.UniqueConstraint(fields=("contract", "effective_from"), name="unique_termset_per_date"),
                ],
            },
        ),

        # ── 3. Migrate data ──────────────────────────────────────────────
        migrations.RunPython(migrate_to_contracts, reverse_code=reverse_migrate),

        # ── 4. Strip employment fields from Workplace ────────────────────
        migrations.RemoveField(model_name="workplace", name="employment_type"),
        migrations.RemoveField(model_name="workplace", name="hourly_rate"),
        migrations.RemoveField(model_name="workplace", name="monthly_salary"),
        migrations.RemoveField(model_name="workplace", name="weekly_hours_fixed"),
        migrations.RemoveField(model_name="workplace", name="weekly_hours_min"),
        migrations.RemoveField(model_name="workplace", name="weekly_hours_max"),
        migrations.RemoveField(model_name="workplace", name="payroll_period_start_day"),
        migrations.RemoveField(model_name="workplace", name="tax_card_type"),
        migrations.RemoveField(model_name="workplace", name="tax_pull_day"),
        migrations.RemoveField(model_name="workplace", name="vacation_type"),
        migrations.RemoveField(model_name="workplace", name="pension_employee_percent"),
        migrations.RemoveField(model_name="workplace", name="pension_employer_percent"),
        migrations.RemoveField(model_name="workplace", name="fritvalgskonto_enabled"),
        migrations.RemoveField(model_name="workplace", name="fritvalgskonto_percent"),
        migrations.RemoveField(model_name="workplace", name="fritvalgskonto_payout_type"),
        migrations.RemoveField(model_name="workplace", name="ferietillaeg_enabled"),
        migrations.RemoveField(model_name="workplace", name="ferietillaeg_percent"),
        migrations.RemoveField(model_name="workplace", name="ferietillaeg_payout_months"),
        migrations.RemoveField(model_name="workplace", name="default_shift_start_time"),
        migrations.RemoveField(model_name="workplace", name="default_shift_end_time"),
        migrations.RemoveField(model_name="workplace", name="default_shift_break_minutes"),
        migrations.RemoveField(model_name="workplace", name="default_shift_type"),
        migrations.RemoveField(model_name="workplace", name="hour_goal_type"),
        migrations.RemoveField(model_name="workplace", name="hour_goal_min"),
        migrations.RemoveField(model_name="workplace", name="hour_goal_max"),
        migrations.RemoveField(model_name="workplace", name="contract_start_date"),
        migrations.RemoveField(model_name="workplace", name="contract_end_date"),

        # ── 5. Delete PayRate (absorbed into ContractTermSet) ────────────
        migrations.DeleteModel(name="PayRate"),
    ]
