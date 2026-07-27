"""Engine tests for the task scheduler."""
from datetime import time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from scheduler import registry, services
from scheduler.models import ScheduledJob


class ComputeNextRunTests(TestCase):
    def test_interval_schedules_one_slot_ahead(self):
        row = ScheduledJob(
            key="x", kind=ScheduledJob.KIND_INTERVAL, interval_seconds=300
        )
        now = timezone.now()
        self.assertEqual(
            services.compute_next_run(row, now), now + timedelta(seconds=300)
        )

    def test_daily_picks_todays_slot_when_still_ahead(self):
        row = ScheduledJob(
            key="x", kind=ScheduledJob.KIND_DAILY, daily_time=time(23, 59)
        )
        # A moment early in the local day → today's 23:59 is still ahead.
        base = timezone.localtime(timezone.now()).replace(
            hour=0, minute=1, second=0, microsecond=0
        )
        nxt = timezone.localtime(services.compute_next_run(row, base))
        self.assertEqual((nxt.hour, nxt.minute), (23, 59))
        self.assertEqual(nxt.date(), base.date())

    def test_overdue_daily_fires_once_not_a_backlog(self):
        row = ScheduledJob(
            key="x", kind=ScheduledJob.KIND_DAILY, daily_time=time(0, 1)
        )
        # Late in the local day → 00:01 already passed, so next is tomorrow.
        base = timezone.localtime(timezone.now()).replace(
            hour=23, minute=0, second=0, microsecond=0
        )
        nxt = timezone.localtime(services.compute_next_run(row, base))
        self.assertEqual((nxt.hour, nxt.minute), (0, 1))
        self.assertEqual(nxt.date(), (base + timedelta(days=1)).date())


class RunJobTests(TestCase):
    def setUp(self):
        # The post_migrate seed already created the shipped row; start clean so
        # our fixtures own the table (rolled back after each test by TestCase).
        ScheduledJob.objects.all().delete()

    def _row(self, **kw):
        defaults = dict(
            key="prune_workplace_icons",
            kind=ScheduledJob.KIND_DAILY,
            daily_time=time(3, 30),
            next_run_at=timezone.now(),
        )
        defaults.update(kw)
        return ScheduledJob.objects.create(**defaults)

    def test_success_records_ok_and_duration(self):
        row = self._row()
        job = registry.Job(
            id="prune_workplace_icons", title="t", description="d",
            func=lambda: "did a thing", daily_at=time(3, 30),
        )
        with mock.patch.object(registry, "get", return_value=job):
            status = services.run_job(row)
        row.refresh_from_db()
        self.assertEqual(status, ScheduledJob.STATUS_OK)
        self.assertEqual(row.last_status, ScheduledJob.STATUS_OK)
        self.assertIsNotNone(row.last_run_at)
        self.assertIsNotNone(row.last_duration_ms)
        self.assertEqual(row.last_error, "")

    def test_failure_is_caught_and_recorded(self):
        row = self._row()

        def boom():
            raise ValueError("nope")

        job = registry.Job(
            id="prune_workplace_icons", title="t", description="d",
            func=boom, daily_at=time(3, 30),
        )
        with mock.patch.object(registry, "get", return_value=job):
            status = services.run_job(row)  # must not raise
        row.refresh_from_db()
        self.assertEqual(status, ScheduledJob.STATUS_ERROR)
        self.assertIn("ValueError: nope", row.last_error)

    def test_defunct_row_is_disabled(self):
        row = self._row(key="ghost-job")
        with mock.patch.object(registry, "get", return_value=None):
            status = services.run_job(row)
        row.refresh_from_db()
        self.assertEqual(status, ScheduledJob.STATUS_ERROR)
        self.assertFalse(row.enabled)


class ClaimAndDueTests(TestCase):
    def setUp(self):
        ScheduledJob.objects.all().delete()

    def test_claim_advances_next_run_and_is_exclusive(self):
        now = timezone.now()
        row = ScheduledJob.objects.create(
            key="prune_workplace_icons",
            kind=ScheduledJob.KIND_INTERVAL,
            interval_seconds=60,
            next_run_at=now - timedelta(seconds=1),
        )
        self.assertTrue(services.claim(row, now))
        row.refresh_from_db()
        self.assertGreater(row.next_run_at, now)
        # A second loop holding the stale next_run_at loses the compare-and-set.
        stale = ScheduledJob(pk=row.pk, next_run_at=now - timedelta(seconds=1),
                             kind=ScheduledJob.KIND_INTERVAL, interval_seconds=60)
        self.assertFalse(services.claim(stale, now))

    def test_run_due_runs_due_and_skips_disabled(self):
        now = timezone.now()
        due = ScheduledJob.objects.create(
            key="prune_workplace_icons",
            kind=ScheduledJob.KIND_INTERVAL, interval_seconds=60,
            next_run_at=now - timedelta(seconds=1),
        )
        ScheduledJob.objects.create(
            key="ghost", enabled=False,
            kind=ScheduledJob.KIND_INTERVAL, interval_seconds=60,
            next_run_at=now - timedelta(seconds=1),
        )
        job = registry.Job(
            id="prune_workplace_icons", title="t", description="d",
            func=lambda: None, every=timedelta(seconds=60),
        )
        with mock.patch.object(registry, "get",
                               side_effect=lambda k: job if k == due.key else None):
            ran = services.run_due(now)
        self.assertEqual(ran, ["prune_workplace_icons"])


class SeedTests(TestCase):
    def test_seed_creates_a_row_per_registered_job(self):
        # post_migrate already seeded; assert the shipped job has its row.
        keys = set(ScheduledJob.objects.values_list("key", flat=True))
        self.assertTrue(registry.ids().issubset(keys))

    def test_seed_removes_defunct_rows(self):
        from scheduler import signals

        ScheduledJob.objects.create(
            key="was-removed", kind=ScheduledJob.KIND_INTERVAL,
            interval_seconds=60, next_run_at=timezone.now(),
        )
        signals.seed_scheduled_jobs(sender=None)
        self.assertFalse(ScheduledJob.objects.filter(key="was-removed").exists())
        self.assertTrue(ScheduledJob.objects.filter(key="prune_workplace_icons").exists())


class JobsSettingsTabTests(TestCase):
    """The Settings → Jobs tab and its toggle endpoint."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_tab_renders_with_the_job(self):
        resp = self.client.get(reverse("core:settings") + "?tab=jobs")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Scheduled jobs")
        self.assertContains(resp, "prune_workplace_icons")

    def test_toggle_flips_enabled_and_redirects_to_tab(self):
        job = ScheduledJob.objects.get(key="prune_workplace_icons")
        self.assertTrue(job.enabled)
        resp = self.client.post(reverse("scheduler:job-toggle", args=[job.pk]))
        self.assertRedirects(resp, reverse("core:settings") + "?tab=jobs")
        job.refresh_from_db()
        self.assertFalse(job.enabled)
        # Toggling again turns it back on.
        self.client.post(reverse("scheduler:job-toggle", args=[job.pk]))
        job.refresh_from_db()
        self.assertTrue(job.enabled)

    def test_toggle_of_missing_job_is_a_noop_redirect(self):
        resp = self.client.post(reverse("scheduler:job-toggle", args=[999999]))
        self.assertRedirects(resp, reverse("core:settings") + "?tab=jobs")
