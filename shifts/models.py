from datetime import datetime
from decimal import Decimal

from django.db import models
from django.core.exceptions import ValidationError

from workplaces.models import Workplace


class ShiftTimeMixin(models.Model):
    """Abstract mixin providing shared time-calculation logic for shifts."""

    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Break time in minutes (deducted from total).",
    )

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError("End time must be after start time.")

    @property
    def gross_minutes(self) -> int:
        """Total minutes from start to end."""
        start_dt = datetime.combine(self.date, self.start_time)
        end_dt = datetime.combine(self.date, self.end_time)
        return int((end_dt - start_dt).total_seconds() / 60)

    @property
    def net_minutes(self) -> int:
        """Gross minutes minus break."""
        return max(self.gross_minutes - self.break_minutes, 0)

    @property
    def net_hours(self) -> Decimal:
        """Net working hours as a Decimal."""
        return Decimal(str(self.net_minutes)) / Decimal("60")


class Shift(ShiftTimeMixin):
    """An approved/completed work shift on a given day."""

    class ShiftType(models.TextChoices):
        ON_SITE = "on_site", "On-site"
        REMOTE = "remote", "Remote"
        SICK_LEAVE = "sick_leave", "Sick leave (with pay)"
        PAID_ABSENCE = "paid_absence", "Paid absence"
        VACATION = "vacation", "Vacation"

    workplace = models.ForeignKey(
        Workplace,
        on_delete=models.CASCADE,
        related_name="shifts",
    )
    shift_type = models.CharField(
        max_length=15,
        choices=ShiftType.choices,
        default=ShiftType.ON_SITE,
    )
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["workplace", "date"]),
        ]

    def __str__(self):
        return (
            f"{self.workplace.name} — {self.date} "
            f"{self.start_time:%H:%M}–{self.end_time:%H:%M}"
        )

    @property
    def is_commuting_day(self) -> bool:
        """On-site shifts count as commuting days for tax purposes."""
        return self.shift_type == self.ShiftType.ON_SITE


class PlannedShift(ShiftTimeMixin):
    """A planned/draft shift that can be approved and converted to a Shift."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        APPROVED = "approved", "Approved"

    workplace = models.ForeignKey(
        Workplace,
        on_delete=models.CASCADE,
        related_name="planned_shifts",
    )
    shift_type = models.CharField(
        max_length=15,
        choices=Shift.ShiftType.choices,
        default=Shift.ShiftType.ON_SITE,
    )
    notes = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PLANNED,
    )
    arrival_confirmed = models.BooleanField(
        default=False,
        help_text="Whether the user has confirmed/updated their arrival time.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["workplace", "date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return (
            f"[{self.get_status_display()}] {self.workplace.name} — {self.date} "
            f"{self.start_time:%H:%M}–{self.end_time:%H:%M}"
        )

    def approve(self) -> "Shift":
        """Convert this planned shift into an approved Shift."""
        shift = Shift.objects.create(
            workplace=self.workplace,
            date=self.date,
            start_time=self.start_time,
            end_time=self.end_time,
            break_minutes=self.break_minutes,
            shift_type=self.shift_type,
            notes=self.notes,
        )
        self.status = self.Status.APPROVED
        self.save()
        return shift
