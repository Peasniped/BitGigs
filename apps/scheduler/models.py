"""The DB-backed schedule table.

One ``ScheduledJob`` row per registered job (see ``registry.py``). The row is
the *live schedule*: it carries the cadence (seeded from the registry default,
but the operator may retune it), the enabled switch, and the runtime bookkeeping
the loop reads and writes — ``next_run_at`` decides when a job is due, and the
``last_*`` fields record how the previous run went.
"""
from django.db import models

from . import registry


class ScheduledJob(models.Model):
    KIND_INTERVAL = registry.KIND_INTERVAL
    KIND_DAILY = registry.KIND_DAILY
    KIND_CHOICES = [
        (KIND_INTERVAL, "Every N seconds"),
        (KIND_DAILY, "Daily at a set time"),
    ]

    STATUS_OK = "ok"
    STATUS_ERROR = "error"

    key = models.SlugField(
        unique=True,
        help_text="Matches a job id in scheduler.registry.",
    )
    enabled = models.BooleanField(default=True)

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    interval_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="For 'Every N seconds' jobs — the gap between runs.",
    )
    daily_time = models.TimeField(
        null=True,
        blank=True,
        help_text="For 'Daily' jobs — the local time of day it runs.",
    )

    next_run_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the loop will next consider this job due.",
    )
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=16, blank=True)
    last_error = models.TextField(blank=True)
    last_duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key

    @property
    def cadence_label(self) -> str:
        if self.kind == self.KIND_DAILY and self.daily_time:
            return f"daily at {self.daily_time:%H:%M}"
        if self.kind == self.KIND_INTERVAL and self.interval_seconds:
            return f"every {self.interval_seconds}s"
        return "—"

    @property
    def title(self) -> str:
        """The registry title, falling back to the key for a defunct row."""
        job = registry.get(self.key)
        return job.title if job else self.key

    @property
    def description(self) -> str:
        """The registry description, empty for a defunct row."""
        job = registry.get(self.key)
        return job.description if job else ""

    @property
    def in_registry(self) -> bool:
        return registry.get(self.key) is not None
