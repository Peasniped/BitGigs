"""Settings → Jobs tab: a read-mostly view of the schedule table with an
on/off toggle per job. Mirrors the API tab's shape — a context helper called by
core's UserSettingsView, plus small POST views that redirect back to the tab.
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View

from .models import ScheduledJob


def _back_to_tab():
    return redirect(f"{reverse('core:settings')}?tab=jobs")


def jobs_settings_context():
    """Context for the Settings → Jobs tab (called by core.UserSettingsView)."""
    return {"scheduled_jobs": list(ScheduledJob.objects.all())}


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
