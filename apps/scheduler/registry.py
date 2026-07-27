"""The catalogue of scheduled jobs — the single source of truth that seeds the
DB-backed schedule table (``ScheduledJob``) and supplies the callable the loop
runs for each row.

Adding a job = write a zero-argument callable that does the work (returning a
short one-line summary for the log, or None), then describe it here with its
default cadence. Everything else — the DB row, the admin entry, the loop — flows
from this list. The operator can retune a job's cadence or disable it via the
row afterwards; this file only supplies the *defaults* a fresh install starts
from.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from typing import Callable, Optional

KIND_INTERVAL = "interval"
KIND_DAILY = "daily"


@dataclass(frozen=True)
class Job:
    id: str  # matches ScheduledJob.key
    title: str
    description: str
    func: Callable[[], object]  # zero-arg; returns a short summary str or None
    # Exactly one cadence must be set.
    every: Optional[timedelta] = None  # run this often
    daily_at: Optional[time] = None  # run once a day at this LOCAL time

    def __post_init__(self):
        if (self.every is None) == (self.daily_at is None):
            raise ValueError(
                f"Job {self.id!r} must set exactly one of every / daily_at"
            )

    @property
    def kind(self) -> str:
        return KIND_INTERVAL if self.every is not None else KIND_DAILY

    @property
    def interval_seconds(self) -> Optional[int]:
        return int(self.every.total_seconds()) if self.every is not None else None

    @property
    def daily_time(self) -> Optional[time]:
        return self.daily_at


# ─── Job implementations ─────────────────────────────────────────────────────

def _prune_workplace_icons() -> str:
    """Delete orphaned custom workplace-icon files no workplace references.

    Honours settings.ICON_PRUNE_AUTO exactly like the opportunistic path does:
    the prune treats the active database as the sole authority on which icons
    are in use, which is only true in production. In dev (a spare db.sqlite3.bak
    sharing the same media/ directory) the flag is off, so this no-ops safely.
    """
    from django.conf import settings

    if not getattr(settings, "ICON_PRUNE_AUTO", True):
        return "skipped — ICON_PRUNE_AUTO is off (dev)"
    from workplaces.services import prune_orphan_icons

    removed = prune_orphan_icons()
    return f"removed {len(removed)} orphaned icon(s)"


# ─── The catalogue ───────────────────────────────────────────────────────────

JOBS: list[Job] = [
    Job(
        id="prune_workplace_icons",
        title="Prune orphaned workplace icons",
        description=(
            "Delete uploaded workplace-icon files on disk that no workplace "
            "still references. Runs opportunistically too (on a dashboard "
            "load), so this is a belt-and-braces daily sweep for installs "
            "that go a day without one."
        ),
        func=_prune_workplace_icons,
        daily_at=time(3, 30),
    ),
]


def get(job_id: str) -> Optional[Job]:
    for job in JOBS:
        if job.id == job_id:
            return job
    return None


def all_jobs() -> list[Job]:
    return list(JOBS)


def ids() -> set[str]:
    return {job.id for job in JOBS}
