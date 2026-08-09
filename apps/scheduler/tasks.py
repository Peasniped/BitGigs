"""One-off task handlers: the registry the queue (``ScheduledTask``) runs.

The scheduler core stays app-agnostic — other apps register a handler for a
task id and enqueue work against it, without the scheduler importing them:

    from scheduler.tasks import register, enqueue

    @register("calendar.test_invite", title="Send a test invite")
    def _run(payload):
        ...                       # do the slow thing; raise to fail/retry
        return "a short summary"  # stored on the row's result

    enqueue("calendar.test_invite", {"to": address})

The optional *title* is what the Settings → Jobs queue shows instead of the bare
task id (which stays visible as the row's detail).

A handler takes the task's ``payload`` dict and returns a short summary string
(or None). Raising marks the run failed (and retries if ``max_attempts`` > 1).
Handlers must be imported for their `@register` to run — each app does that from
its ``AppConfig.ready()`` (see calendar_sync/apps.py).

``enqueue`` stamps ``queued_at`` into every payload. A handler that **sends mail**
should open with ``core.mail.require_sendable(role, payload.get("queued_at"))``:
that is the shared circuit breaker, which drops queued messages once the
connection has refused a run of them rather than feeding a server that is already
saying no. It lives in the mail layer, not here — the scheduler core knows
nothing about mail and stays that way.
"""
from __future__ import annotations

from typing import Callable, Optional

_HANDLERS: dict[str, Callable[[dict], object]] = {}
_TITLES: dict[str, str] = {}
_CLEAR_HOOKS: dict[str, Callable[[dict], object]] = {}
_ABANDON_HOOKS: dict[str, Callable[[dict, str], object]] = {}


def register(
    task_id: str,
    *,
    title: str = "",
    on_clear: Callable[[dict], object] | None = None,
    on_abandon: Callable[[dict, str], object] | None = None,
):
    """Decorator: bind *task_id* to the handler it decorates.

    *on_clear* is called with the payload when a **failed** row for this task is
    cleared from the queue. A failed row is often the only visible record that
    something didn't happen, so clearing it doubles as acknowledging it — this is
    the hook that lets the owning app act on that (see calendar_sync.tasks) while
    the scheduler core keeps importing no feature app.

    *on_abandon* is the same idea for a row that is failed **without its handler
    ever finishing** — reaped by the watchdog, or cancelled by hand. The handler's
    own failure path (which is where an app normally records "this didn't send")
    never ran, so without this hook the app is left believing the work is still
    in flight. It takes ``(payload, reason)``.
    """
    def decorator(func: Callable[[dict], object]) -> Callable[[dict], object]:
        _HANDLERS[task_id] = func
        if title:
            _TITLES[task_id] = title
        if on_clear:
            _CLEAR_HOOKS[task_id] = on_clear
        if on_abandon:
            _ABANDON_HOOKS[task_id] = on_abandon
        return func
    return decorator


def get_handler(task_id: str) -> Optional[Callable[[dict], object]]:
    return _HANDLERS.get(task_id)


def title_for(task_id: str) -> str:
    """The human label for *task_id*, or "" when it declared none (or is a row
    left over from a handler that no longer exists)."""
    return _TITLES.get(task_id, "")


def run_clear_hooks(rows, *, log=None) -> None:
    """Fire each cleared row's ``on_clear`` hook. Never raises — tidying up a log
    must not fail because of what a hook makes of it."""
    import logging

    log = log or logging.getLogger(__name__)
    for row in rows:
        hook = _CLEAR_HOOKS.get(row.task)
        if hook is None:
            continue
        try:
            hook(row.payload or {})
        except Exception:  # noqa: BLE001 — housekeeping never breaks the page
            log.exception("on_clear hook for task %r failed", row.task)


def run_abandon_hooks(rows, reason: str, *, log=None) -> None:
    """Fire each abandoned row's ``on_abandon`` hook. Never raises — the row is
    already marked failed, and a hook's opinion of that must not undo it."""
    import logging

    log = log or logging.getLogger(__name__)
    for row in rows:
        hook = _ABANDON_HOOKS.get(row.task)
        if hook is None:
            continue
        try:
            hook(row.payload or {}, reason)
        except Exception:  # noqa: BLE001 — see run_clear_hooks
            log.exception("on_abandon hook for task %r failed", row.task)


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

    # Stamped for every task: a handler only ever sees the payload, and "when was
    # this queued?" is the difference between a message that is part of a storm
    # already known to be failing and one somebody asked for afterwards (see
    # core.mail.blocked_reason).
    payload = dict(payload or {})
    payload.setdefault("queued_at", timezone.now().isoformat())

    task = ScheduledTask.objects.create(
        task=task_id,
        payload=payload,
        run_at=run_at or timezone.now(),
        max_attempts=max_attempts,
    )
    if getattr(settings, "SCHEDULER_TASK_EAGER", False):
        from . import services

        if services.claim_task(task):
            services.process_task(task)
    return task
