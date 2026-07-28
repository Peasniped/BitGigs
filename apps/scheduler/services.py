"""Scheduler engine: computing when a job runs next, claiming a due job so a
stray second loop can't double-fire it, and running it while recording the
outcome. Kept out of the management command so views/tests/admin can reuse it.
"""
import logging
from datetime import datetime, timedelta
from time import monotonic

from django.conf import settings as django_settings
from django.db import models
from django.utils import timezone

from . import registry
from .models import ScheduledJob, ScheduledTask

logger = logging.getLogger(__name__)

DEFAULT_TASK_TIMEOUT = 600  # seconds; overridden by SCHEDULER_TASK_TIMEOUT_SECONDS


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


# ─── One-off task queue ──────────────────────────────────────────────────────

RETRY_BACKOFF = timedelta(seconds=60)


def due_tasks(now: datetime | None = None):
    now = now or timezone.now()
    return ScheduledTask.objects.filter(
        status=ScheduledTask.PENDING, run_at__lte=now
    ).order_by("run_at", "id")  # FIFO within the same run_at (CANCEL before REQUEST)


def claim_task(task: ScheduledTask, now: datetime | None = None) -> bool:
    """Atomically flip PENDING → RUNNING so only one loop owns the run (same
    compare-and-set trick as ``claim``)."""
    now = now or timezone.now()
    return (
        ScheduledTask.objects.filter(pk=task.pk, status=ScheduledTask.PENDING)
        .update(status=ScheduledTask.RUNNING, started_at=now)
    ) == 1


def process_task(task: ScheduledTask, *, log=logger) -> str:
    """Run the registered handler for *task* and record how it went.

    Never raises. On failure, retries (back to PENDING with a backoff) while
    attempts remain, else marks FAILED. Returns the resulting status.
    """
    from . import tasks as task_registry

    handler = task_registry.get_handler(task.task)
    attempts = task.attempts + 1
    if handler is None:
        ScheduledTask.objects.filter(pk=task.pk).update(
            status=ScheduledTask.FAILED,
            finished_at=timezone.now(),
            attempts=attempts,
            last_error="No handler registered for this task.",
        )
        log.warning("Task %r has no registered handler", task.task)
        return ScheduledTask.FAILED

    started = monotonic()
    try:
        result = handler(task.payload or {})
    except Exception as exc:  # a task's failure must not stop the loop
        error = f"{type(exc).__name__}: {exc}"
        log.exception("Task %r failed (attempt %d/%d)", task.task, attempts, task.max_attempts)
        if attempts < task.max_attempts:
            ScheduledTask.objects.filter(pk=task.pk).update(
                status=ScheduledTask.PENDING,
                attempts=attempts,
                last_error=error[:2000],
                run_at=timezone.now() + RETRY_BACKOFF * attempts,
            )
            return ScheduledTask.PENDING
        ScheduledTask.objects.filter(pk=task.pk).update(
            status=ScheduledTask.FAILED,
            finished_at=timezone.now(),
            attempts=attempts,
            last_error=error[:2000],
        )
        return ScheduledTask.FAILED

    duration_ms = int((monotonic() - started) * 1000)
    ScheduledTask.objects.filter(pk=task.pk).update(
        status=ScheduledTask.DONE,
        finished_at=timezone.now(),
        attempts=attempts,
        result=(str(result) if result else "")[:255],
        last_error="",
    )
    log.info(
        "Task %r done in %dms%s",
        task.task,
        duration_ms,
        f" — {result}" if result else "",
    )
    return ScheduledTask.DONE


def run_pending_tasks(now: datetime | None = None, *, log=logger) -> list[str]:
    """Claim and run every queued task that is due. Returns the task ids run."""
    now = now or timezone.now()
    ran: list[str] = []
    for task in list(due_tasks(now)):
        if claim_task(task, now):
            process_task(task, log=log)
            ran.append(task.task)
    if ran:
        ScheduledTask.prune()
    return ran


# ─── Stuck-task watchdog ─────────────────────────────────────────────────────
#
# A task is claimed by flipping PENDING → RUNNING *before* it runs, so if the
# process dies mid-task (a crash, `docker stop`, a dev Ctrl+C) the row is left
# RUNNING for ever: nothing re-claims it (claim_task only takes PENDING), the
# queue's Clear buttons only touch finished rows, and Retry only offers itself on
# a failed one. It sits in the table permanently and — worse — whatever queued it
# still believes the work is in flight. The watchdog is what ends that: past a
# generous timeout, a RUNNING row becomes FAILED like any other failure, which
# puts Retry and Clear back within reach.

def task_timeout_seconds() -> int:
    return int(
        getattr(django_settings, "SCHEDULER_TASK_TIMEOUT_SECONDS", DEFAULT_TASK_TIMEOUT)
    )


def stuck_tasks(now: datetime | None = None):
    """RUNNING rows that have been running longer than the timeout.

    ``started_at`` is stamped by ``claim_task``; a row somehow missing it falls
    back to ``run_at`` so it can still be reaped rather than stay stuck for ever.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=task_timeout_seconds())
    return ScheduledTask.objects.filter(status=ScheduledTask.RUNNING).filter(
        models.Q(started_at__lte=cutoff)
        | models.Q(started_at__isnull=True, run_at__lte=cutoff)
    )


def reap_stuck_tasks(now: datetime | None = None, *, log=logger) -> int:
    """Mark timed-out RUNNING rows as failed. Returns how many were reaped.

    Each row's ``on_abandon`` hook then fires, because the handler's own failure
    path never got to run — for a calendar invite that's what stops the shift
    wearing an "invite sent" marker nobody ever received.

    The reap can't *stop* a run that is genuinely still going; if that process
    later finishes it overwrites the row with its real outcome, which is the
    honest answer either way.
    """
    from . import tasks as task_registry

    now = now or timezone.now()
    rows = list(stuck_tasks(now))
    if not rows:
        return 0

    minutes = task_timeout_seconds() // 60
    reason = f"Timed out — no result after {minutes} minute(s); the scheduler may have restarted."
    ScheduledTask.objects.filter(pk__in=[r.pk for r in rows]).update(
        status=ScheduledTask.FAILED, finished_at=now, last_error=reason
    )
    for row in rows:
        log.warning("Reaped stuck task %r (#%d) — %s", row.task, row.pk, reason)
    task_registry.run_abandon_hooks(rows, reason, log=log)
    return len(rows)
