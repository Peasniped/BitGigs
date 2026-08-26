"""Danish tax domain — the date-versioned personal tax profile and the ATP
brackets the payroll engine prices contributions from.

Carved out of ``core`` in Phase A2 of the BitBase extraction: ``core`` is the
platform half of the app (settings, mail, auth, onboarding machinery) and must
not carry one country's payroll rules. The tables keep their historical
``core_*`` names until the rename migration, so no data moves.
"""
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class TaxProfile(models.Model):
    """
    Date-versioned personal tax settings.
    The profile with the latest effective_from <= a given date is used.
    """

    monthly_deduction = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Monthly personal tax deduction (personfradrag) in DKK.",
    )
    tax_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Combined municipality + health tax rate (trækprocent).",
    )
    church_tax_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Church tax rate (kirkeskat). Set to 0 if not a member.",
    )
    am_bidrag_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=8.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="AM-bidrag (labour market contribution), typically 8%.",
    )
    effective_from = models.DateField(
        unique=True,
        help_text="This profile applies from this date forward.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"TaxProfile from {self.effective_from} ({self.tax_percent}%)"


class ATPConfiguration(models.Model):
    """
    Date-versioned ATP (Arbejdsmarkedets Tillægspension) settings.
    ATP brackets define employee/employer contributions based on monthly hours.
    """

    effective_from = models.DateField(
        unique=True,
        help_text="This ATP configuration applies from this date forward.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"ATP from {self.effective_from}"


class ATPBracket(models.Model):
    """
    A single ATP contribution bracket.
    hours_min (inclusive), hours_max (inclusive or None for open-ended).
    """

    configuration = models.ForeignKey(
        ATPConfiguration,
        on_delete=models.CASCADE,
        related_name="brackets",
    )
    hours_min = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Minimum monthly hours (inclusive).",
    )
    hours_max = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum monthly hours (inclusive). Leave blank for open-ended.",
    )
    employee_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Employee ATP contribution in DKK.",
    )
    employer_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Employer ATP contribution in DKK.",
    )

    class Meta:
        ordering = ["hours_min"]

    def __str__(self):
        upper = f"–{self.hours_max}" if self.hours_max else "+"
        return f"{self.hours_min}{upper} h/mo → emp {self.employee_amount} kr."
