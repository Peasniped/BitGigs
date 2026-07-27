"""The DB-backed schedule table.

One ``ScheduledJob`` row per registered job (see ``registry.py``). The row is
the *live schedule*: it carries the cadence (seeded from the registry default,
but the operator may retune it), the enabled switch, and the runtime bookkeeping
the loop reads and writes — ``next_run_at`` decides when a job is due, and the
``last_*`` fields record how the previous run went.
"""
from django.db import models
from django.utils import timezone

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


class ScheduledTask(models.Model):
    """A durable **one-off** task: enqueued by a request, run once by the loop.

    This is the async hand-off — a view enqueues work (e.g. "send this calendar
    invite") and returns instantly instead of blocking on SMTP; the scheduler
    process picks it up on its next tick and runs the registered handler (see
    ``scheduler.tasks``). Distinct from ``ScheduledJob``, which is *recurring*.
    """
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (RUNNING, "Running"),
        (DONE, "Done"),
        (FAILED, "Failed"),
    ]

    task = models.CharField(max_length=64, help_text="Handler id in scheduler.tasks.")
    payload = models.JSONField(default=dict, blank=True)
    run_at = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    result = models.CharField(max_length=255, blank=True)

    PRUNE_KEEP = 200  # mirror EmailLog / HelpArticleRevision retention

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task} ({self.status})"

    @classmethod
    def prune(cls, keep: int | None = None):
        """Keep the newest *keep* finished (done/failed) rows; drop older ones.

        Pending/running rows are never touched — only the completed tail.
        """
        keep = cls.PRUNE_KEEP if keep is None else keep
        finished = cls.objects.filter(status__in=[cls.DONE, cls.FAILED])
        stale_ids = list(
            finished.order_by("-finished_at", "-id").values_list("id", flat=True)[keep:]
        )
        if stale_ids:
            cls.objects.filter(id__in=stale_ids).delete()


class SchedulerHeartbeat(models.Model):
    """A single row the loop stamps every tick, so the rest of the app can tell
    whether the scheduler process is actually running — a queued task silently
    never sending (no scheduler up) is otherwise indistinguishable from a slow
    one. There is only ever one row."""
    beat_at = models.DateTimeField()

    @classmethod
    def beat(cls):
        cls.objects.update_or_create(pk=1, defaults={"beat_at": timezone.now()})

    @classmethod
    def seconds_since(cls):
        row = cls.objects.first()
        return None if row is None else (timezone.now() - row.beat_at).total_seconds()

    @classmethod
    def is_alive(cls, within: float | None = None) -> bool:
        from django.conf import settings

        if within is None:
            tick = getattr(settings, "SCHEDULER_TICK_SECONDS", 30)
            within = max(90, 3 * tick)
        secs = cls.seconds_since()
        return secs is not None and secs <= within
