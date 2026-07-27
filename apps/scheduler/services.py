"""Scheduler engine: computing when a job runs next, claiming a due job so a
stray second loop can't double-fire it, and running it while recording the
outcome. Kept out of the management command so views/tests/admin can reuse it.
"""
import logging
from datetime import datetime, timedelta
from time import monotonic

from django.utils import timezone

from . import registry
from .models import ScheduledJob

logger = logging.getLogger(__name__)


def compute_next_run(job: ScheduledJob, after: datetime | None = None) -> datetime | None:
    """The next fire time strictly after *after* (default: now).

    Both cadences deliberately schedule a single *future* slot, never a backlog:
    a daily job whose time slipped by while the scheduler was down fires once on
    the next tick, then lands on tomorrow's slot — not once per missed day.
    """
    now = after or timezone.now()

    if job.kind == ScheduledJob.KIND_INTERVAL:
        if not job.interval_seconds:
            return None
        return now + timedelta(seconds=job.interval_seconds)

    if job.kind == ScheduledJob.KIND_DAILY:
        if not job.daily_time:
            return None
        local_now = timezone.localtime(now)
        candidate = local_now.replace(
            hour=job.daily_time.hour,
            minute=job.daily_time.minute,
            second=job.daily_time.second,
            microsecond=0,
        )
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate

    return None


def due_jobs(now: datetime | None = None):
    now = now or timezone.now()
    return ScheduledJob.objects.filter(
        enabled=True, next_run_at__isnull=False, next_run_at__lte=now
    )


def claim(row: ScheduledJob, now: datetime | None = None) -> bool:
    """Atomically advance ``next_run_at`` so this loop owns the run.

    Uses an optimistic compare-and-set on the old ``next_run_at`` (works on
    SQLite and Postgres alike, no row locks): if a concurrent loop already
    advanced it, our conditional UPDATE touches 0 rows and we back off. The slot
    is booked *before* the job runs, so a crash mid-job doesn't wedge it due.
    """
    now = now or timezone.now()
    nxt = compute_next_run(row, now)
    updated = (
        ScheduledJob.objects.filter(pk=row.pk, next_run_at=row.next_run_at)
        .update(next_run_at=nxt)
    )
    return updated == 1


def run_job(row: ScheduledJob, *, log=logger) -> str:
    """Run the registered callable for *row* and record how it went.

    Never raises — a failing job is caught, logged and stamped onto the row so
    one broken job can't take the loop down with it. Returns ``last_status``.
    """
    job = registry.get(row.key)
    if job is None:
        # Defunct row the seed hasn't cleaned up yet — disable so the loop
        # stops re-picking it every tick.
        ScheduledJob.objects.filter(pk=row.pk).update(enabled=False)
        log.warning("Disabling scheduled job %r — no such job in registry", row.key)
        return ScheduledJob.STATUS_ERROR

    started = monotonic()
    status, error, summary = ScheduledJob.STATUS_OK, "", None
    try:
        summary = job.func()
    except Exception as exc:  # a job's failure must not stop the scheduler
        status = ScheduledJob.STATUS_ERROR
        error = f"{type(exc).__name__}: {exc}"
        log.exception("Scheduled job %r failed", row.key)
    duration_ms = int((monotonic() - started) * 1000)

    ScheduledJob.objects.filter(pk=row.pk).update(
        last_run_at=timezone.now(),
        last_status=status,
        last_error=error[:2000],
        last_duration_ms=duration_ms,
    )
    if status == ScheduledJob.STATUS_OK:
        log.info(
            "Scheduled job %r ok in %dms%s",
            row.key,
            duration_ms,
            f" — {summary}" if summary else "",
        )
    return status


def run_due(now: datetime | None = None, *, log=logger) -> list[str]:
    """Claim and run every job that is due right now. Returns the keys run."""
    now = now or timezone.now()
    ran: list[str] = []
    for row in list(due_jobs(now)):
        if claim(row, now):
            run_job(row, log=log)
            ran.append(row.key)
    return ran
