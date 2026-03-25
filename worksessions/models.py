from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError

from workplaces.models import Workplace


class WorkSession(models.Model):
    """A single work session on a given day."""

    class SessionType(models.TextChoices):
        ON_SITE = "on_site", "On-site"
        REMOTE = "remote", "Remote"
        SICK_LEAVE = "sick_leave", "Sick leave (with pay)"
        PAID_ABSENCE = "paid_absence", "Paid absence"
        VACATION = "vacation", "Vacation"

    workplace = models.ForeignKey(
        Workplace,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Break time in minutes (deducted from total).",
    )
    session_type = models.CharField(
        max_length=15,
        choices=SessionType.choices,
        default=SessionType.ON_SITE,
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

    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError("End time must be after start time.")

    @property
    def gross_minutes(self) -> int:
        """Total minutes from start to end."""
        from datetime import datetime, timedelta

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

    @property
    def is_commuting_day(self) -> bool:
        """On-site sessions count as commuting days for tax purposes."""
        return self.session_type == self.SessionType.ON_SITE


class PlannedShift(models.Model):
    """A planned/draft shift that can be approved and converted to a WorkSession."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        APPROVED = "approved", "Approved"

    workplace = models.ForeignKey(
        Workplace,
        on_delete=models.CASCADE,
        related_name="planned_shifts",
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Break time in minutes (deducted from total).",
    )
    session_type = models.CharField(
        max_length=15,
        choices=WorkSession.SessionType.choices,
        default=WorkSession.SessionType.ON_SITE,
    )
    notes = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PLANNED,
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

    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError("End time must be after start time.")

    @property
    def gross_minutes(self) -> int:
        from datetime import datetime
        start_dt = datetime.combine(self.date, self.start_time)
        end_dt = datetime.combine(self.date, self.end_time)
        return int((end_dt - start_dt).total_seconds() / 60)

    @property
    def net_minutes(self) -> int:
        return max(self.gross_minutes - self.break_minutes, 0)

    @property
    def net_hours(self) -> Decimal:
        return Decimal(str(self.net_minutes)) / Decimal("60")

    def approve(self) -> WorkSession:
        """Convert this planned shift into a real WorkSession and mark as approved."""
        session = WorkSession.objects.create(
            workplace=self.workplace,
            date=self.date,
            start_time=self.start_time,
            end_time=self.end_time,
            break_minutes=self.break_minutes,
            session_type=self.session_type,
            notes=self.notes,
        )
        self.status = self.Status.APPROVED
        self.save()
        return session
