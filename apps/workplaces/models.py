import calendar as _cal
import os
from datetime import date as _date, timedelta
from decimal import Decimal

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.utils import date_spans_overlap, dk_slugify, weekly_to_monthly_hours


def workplace_icon_upload_to(instance, filename):
    """Store custom icons as workplace_icons/<slug>_icon.<ext> so files are
    identifiable per workplace and a re-upload overwrites the previous one."""
    ext = os.path.splitext(filename)[1].lower() or ".png"
    return f"workplace_icons/{instance.slug}_icon{ext}"


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
        upload_to=workplace_icon_upload_to,
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

    # Default shift (planning convenience — not a versioned employment term)
    default_shift_start_time = models.TimeField(null=True, blank=True)
    default_shift_end_time = models.TimeField(null=True, blank=True)
    default_shift_break_minutes = models.PositiveIntegerField(default=0)
    default_shift_type = models.CharField(
        max_length=15,
        choices=[
            ("on_site", "On-site"),
            ("remote", "Remote"),
            ("sick_leave", "Sick leave"),
            ("paid_absence", "Paid absence"),
            ("vacation", "Vacation"),
        ],
        default="on_site",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = dk_slugify(self.name) or "workplace"
            slug = base_slug
            n = 1
            while Workplace.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def avatar_color(self) -> str:
        """Background colour for the avatar: custom colour, else derived from name."""
        from core.utils import avatar_for_name
        return self.color or avatar_for_name(self.name)[1]

    @property
    def avatar_initials(self) -> str:
        """Initials shown when there's no icon/custom icon."""
        from core.utils import avatar_for_name
        return avatar_for_name(self.name)[0]

    @property
    def accent_rgb(self) -> str:
        """``accent_color`` as ``"14,97,222"`` — the form the ``--wp-accent-rgb``
        CSS token wants. Empty when no accent is set or the stored value can't be
        parsed, which is the signal not to open an accent scope at all."""
        from core.utils import hex_to_rgb_str
        try:
            return hex_to_rgb_str(self.accent_color) if self.accent_color else ""
        except (ValueError, IndexError):
            return ""

    @property
    def is_active(self) -> bool:
        """True when the workplace has at least one currently active contract."""
        return self.active_contract_on(timezone.localdate()) is not None

    # ------------------------------------------------------------------
    # Contract helpers
    #
    # A contract has no dates of its own — its active span is derived from its
    # term sets (see WorkplaceContract). These helpers therefore evaluate each
    # contract's term sets rather than any contract-level date field.
    # ------------------------------------------------------------------

    def active_contract_on(self, d: _date) -> "WorkplaceContract | None":
        """Return the contract active on date d, or None. Contracts for a
        workplace are guaranteed non-overlapping, so at most one matches."""
        for contract in self.contracts.all():
            if contract.is_active_on(d):
                return contract
        return None

    def contracts_in_period(self, start: _date, end: _date) -> list["WorkplaceContract"]:
        """Return contracts whose derived span overlaps [start, end]."""
        result = []
        for contract in self.contracts.all():
            s, e = contract.span()
            if date_spans_overlap(s, e, start, end):
                result.append(contract)
        return result

    def active_termset_on(self, d: _date) -> "ContractTermSet | None":
        """Convenience shortcut: active ContractTermSet on date d."""
        contract = self.active_contract_on(d)
        if contract is None:
            return None
        return contract.active_termset_on(d)

    def active_termset_in_month(self, year: int, month: int) -> "ContractTermSet | None":
        """The term set representing this workplace's pay terms for a calendar
        month — the terms in effect on the latest day the workplace has an active
        contract within the month.

        Robust to contracts/term sets that start or end anywhere in the month
        (a fixed mid-month probe would miss e.g. a contract starting on the 20th).
        """
        last_day = _cal.monthrange(year, month)[1]
        month_start = _date(year, month, 1)
        month_end = _date(year, month, last_day)
        active = self.contracts_in_period(month_start, month_end)
        if not active:
            return None
        # Latest-starting contract overlapping the month wins.
        contract = max(active, key=lambda c: c.start_date)
        span_end = contract.end_date
        anchor = month_end if span_end is None else min(month_end, span_end)
        return contract.active_termset_on(anchor)


class WorkplaceContract(models.Model):
    """A named employment arrangement. It carries no dates of its own — its
    active span is derived from its term sets: it starts at the earliest term
    set's ``effective_from`` and ends when the last term set's optional
    ``effective_until`` passes (open-ended if that is blank)."""

    workplace = models.ForeignKey(
        Workplace, on_delete=models.CASCADE, related_name="contracts"
    )
    name = models.CharField(
        max_length=200, blank=True,
        help_text="Optional label, e.g. 'Physics Lab' or 'Adjunkt 2024'.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["workplace", "id"]

    def __str__(self):
        label = self.name or (str(self.start_date) if self.start_date else "contract")
        end = self.end_date or "open"
        start = self.start_date or "?"
        return f"{self.workplace.name} — {label} ({start} → {end})"

    # ------------------------------------------------------------------
    # Derived date span (single source of truth = the term sets)
    # ------------------------------------------------------------------

    @property
    def _ordered_term_sets(self) -> list["ContractTermSet"]:
        """Term sets sorted by effective_from. Uses the Python list so a
        prefetch on ``term_sets`` is reused instead of hitting the DB again."""
        return sorted(self.term_sets.all(), key=lambda t: t.effective_from)

    @property
    def start_date(self) -> "_date | None":
        """Derived: earliest term set's effective_from (None if no terms yet)."""
        ordered = self._ordered_term_sets
        return ordered[0].effective_from if ordered else None

    @property
    def end_date(self) -> "_date | None":
        """Derived: the last (latest-starting) term set's effective_until, or
        None when that term set is open-ended / there are no terms."""
        ordered = self._ordered_term_sets
        return ordered[-1].effective_until if ordered else None

    def span(self) -> "tuple[_date | None, _date | None]":
        """(start_date, end_date) of the contract's active window."""
        ordered = self._ordered_term_sets
        if not ordered:
            return None, None
        return ordered[0].effective_from, ordered[-1].effective_until

    @property
    def timeline(self) -> list["ContractTermSet"]:
        """Term sets in display order (newest first), each with a transient
        ``gap_after`` attribute set to the inactive ``(first_day, last_day)``
        range between it and the next (older) term set, or None when they are
        contiguous. A gap exists when the older term set has an explicit
        effective_until that ends more than a day before this one begins."""
        ordered = sorted(
            self.term_sets.all(), key=lambda t: t.effective_from, reverse=True
        )
        for i, ts in enumerate(ordered):
            ts.gap_after = None
            if i + 1 < len(ordered):
                older = ordered[i + 1]
                if (
                    older.effective_until
                    and ts.effective_from - older.effective_until > timedelta(days=1)
                ):
                    ts.gap_after = (
                        older.effective_until + timedelta(days=1),
                        ts.effective_from - timedelta(days=1),
                    )
        return ordered

    def active_intervals(self) -> "list[tuple[_date, _date | None]]":
        """The contract's actually-active date ranges as (start, end) tuples
        (end None = open), derived from the term sets. Each term set runs from
        its effective_from until the day before the next term set, capped by its
        own effective_until — so gaps between term sets are excluded."""
        ordered = self._ordered_term_sets
        intervals = []
        for i, ts in enumerate(ordered):
            end = ts.effective_until
            if i + 1 < len(ordered):
                boundary = ordered[i + 1].effective_from - timedelta(days=1)
                end = boundary if end is None else min(end, boundary)
            intervals.append((ts.effective_from, end))
        return intervals

    def overlapping_contracts(self, span_start=None, span_end=None):
        """Other contracts for the same workplace whose derived span overlaps
        this one's span (or the given prospective [span_start, span_end]).
        Returns a list. Empty when this contract has no span yet."""
        if span_start is None and span_end is None:
            span_start, span_end = self.span()
        if span_start is None or not self.workplace_id:
            return []
        clashes = []
        siblings = (
            WorkplaceContract.objects
            .filter(workplace_id=self.workplace_id)
            .exclude(pk=self.pk)
            .prefetch_related("term_sets")
        )
        for other in siblings:
            os, oe = other.span()
            if date_spans_overlap(span_start, span_end, os, oe):
                clashes.append(other)
        return clashes

    def is_active_on(self, d: _date) -> bool:
        return self.active_termset_on(d) is not None

    def active_termset_on(self, d: _date) -> "ContractTermSet | None":
        """The term set in effect on date d. The latest term set whose
        effective_from <= d wins ("runs until the next one starts"); if that
        term set has an effective_until earlier than d, the contract has ended
        and there is no active term set."""
        ts = None
        for candidate in self._ordered_term_sets:  # ascending effective_from
            if candidate.effective_from > d:
                break
            ts = candidate
        if ts is None:
            return None
        if ts.effective_until is not None and ts.effective_until < d:
            return None
        return ts

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
    effective_until = models.DateField(
        null=True, blank=True,
        help_text=(
            "Optional. The date these terms stop applying. On the last term set "
            "this is the date the contract itself ends — leave blank while the "
            "employment is ongoing."
        ),
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

        if (
            self.effective_until and self.effective_from
            and self.effective_until < self.effective_from
        ):
            raise ValidationError({
                "effective_until": "End date must be on or after the effective-from date."
            })

        # Within a contract, a newer term set takes over on its effective_from,
        # so an end date that reaches into (or past) the next term set is
        # meaningless — that newer term set already ends these the day before.
        if self.contract_id and self.effective_from and self.effective_until:
            next_ts = (
                self.contract.term_sets
                .filter(effective_from__gt=self.effective_from)
                .exclude(pk=self.pk)
                .order_by("effective_from")
                .first()
            )
            if next_ts and self.effective_until >= next_ts.effective_from:
                raise ValidationError({
                    "effective_until": (
                        f"Newer terms begin on {next_ts.effective_from:%d/%m/%Y}, so "
                        f"these terms already end the day before. Remove this end "
                        f"date, or set it before {next_ts.effective_from:%d/%m/%Y}."
                    )
                })

        # Contracts for the same workplace must not overlap. The contract has no
        # dates of its own, so the guard runs here: compute the parent contract's
        # resulting span (existing sibling term sets + this one) and check it
        # against the other contracts at the workplace.
        if self.contract_id and self.effective_from:
            spans = [
                (t.effective_from, t.effective_until)
                for t in self.contract.term_sets.exclude(pk=self.pk)
            ]
            spans.append((self.effective_from, self.effective_until))
            span_start = min(ef for ef, _ in spans)
            span_end = max(spans, key=lambda t: t[0])[1]
            clashes = self.contract.overlapping_contracts(span_start, span_end)
            if clashes:
                other = clashes[0]
                if other.name:
                    other_label = f"“{other.name}”"
                elif other.start_date:
                    other_label = f"the contract starting on {other.start_date.strftime('%d/%m/%y')}"
                else:
                    other_label = "another contract"
                raise ValidationError(
                    f"These terms would make this contract overlap with {other_label}. "
                    f"Contracts for the same workplace must not overlap in time — "
                    f"set an end date on the other contract's final terms first."
                )

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
            monthly_hours = weekly_to_monthly_hours(self.expected_weekly_hours)
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
    def ferietillaeg_payout_month_list(self):
        if not self.ferietillaeg_payout_months:
            return []
        return [
            int(m.strip())
            for m in self.ferietillaeg_payout_months.split(",")
            if m.strip().isdigit() and 1 <= int(m.strip()) <= 12
        ]

    def get_rate_as_of(self, as_of=None):
        """Duck-type compatibility: this record IS the point-in-time rate snapshot."""
        return self.hourly_rate, self.monthly_salary
