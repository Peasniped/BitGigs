import calendar as _cal
from datetime import date as _date
from decimal import Decimal

from django.db import models
from django.db.models import Q
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils.text import slugify


class Workplace(models.Model):
    """A workplace / employer — appearance and identification only.

    Employment settings live on WorkplaceContract → ContractTermSet.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=200, unique=True,
        help_text="URL-friendly short name. Auto-generated from name, but editable.",
    )
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "workplace"
            slug = base_slug
            n = 1
            while Workplace.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_active(self) -> bool:
        """True when the workplace has at least one currently active contract."""
        today = _date.today()
        return self.contracts.filter(start_date__lte=today).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        ).exists()

    # ------------------------------------------------------------------
    # Contract helpers
    # ------------------------------------------------------------------

    def active_contract_on(self, d: _date) -> "WorkplaceContract | None":
        """Return the contract active on date d, or None."""
        return (
            self.contracts.filter(start_date__lte=d)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=d))
            .order_by("-start_date")
            .first()
        )

    def contracts_in_period(self, start: _date, end: _date):
        """Return contracts overlapping [start, end]."""
        return self.contracts.filter(start_date__lte=end).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=start)
        )

    def active_termset_on(self, d: _date) -> "ContractTermSet | None":
        """Convenience shortcut: active ContractTermSet on date d."""
        contract = self.active_contract_on(d)
        if contract is None:
            return None
        return contract.active_termset_on(d)

    def has_active_contract_in_month(self, year: int, month: int) -> bool:
        """True if any contract overlaps the given calendar month."""
        last_day = _cal.monthrange(year, month)[1]
        month_start = _date(year, month, 1)
        month_end = _date(year, month, last_day)
        return self.contracts_in_period(month_start, month_end).exists()


class WorkplaceContract(models.Model):
    """An employment arrangement spanning a date range."""

    workplace = models.ForeignKey(
        Workplace, on_delete=models.CASCADE, related_name="contracts"
    )
    name = models.CharField(
        max_length=200, blank=True,
        help_text="Optional label, e.g. 'Physics Lab' or 'Adjunkt 2024'.",
    )
    start_date = models.DateField(
        help_text="Date this employment arrangement starts.",
    )
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Date this arrangement ends (leave blank if still active).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["workplace", "start_date"]

    def __str__(self):
        label = self.name or str(self.start_date)
        end = self.end_date or "open"
        return f"{self.workplace.name} — {label} ({self.start_date} → {end})"

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("End date must be on or after start date.")

        # Overlap check: no other contract for the same workplace may overlap
        if not self.start_date or not self.workplace_id:
            return
        qs = WorkplaceContract.objects.filter(workplace=self.workplace)
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        if self.end_date:
            # This contract runs [start, end]; overlap when other.start <= end AND other.end >= start
            overlap = qs.filter(start_date__lte=self.end_date).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=self.start_date)
            )
        else:
            # Open-ended: overlaps any contract that starts on or before today
            # (or any contract whose end_date >= our start)
            overlap = qs.filter(
                Q(end_date__isnull=True) | Q(end_date__gte=self.start_date)
            )

        if overlap.exists():
            other = overlap.first()
            raise ValidationError(
                f"This contract overlaps with '{other}'. "
                "Contracts for the same workplace must not overlap."
            )

    def is_active_on(self, d: _date) -> bool:
        if self.start_date and d < self.start_date:
            return False
        if self.end_date and d > self.end_date:
            return False
        return True

    def active_termset_on(self, d: _date) -> "ContractTermSet | None":
        return (
            self.term_sets.filter(effective_from__lte=d)
            .order_by("-effective_from")
            .first()
        )

    def get_rate_as_of(self, as_of: _date | None = None):
        """Return (hourly_rate, monthly_salary) for the active termset on *as_of*."""
        ts = self.active_termset_on(as_of or _date.today())
        if ts:
            return ts.hourly_rate, ts.monthly_salary
        return None, None


class ContractTermSet(models.Model):
    """
    A versioned snapshot of employment settings within a contract.
    The termset with the latest effective_from <= a given date is used.
    """

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

    class HourGoalType(models.TextChoices):
        WEEKLY = "weekly", "Per week"
        MONTHLY = "monthly", "Per month"

    contract = models.ForeignKey(
        WorkplaceContract, on_delete=models.CASCADE, related_name="term_sets"
    )
    effective_from = models.DateField(
        help_text="These terms apply from this date forward within the contract.",
    )

    # Employment
    employment_type = models.CharField(
        max_length=10,
        choices=EmploymentType.choices,
        default=EmploymentType.SALARIED,
    )
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Hourly rate in DKK (for hourly employment).",
    )
    monthly_salary = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Monthly gross salary in DKK (for salaried employment).",
    )

    # Weekly hours
    weekly_hours_fixed = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Fixed weekly hours. Leave blank if using min/max range.",
    )
    weekly_hours_min = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Minimum weekly hours (range mode).",
    )
    weekly_hours_max = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
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
    tax_pull_day = models.IntegerField(
        default=18,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text=(
            "Day of the month when the employer pulls your tax card from SKAT. "
            "Typically between the 15th and 20th."
        ),
    )

    # Vacation
    vacation_type = models.CharField(
        max_length=10,
        choices=VacationType.choices,
        default=VacationType.FERIEKONTO,
    )

    # Pension & fritvalgskonto
    pension_employee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Employee's own pension contribution (%).",
    )
    pension_employer_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Employer's pension contribution (%).",
    )
    fritvalgskonto_enabled = models.BooleanField(default=False)
    fritvalgskonto_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Fritvalgskonto percentage of gross salary.",
    )
    fritvalgskonto_payout_type = models.CharField(
        max_length=15,
        choices=FritvalgsPayoutType.choices,
        default=FritvalgsPayoutType.ACCRUES,
    )

    # Ferietillæg
    ferietillaeg_enabled = models.BooleanField(default=False)
    ferietillaeg_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("1.00"),
        help_text="Ferietillæg as % of yearly gross, typically ~1%.",
    )
    ferietillaeg_payout_months = models.CharField(
        max_length=50, default="5,8", blank=True,
        help_text="Comma-separated month numbers for payout (e.g. '5,8' for May & August).",
    )

    # Default shift (used when planning)
    default_shift_start_time = models.TimeField(null=True, blank=True)
    default_shift_end_time = models.TimeField(null=True, blank=True)
    default_shift_break_minutes = models.PositiveIntegerField(default=0)
    default_shift_type = models.CharField(
        max_length=15,
        choices=[
            ("on_site", "On-site"),
            ("remote", "Remote"),
            ("sick_leave", "Sick leave (with pay)"),
            ("paid_absence", "Paid absence"),
            ("vacation", "Vacation"),
        ],
        default="on_site",
    )

    # Hour goal
    hour_goal_type = models.CharField(
        max_length=10, choices=HourGoalType.choices, blank=True, default="",
    )
    hour_goal_min = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
    )
    hour_goal_max = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "effective_from"],
                name="unique_termset_per_date",
            )
        ]

    def __str__(self):
        return (
            f"{self.contract.workplace.name} / {self.contract.name or 'contract'} "
            f"from {self.effective_from}"
        )

    def clean(self):
        super().clean()
        if self.employment_type == self.EmploymentType.HOURLY and not self.hourly_rate:
            raise ValidationError("Hourly employment requires an hourly rate.")
        if self.employment_type == self.EmploymentType.SALARIED and not self.monthly_salary:
            raise ValidationError("Salaried employment requires a monthly salary.")

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

        # effective_from must fall within the parent contract's date range
        if self.contract_id and self.effective_from:
            c = self.contract
            if self.effective_from < c.start_date:
                raise ValidationError({
                    "effective_from": (
                        f"Must be on or after the contract start ({c.start_date})."
                    )
                })
            if c.end_date and self.effective_from > c.end_date:
                raise ValidationError({
                    "effective_from": (
                        f"Must be on or before the contract end ({c.end_date})."
                    )
                })

    # ------------------------------------------------------------------
    # Computed properties (moved from Workplace)
    # ------------------------------------------------------------------

    @property
    def expected_weekly_hours(self):
        if self.weekly_hours_fixed is not None:
            return self.weekly_hours_fixed
        if self.weekly_hours_min is not None and self.weekly_hours_max is not None:
            return (self.weekly_hours_min + self.weekly_hours_max) / 2
        return None

    @property
    def pension_total_percent(self):
        return self.pension_employee_percent + self.pension_employer_percent

    @property
    def base_hourly_rate(self):
        if self.employment_type == self.EmploymentType.HOURLY:
            return self.hourly_rate
        if self.monthly_salary and self.expected_weekly_hours:
            monthly_hours = self.expected_weekly_hours * Decimal("52") / Decimal("12")
            return (self.monthly_salary / monthly_hours).quantize(Decimal("0.01"))
        return None

    @property
    def effective_hourly_rate(self):
        base = self.base_hourly_rate
        if not base:
            return None
        factor = (
            Decimal("1")
            + (self.ferietillaeg_percent / Decimal("100") if self.ferietillaeg_enabled else Decimal("0"))
            + (self.fritvalgskonto_percent / Decimal("100") if self.fritvalgskonto_enabled else Decimal("0"))
            - self.pension_employee_percent / Decimal("100")
        )
        return (base * factor).quantize(Decimal("0.01"))

    @property
    def total_hourly_rate(self):
        base = self.base_hourly_rate
        if not base:
            return None
        factor = (
            Decimal("1")
            + (self.ferietillaeg_percent / Decimal("100") if self.ferietillaeg_enabled else Decimal("0"))
            + (self.fritvalgskonto_percent / Decimal("100") if self.fritvalgskonto_enabled else Decimal("0"))
            + self.pension_employer_percent / Decimal("100")
        )
        return (base * factor).quantize(Decimal("0.01"))

    @property
    def beskæftigelsesprocent(self):
        if self.weekly_hours_fixed is None:
            return None
        return (self.weekly_hours_fixed / Decimal("37") * Decimal("100")).quantize(Decimal("0.1"))

    @property
    def ferietillaeg_payout_month_list(self):
        if not self.ferietillaeg_payout_months:
            return []
        return [
            int(m.strip())
            for m in self.ferietillaeg_payout_months.split(",")
            if m.strip().isdigit() and 1 <= int(m.strip()) <= 12
        ]

    @property
    def ferietillaeg_payout_month_names(self):
        return [_cal.month_name[m] for m in self.ferietillaeg_payout_month_list]

    @property
    def vacation_days_per_month(self):
        return Decimal("2.08")

    def get_rate_as_of(self, as_of=None):
        """Duck-type compatibility: this record IS the point-in-time rate snapshot."""
        return self.hourly_rate, self.monthly_salary
