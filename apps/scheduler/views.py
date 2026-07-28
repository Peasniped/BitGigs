"""Settings → Jobs tab: a read-mostly view of the schedule table with an
on/off toggle per job. Mirrors the API tab's shape — a context helper called by
core's UserSettingsView, plus small POST views that redirect back to the tab.

The tab also polls ``SchedulerStatusView`` for a live picture of the heartbeat,
the one-off task queue and each job's runtime state, so a queued invite visibly
moves Queued → Running → Done without a reload. The JSON and the server-rendered
first paint come from the *same* serializers below, so they can't drift apart.
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.defaultfilters import date as date_filter
from django.urls import reverse
from django.views import View

from .models import ScheduledJob, ScheduledTask, SchedulerHeartbeat

RECENT_TASK_LIMIT = 10


def _back_to_tab():
    return redirect(f"{reverse('core:settings')}?tab=jobs")


def _when(dt) -> str:
    """A timestamp in the same format the tab's templates use ("" for None)."""
    return date_filter(dt, "j M, H:i") or ""


def _task_payload(task: ScheduledTask) -> dict:
    return {
        "id": task.pk,
        "task": task.task,
        "label": task.label,
        "status": task.status,
        # Finished rows are interesting for *when they ended*, queued ones for
        # when they are due to start.
        "when": _when(task.finished_at or task.run_at),
        "result": task.result,
        "error": task.last_error,
    }


def _job_payload(job: ScheduledJob) -> dict:
    return {
        "id": job.pk,
        "enabled": job.enabled,
        "next_run": _when(job.next_run_at) if job.enabled else "",
        "last_run": _when(job.last_run_at),
        "last_status": job.last_status,
        "last_duration_ms": job.last_duration_ms,
        "last_error": job.last_error,
    }


def scheduler_status() -> dict:
    """Everything the Jobs tab shows that can change on its own."""
    finished = ScheduledTask.objects.filter(
        status__in=[ScheduledTask.DONE, ScheduledTask.FAILED]
    )
    secs = SchedulerHeartbeat.seconds_since()
    return {
        "alive": SchedulerHeartbeat.is_alive(),
        "seconds_since": None if secs is None else int(secs),
        "active_tasks": list(
            ScheduledTask.objects.filter(
                status__in=[ScheduledTask.PENDING, ScheduledTask.RUNNING]
            ).order_by("run_at", "id")
        ),
        "recent_tasks": list(finished.order_by("-finished_at", "-id")[:RECENT_TASK_LIMIT]),
        "done_count": finished.filter(status=ScheduledTask.DONE).count(),
        "failed_count": finished.filter(status=ScheduledTask.FAILED).count(),
    }


def jobs_settings_context():
    """Context for the Settings → Jobs tab (called by core.UserSettingsView)."""
    status = scheduler_status()
    return {
        "scheduled_jobs": list(ScheduledJob.objects.all()),
        "scheduler_alive": status["alive"],
        "scheduler_seconds_since": status["seconds_since"],
        "scheduler_active_tasks": status["active_tasks"],
        "scheduler_recent_tasks": status["recent_tasks"],
        "scheduler_done_count": status["done_count"],
        "scheduler_failed_count": status["failed_count"],
    }


class SchedulerStatusView(View):
    """JSON snapshot polled by the Jobs tab (session-gated like every page)."""

    def get(self, request):
        status = scheduler_status()
        return JsonResponse(
            {
                "alive": status["alive"],
                "seconds_since": status["seconds_since"],
                "active": [_task_payload(t) for t in status["active_tasks"]],
                "recent": [_task_payload(t) for t in status["recent_tasks"]],
                "done_count": status["done_count"],
                "failed_count": status["failed_count"],
                "jobs": [_job_payload(j) for j in ScheduledJob.objects.all()],
            }
        )


class ScheduledJobToggleView(View):
    """Flip a job's enabled switch. Disabling only excludes it from the due
    query — its next_run_at is untouched, so re-enabling picks up where it left
    off (and fires on the next tick if that time has already passed)."""

    def post(self, request, pk):
        try:
            job = ScheduledJob.objects.get(pk=pk)
        except ScheduledJob.DoesNotExist:
            return _back_to_tab()
        job.enabled = not job.enabled
        job.save(update_fields=["enabled"])
        state = "enabled" if job.enabled else "disabled"
        messages.success(request, f"Job “{job.title}” {state}.")
        return _back_to_tab()


class TaskQueueClearView(View):
    """Delete finished rows from the one-off task queue.

    Scoped on purpose: "done" is the routine tidy-up, while a failed row is the
    only place a silently-not-sent invite is visible, so clearing those is a
    separate, deliberate press. Pending/running rows are never touched — the
    scheduler owns them.
    """

    SCOPES = {
        "done": ([ScheduledTask.DONE], "done"),
        "failed": ([ScheduledTask.FAILED], "failed"),
        "all": ([ScheduledTask.DONE, ScheduledTask.FAILED], "finished"),
    }

    def post(self, request):
        statuses, noun = self.SCOPES.get(request.POST.get("scope", "done"), (None, ""))
        if statuses is None:
            return _back_to_tab()
        rows = ScheduledTask.objects.filter(status__in=statuses)
        count = rows.count()
        rows.delete()
        if count:
            messages.success(
                request, f"Cleared {count} {noun} task{'' if count == 1 else 's'}."
            )
        else:
            messages.info(request, f"No {noun} tasks to clear.")
        return _back_to_tab()
