from decimal import Decimal

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError


class Workplace(models.Model):
    """A job / workplace with its employment and payroll configuration."""

    class EmploymentType(models.TextChoices):
        HOURLY = "hourly", "Hourly"
        SALARIED = "salaried", "Salaried"

    class TaxCardType(models.TextChoices):
        HOVEDKORT = "hovedkort", "Hovedkort (primary)"
        BIKORT = "bikort", "Bikort (secondary)"

    class VacationType(models.TextChoices):
        FERIEKONTO = "feriekonto", "Paid to FerieKonto"
        ACCRUED = "accrued", "Accrued as leave balance"

    class FritvalgsPayoutType(models.TextChoices):
        ACCRUES = "accrues", "Accrues (saved up)"
        PAID_MONTHLY = "paid_monthly", "Paid out every month"

    # Basic info
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    # Customisation (optional)
    icon = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Bootstrap Icons class, e.g. 'bi-briefcase'.",
    )
    custom_icon = models.FileField(
        upload_to="workplace_icons/",
        blank=True,
        default="",
        help_text="Custom icon (PNG or SVG, max 512 KB).",
    )
    color = models.CharField(
        max_length=7, blank=True, default="",
        help_text="Background hex colour for the avatar circle, e.g. '#6366f1'.",
    )
    accent_color = models.CharField(
        max_length=7, blank=True, default="",
        help_text="Accent hex colour for icon tint and page theming.",
    )

    # Employment
    employment_type = models.CharField(
        max_length=10,
        choices=EmploymentType.choices,
        default=EmploymentType.SALARIED,
    )
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Hourly rate in DKK (for hourly employment).",
    )
    monthly_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monthly gross salary in DKK (for salaried employment).",
    )

    # Weekly hours
    weekly_hours_fixed = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fixed weekly hours. Leave blank if using min/max range.",
    )
    weekly_hours_min = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum weekly hours (range mode).",
    )
    weekly_hours_max = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum weekly hours (range mode).",
    )

    # Payroll period
    payroll_period_start_day = models.IntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text=(
            "Day of month when payroll period starts. "
            "E.g. 20 means the 20th of previous month to the 19th of current month."
        ),
    )

    # Tax card
    tax_card_type = models.CharField(
        max_length=10,
        choices=TaxCardType.choices,
        default=TaxCardType.HOVEDKORT,
    )

    # Vacation
    vacation_type = models.CharField(
        max_length=10,
        choices=VacationType.choices,
        default=VacationType.FERIEKONTO,
    )

    # Pension & fritvalgskonto
    pension_employee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Employee's own pension contribution (%).",
    )
    pension_employer_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Employer's pension contribution (%).",
    )
    fritvalgskonto_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Fritvalgskonto percentage of gross salary.",
    )
    fritvalgskonto_payout_type = models.CharField(
        max_length=15,
        choices=FritvalgsPayoutType.choices,
        default=FritvalgsPayoutType.ACCRUES,
        help_text="Whether fritvalgskonto accrues or is paid out monthly.",
    )

    # Ferietillæg (vacation supplement)
    ferietillaeg_enabled = models.BooleanField(
        default=False,
        help_text="Enable ferietillæg (vacation supplement).",
    )
    ferietillaeg_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text="Ferietillæg as % of yearly gross, typically ~1%.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.employment_type == self.EmploymentType.HOURLY and not self.hourly_rate:
            raise ValidationError("Hourly employment requires an hourly rate.")
        if (
            self.employment_type == self.EmploymentType.SALARIED
            and not self.monthly_salary
        ):
            raise ValidationError("Salaried employment requires a monthly salary.")

        # Weekly hours: must define either fixed, or both min/max
        has_fixed = self.weekly_hours_fixed is not None
        has_range = (
            self.weekly_hours_min is not None and self.weekly_hours_max is not None
        )
        if not has_fixed and not has_range:
            raise ValidationError(
                "Specify either fixed weekly hours or a min/max range."
            )
        if has_range and self.weekly_hours_min > self.weekly_hours_max:
            raise ValidationError(
                "Minimum weekly hours cannot exceed maximum weekly hours."
            )

    @property
    def expected_weekly_hours(self):
        """Return the nominal weekly hours (fixed, or midpoint of range)."""
        if self.weekly_hours_fixed is not None:
            return self.weekly_hours_fixed
        if self.weekly_hours_min is not None and self.weekly_hours_max is not None:
            return (self.weekly_hours_min + self.weekly_hours_max) / 2
        return None

    @property
    def pension_total_percent(self):
        """Sum of employee and employer pension contributions."""
        return self.pension_employee_percent + self.pension_employer_percent

    @property
    def effective_hourly_rate(self):
        """Hourly rate adjusted for ferietillæg, fritvalgskonto, and employee pension.

        effective = base × (1 + ferietillaeg%/100 + fritvalgskonto%/100 − pension_employee%/100)
        """
        if not self.hourly_rate:
            return None
        factor = (
            Decimal("1")
            + (self.ferietillaeg_percent / Decimal("100") if self.ferietillaeg_enabled else Decimal("0"))
            + self.fritvalgskonto_percent / Decimal("100")
            - self.pension_employee_percent / Decimal("100")
        )
        return (self.hourly_rate * factor).quantize(Decimal("0.01"))

    @property
    def total_hourly_rate(self):
        """Effective hourly rate plus employer pension contributions.

        total = effective + base × pension_employer%/100
        """
        eff = self.effective_hourly_rate
        if eff is None:
            return None
        employer = (self.hourly_rate * self.pension_employer_percent / Decimal("100")).quantize(Decimal("0.01"))
        return eff + employer

    @property
    def vacation_days_per_month(self):
        """Fixed Danish vacation accrual: 2.08 days per month."""
        from decimal import Decimal
        return Decimal("2.08")
