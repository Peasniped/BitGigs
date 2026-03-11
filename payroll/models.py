from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

from workplaces.models import Workplace


class PayrollPeriod(models.Model):
    """
    A specific payroll period for a workplace.

    E.g. if payroll_period_start_day=20, a period might be 2026-02-20 to 2026-03-19.
    """

    workplace = models.ForeignKey(
        Workplace,
        on_delete=models.CASCADE,
        related_name="payroll_periods",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    is_locked = models.BooleanField(
        default=False,
        help_text="Lock period to prevent edits after payslip is finalized.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        unique_together = ["workplace", "start_date"]

    def __str__(self):
        return f"{self.workplace.name}: {self.start_date} → {self.end_date}"


class PayslipLineTemplate(models.Model):
    """
    Reusable payslip line templates per workplace.
    When a new payroll period is created, these are copied in as initial lines.
    """

    class LineType(models.TextChoices):
        PRE_TAX_ADD = "pre_tax_add", "Pre-tax addition"
        PRE_TAX_DEDUCT = "pre_tax_deduct", "Pre-tax deduction"
        POST_TAX_ADD = "post_tax_add", "Post-tax addition"
        POST_TAX_DEDUCT = "post_tax_deduct", "Post-tax deduction"
        INFORMATIONAL = "info", "Informational"

    class RoundingMethod(models.TextChoices):
        ROUND = "round", "Round (standard)"
        FLOOR = "floor", "Floor (round down)"
        CEIL = "ceil", "Ceil (round up)"

    workplace = models.ForeignKey(
        Workplace,
        on_delete=models.CASCADE,
        related_name="payslip_templates",
    )
    name = models.CharField(max_length=200)
    default_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    default_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    default_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    line_type = models.CharField(
        max_length=15,
        choices=LineType.choices,
        default=LineType.PRE_TAX_ADD,
    )
    rounding_method = models.CharField(
        max_length=5,
        choices=RoundingMethod.choices,
        default=RoundingMethod.ROUND,
        help_text="How to round the line amount.",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self):
        return f"{self.name} ({self.get_line_type_display()})"


class PayslipLine(models.Model):
    """
    Actual payslip line for a payroll period.
    Standard lines are auto-generated from tax/payroll calculations.
    Custom lines are user-added and can be moved between standard lines.
    Columns: name, quantity, rate, amount, running subtotal (computed).
    Supports drag-and-drop reordering via sort_order.
    """

    class LineType(models.TextChoices):
        PRE_TAX_ADD = "pre_tax_add", "Pre-tax addition"
        PRE_TAX_DEDUCT = "pre_tax_deduct", "Pre-tax deduction"
        POST_TAX_ADD = "post_tax_add", "Post-tax addition"
        POST_TAX_DEDUCT = "post_tax_deduct", "Post-tax deduction"
        INFORMATIONAL = "info", "Informational"

    class RoundingMethod(models.TextChoices):
        ROUND = "round", "Round (standard)"
        FLOOR = "floor", "Floor (round down)"
        CEIL = "ceil", "Ceil (round up)"

    class StandardLineKey(models.TextChoices):
        """Keys for auto-calculated standard lines."""
        GROSS_PAY = "gross_pay", "Gross pay"
        FERIETILLAEG = "ferietillaeg", "Ferietillæg"
        PENSION_EMPLOYEE = "pension_employee", "Own pension contribution"
        ATP_EMPLOYEE = "atp_employee", "ATP (employee)"
        AM_BIDRAG = "am_bidrag", "AM-bidrag"
        FRADRAG_USED = "fradrag_used", "Benyttet fradrag"
        A_SKAT = "a_skat", "A-skat"
        TOTAL_TAX = "total_tax", "Total taxation"
        SUBTOTAL = "subtotal", "Subtotal"
        NET_PAY = "net_pay", "Net pay"

    payroll_period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    name = models.CharField(max_length=200)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="E.g. number of hours or units.",
    )
    rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Rate per unit (e.g. hourly rate).",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Line amount in DKK. If quantity and rate are set, this may be auto-calculated.",
    )
    line_type = models.CharField(
        max_length=15,
        choices=LineType.choices,
        default=LineType.PRE_TAX_ADD,
    )
    rounding_method = models.CharField(
        max_length=5,
        choices=RoundingMethod.choices,
        default=RoundingMethod.ROUND,
        help_text="How to round this line's amount.",
    )
    standard_line_key = models.CharField(
        max_length=20,
        choices=StandardLineKey.choices,
        null=True,
        blank=True,
        help_text="Set for auto-calculated standard lines. NULL for custom lines.",
    )
    is_editable = models.BooleanField(
        default=True,
        help_text="Whether the user can edit the amount. Standard calculated lines are read-only.",
    )
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self):
        return f"{self.name}: {self.amount} DKK"

    def save(self, *args, **kwargs):
        from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
        # Auto-calculate amount from quantity × rate if both are provided
        if self.quantity is not None and self.rate is not None and not self.amount:
            self.amount = self.quantity * self.rate
        # Apply rounding method
        if self.amount is not None:
            two_places = Decimal("0.01")
            if self.rounding_method == self.RoundingMethod.FLOOR:
                self.amount = self.amount.quantize(two_places, rounding=ROUND_FLOOR)
            elif self.rounding_method == self.RoundingMethod.CEIL:
                self.amount = self.amount.quantize(two_places, rounding=ROUND_CEILING)
            else:
                self.amount = self.amount.quantize(two_places, rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class CommutingRecord(models.Model):
    """
    Monthly commuting day count per workplace for tax deduction (befordringsfradrag).
    """

    workplace = models.ForeignKey(
        Workplace,
        on_delete=models.CASCADE,
        related_name="commuting_records",
    )
    year = models.IntegerField()
    month = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    commuting_days = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["workplace", "year", "month"]
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.workplace.name} — {self.year}-{self.month:02d}: {self.commuting_days} days"


class VacationBalance(models.Model):
    """
    Monthly vacation balance tracking for workplaces using 'accrued' vacation type.
    """

    workplace = models.ForeignKey(
        Workplace,
        on_delete=models.CASCADE,
        related_name="vacation_balances",
    )
    year = models.IntegerField()
    month = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    accrued_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    used_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    carried_over_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text="Balance carried from the previous month.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["workplace", "year", "month"]
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"{self.workplace.name} vacation {self.year}-{self.month:02d}"

    @property
    def balance(self):
        """Current balance = carried_over + accrued − used."""
        return self.carried_over_hours + self.accrued_hours - self.used_hours
