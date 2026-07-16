from django.conf import settings
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


class UserSettings(models.Model):
    """Singleton-style global settings for the app."""

    WEEK_START_CHOICES = [
        (0, "Monday"),
        (6, "Sunday"),
    ]

    PROJECTION_METHOD_CHOICES = [
        ("ema", "Exponential moving average (recent months weighted higher)"),
        ("avg", "Simple average"),
    ]

    week_start = models.IntegerField(
        choices=WEEK_START_CHOICES,
        default=0,
        help_text="0 = Monday, 6 = Sunday",
    )

    show_shift_type_colors = models.BooleanField(
        default=True,
        help_text="Colour calendar shift chips by type (on-site / remote / sick / …).",
    )

    # Analytics projection
    projection_method = models.CharField(
        max_length=10,
        choices=PROJECTION_METHOD_CHOICES,
        default="ema",
        help_text="How to estimate future hours from your historical shifts.",
    )
    projection_trailing_months = models.PositiveIntegerField(
        default=6,
        help_text="Number of past months used to compute the projection.",
    )
    use_planned_shifts = models.BooleanField(
        default=True,
        help_text="When a future month has planned shifts, use them for its income "
                  "instead of the trailing-average projection.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Settings"
        verbose_name_plural = "User Settings"

    def __str__(self):
        return f"Settings (week starts {self.get_week_start_display()})"

    def save(self, *args, **kwargs):
        # Enforce singleton: always overwrite pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class OnboardingDraft(models.Model):
    """In-progress onboarding input, held per user until the final Finish writes
    the real rows. Stored in the DB (not just the session) so the data survives
    logging out mid-onboarding or switching browser. Deleted on completion.

    ``data`` is a dict of ``{step_key: raw_post_payload}`` for the tax /
    workplace / contract / terms steps (each payload already passed the step
    form's ``is_valid()``)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="onboarding_draft",
    )
    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Onboarding draft for {self.user} ({', '.join(self.data) or 'empty'})"
