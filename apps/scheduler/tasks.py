"""One-off task handlers: the registry the queue (``ScheduledTask``) runs.

The scheduler core stays app-agnostic — other apps register a handler for a
task id and enqueue work against it, without the scheduler importing them:

    from scheduler.tasks import register, enqueue

    @register("calendar.test_invite")
    def _run(payload):
        ...                       # do the slow thing; raise to fail/retry
        return "a short summary"  # stored on the row's result

    enqueue("calendar.test_invite", {"to": address})

A handler takes the task's ``payload`` dict and returns a short summary string
(or None). Raising marks the run failed (and retries if ``max_attempts`` > 1).
Handlers must be imported for their `@register` to run — each app does that from
its ``AppConfig.ready()`` (see calendar_sync/apps.py).
"""
from __future__ import annotations

from typing import Callable, Optional

_HANDLERS: dict[str, Callable[[dict], object]] = {}


def register(task_id: str):
    """Decorator: bind *task_id* to the handler it decorates."""
    def decorator(func: Callable[[dict], object]) -> Callable[[dict], object]:
        _HANDLERS[task_id] = func
        return func
    return decorator


def get_handler(task_id: str) -> Optional[Callable[[dict], object]]:
    return _HANDLERS.get(task_id)


def registered_ids() -> set[str]:
    return set(_HANDLERS)


def enqueue(task_id: str, payload: dict | None = None, *, run_at=None, max_attempts: int = 1):
    """Add a one-off task to the queue. Returns the created ``ScheduledTask``.

    Runs on the scheduler's next tick at/after *run_at* (default: now). When
    ``settings.SCHEDULER_TASK_EAGER`` is on (tests), the task runs **inline**
    here instead — the standard "run tasks synchronously" switch, so a test can
    assert an enqueued send's effect without spinning the loop.
    """
    from django.conf import settings
    from django.utils import timezone

    from .models import ScheduledTask

    task = ScheduledTask.objects.create(
        task=task_id,
        payload=payload or {},
        run_at=run_at or timezone.now(),
        max_attempts=max_attempts,
    )
    if getattr(settings, "SCHEDULER_TASK_EAGER", False):
        from . import services

        if services.claim_task(task):
            services.process_task(task)
    return task
