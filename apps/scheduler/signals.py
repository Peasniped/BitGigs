"""post_migrate hook: reconcile the DB schedule table against the registry.

A newly registered job gets a row seeded from its default cadence; a job that
was removed from the registry has its now-defunct row deleted (these are system
rows, not user data). An existing row is left untouched — the operator may have
retuned its cadence or disabled it, and that must survive a redeploy.
"""


def seed_scheduled_jobs(sender, **kwargs):
    from . import registry, services
    from .models import ScheduledJob

    known = registry.ids()

    # Drop rows for jobs that no longer exist.
    ScheduledJob.objects.exclude(key__in=known).delete()

    for job in registry.all_jobs():
        if ScheduledJob.objects.filter(key=job.id).exists():
            continue
        row = ScheduledJob(
            key=job.id,
            kind=job.kind,
            interval_seconds=job.interval_seconds,
            daily_time=job.daily_time,
        )
        # An interval job should start running promptly; a daily job waits for
        # its first real slot rather than firing the moment it's seeded.
        if job.kind == ScheduledJob.KIND_INTERVAL:
            from django.utils import timezone

            row.next_run_at = timezone.now()
        else:
            row.next_run_at = services.compute_next_run(row)
        row.save()
