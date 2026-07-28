"""Engine tests for the task scheduler."""
from datetime import time, timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from scheduler import registry, services, tasks, views
from scheduler.models import ScheduledJob, ScheduledTask, SchedulerHeartbeat


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

    def test_status_endpoint_reports_queue_jobs_and_heartbeat(self):
        SchedulerHeartbeat.beat()
        ScheduledTask.objects.create(task="demo.queued")
        ScheduledTask.objects.create(
            task="demo.finished", status=ScheduledTask.DONE,
            finished_at=timezone.now(), result="all good",
        )
        data = self.client.get(reverse("scheduler:status")).json()
        self.assertTrue(data["alive"])
        self.assertIsNotNone(data["seconds_since"])
        self.assertEqual([t["task"] for t in data["active"]], ["demo.queued"])
        self.assertEqual([t["result"] for t in data["recent"]], ["all good"])
        self.assertEqual(data["done_count"], 1)
        self.assertEqual(data["failed_count"], 0)
        job = ScheduledJob.objects.get(key="prune_workplace_icons")
        self.assertIn(job.pk, [j["id"] for j in data["jobs"]])

    def test_clear_done_leaves_failed_and_pending_alone(self):
        pending = ScheduledTask.objects.create(task="demo.pending")
        ScheduledTask.objects.create(
            task="demo.done", status=ScheduledTask.DONE, finished_at=timezone.now()
        )
        failed = ScheduledTask.objects.create(
            task="demo.failed", status=ScheduledTask.FAILED,
            finished_at=timezone.now(), last_error="boom",
        )
        resp = self.client.post(reverse("scheduler:tasks-clear"), {"scope": "done"})
        self.assertRedirects(resp, reverse("core:settings") + "?tab=jobs")
        self.assertQuerySetEqual(
            ScheduledTask.objects.order_by("task"), [failed, pending]
        )

    def test_clear_failed_and_clear_all(self):
        ScheduledTask.objects.create(
            task="demo.done", status=ScheduledTask.DONE, finished_at=timezone.now()
        )
        ScheduledTask.objects.create(
            task="demo.failed", status=ScheduledTask.FAILED, finished_at=timezone.now()
        )
        self.client.post(reverse("scheduler:tasks-clear"), {"scope": "failed"})
        self.assertEqual(
            list(ScheduledTask.objects.values_list("status", flat=True)),
            [ScheduledTask.DONE],
        )
        self.client.post(reverse("scheduler:tasks-clear"), {"scope": "all"})
        self.assertFalse(ScheduledTask.objects.exists())

    def test_clear_with_an_unknown_scope_deletes_nothing(self):
        ScheduledTask.objects.create(
            task="demo.done", status=ScheduledTask.DONE, finished_at=timezone.now()
        )
        self.client.post(reverse("scheduler:tasks-clear"), {"scope": "everything"})
        self.assertEqual(ScheduledTask.objects.count(), 1)

    def test_a_drained_batch_stays_visible(self):
        """A month's worth of invites finishing must not scroll itself out of the
        table — the old 10-row cap made a 31-shift send look like rows vanishing."""
        for i in range(31):
            ScheduledTask.objects.create(
                task="demo.done", status=ScheduledTask.DONE,
                finished_at=timezone.now() - timedelta(seconds=i),
            )
        data = self.client.get(reverse("scheduler:status")).json()
        self.assertEqual(len(data["recent"]), 31)
        self.assertEqual(data["hidden_count"], 0)

    def test_rows_past_the_cap_are_counted_not_silently_dropped(self):
        for i in range(views.RECENT_TASK_LIMIT + 5):
            ScheduledTask.objects.create(
                task="demo.done", status=ScheduledTask.DONE,
                finished_at=timezone.now() - timedelta(seconds=i),
            )
        data = self.client.get(reverse("scheduler:status")).json()
        self.assertEqual(len(data["recent"]), views.RECENT_TASK_LIMIT)
        self.assertEqual(data["hidden_count"], 5)


class TaskRetryTests(TestCase):
    """Retrying a failed queue row — the only route back for work whose origin is
    gone (a calendar CANCEL whose shift was deleted has no shift left to press)."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()
        self.ran = []
        tasks.register("demo.retryable")(lambda payload: self.ran.append(payload))
        self.addCleanup(tasks._HANDLERS.pop, "demo.retryable", None)

    def _failed(self, task="demo.retryable", **payload):
        return ScheduledTask.objects.create(
            task=task, payload=payload, status=ScheduledTask.FAILED,
            finished_at=timezone.now(), last_error="refused", attempts=1,
        )

    def test_retry_requeues_the_payload_and_retires_the_failed_row(self):
        failed = self._failed(invite_uid="abc")
        resp = self.client.post(reverse("scheduler:task-retry"), {"id": failed.pk})
        self.assertRedirects(resp, reverse("core:settings") + "?tab=jobs")
        self.assertFalse(ScheduledTask.objects.filter(pk=failed.pk).exists())
        fresh = ScheduledTask.objects.get()
        self.assertEqual(fresh.status, ScheduledTask.PENDING)
        self.assertEqual(fresh.payload["invite_uid"], "abc")
        # Labelled so it reads as a second attempt next to the one it follows.
        self.assertEqual(fresh.label, "demo.retryable (retry)")

    def test_retry_is_a_deliberate_probe_past_the_mail_breaker(self):
        """queued_at is re-stamped: the breaker only lets through messages queued
        after the failures it is reacting to, and a hand-pressed retry is exactly
        that (see core.mail.blocked_reason)."""
        old = (timezone.now() - timedelta(hours=2)).isoformat()
        failed = self._failed(queued_at=old)
        self.client.post(reverse("scheduler:task-retry"), {"id": failed.pk})
        self.assertGreater(ScheduledTask.objects.get().payload["queued_at"], old)

    def test_retry_does_not_fire_the_on_clear_hook(self):
        """Retrying is the opposite of dismissing — the failure must not be
        acknowledged away while a fresh attempt is still in flight."""
        cleared = []
        tasks.register("demo.hooked", on_clear=cleared.append)(lambda payload: None)
        self.addCleanup(tasks._HANDLERS.pop, "demo.hooked", None)
        self.addCleanup(tasks._CLEAR_HOOKS.pop, "demo.hooked", None)
        failed = self._failed(task="demo.hooked")
        self.client.post(reverse("scheduler:task-retry"), {"id": failed.pk})
        self.assertEqual(cleared, [])

    def test_retry_of_a_done_or_missing_row_changes_nothing(self):
        done = ScheduledTask.objects.create(
            task="demo.retryable", status=ScheduledTask.DONE, finished_at=timezone.now()
        )
        self.client.post(reverse("scheduler:task-retry"), {"id": done.pk})
        self.client.post(reverse("scheduler:task-retry"), {"id": 999999})
        self.assertQuerySetEqual(ScheduledTask.objects.all(), [done])

    def test_a_row_with_no_handler_left_is_refused(self):
        failed = self._failed(task="demo.long_gone")
        self.client.post(reverse("scheduler:task-retry"), {"id": failed.pk})
        self.assertQuerySetEqual(ScheduledTask.objects.all(), [failed])

    def test_status_marks_only_runnable_failures_retryable(self):
        self._failed()
        self._failed(task="demo.long_gone")
        ScheduledTask.objects.create(
            task="demo.retryable", status=ScheduledTask.DONE, finished_at=timezone.now()
        )
        recent = self.client.get(reverse("scheduler:status")).json()["recent"]
        self.assertEqual(
            {t["task"] for t in recent if t["can_retry"]}, {"demo.retryable"}
        )


class TaskQueueTests(TestCase):
    def test_enqueue_creates_a_pending_task(self):
        task = tasks.enqueue("demo.thing", {"a": 1})
        self.assertEqual(task.status, ScheduledTask.PENDING)
        self.assertEqual(task.payload["a"], 1)
        # Every payload is stamped with when it was queued (see enqueue).
        self.assertIn("queued_at", task.payload)

    def test_process_success_marks_done_with_result(self):
        task = tasks.enqueue("demo.ok")
        with mock.patch.object(tasks, "get_handler", return_value=lambda p: "did it"):
            status = services.process_task(task)
        task.refresh_from_db()
        self.assertEqual(status, ScheduledTask.DONE)
        self.assertEqual(task.status, ScheduledTask.DONE)
        self.assertEqual(task.result, "did it")
        self.assertEqual(task.attempts, 1)

    def test_process_failure_without_retries_marks_failed(self):
        task = tasks.enqueue("demo.boom", max_attempts=1)

        def boom(payload):
            raise ValueError("nope")

        with mock.patch.object(tasks, "get_handler", return_value=boom):
            status = services.process_task(task)
        task.refresh_from_db()
        self.assertEqual(status, ScheduledTask.FAILED)
        self.assertIn("ValueError: nope", task.last_error)

    def test_process_failure_with_retries_requeues(self):
        task = tasks.enqueue("demo.flaky", max_attempts=2)

        def boom(payload):
            raise RuntimeError("temporary")

        with mock.patch.object(tasks, "get_handler", return_value=boom):
            status = services.process_task(task)
        task.refresh_from_db()
        self.assertEqual(status, ScheduledTask.PENDING)  # back in the queue
        self.assertEqual(task.attempts, 1)
        self.assertGreater(task.run_at, timezone.now())  # backed off

    def test_missing_handler_fails_the_task(self):
        task = tasks.enqueue("demo.unregistered")
        with mock.patch.object(tasks, "get_handler", return_value=None):
            status = services.process_task(task)
        self.assertEqual(status, ScheduledTask.FAILED)

    def test_run_pending_runs_due_and_leaves_future_alone(self):
        due = tasks.enqueue("demo.due")
        future = tasks.enqueue("demo.future", run_at=timezone.now() + timedelta(hours=1))
        with mock.patch.object(tasks, "get_handler", return_value=lambda p: None):
            ran = services.run_pending_tasks()
        self.assertEqual(ran, ["demo.due"])
        future.refresh_from_db()
        self.assertEqual(future.status, ScheduledTask.PENDING)

    def test_claim_task_is_exclusive(self):
        task = tasks.enqueue("demo.claim")
        self.assertTrue(services.claim_task(task))
        self.assertFalse(services.claim_task(task))  # already RUNNING

    def test_label_uses_the_handlers_title_and_falls_back_to_the_id(self):
        titled = tasks.enqueue("calendar.send_invite_mail")  # registered with a title
        self.assertEqual(titled.label, "Send calendar invite")
        self.assertEqual(tasks.enqueue("demo.untitled").label, "demo.untitled")

    def test_prune_keeps_only_the_newest_finished(self):
        for i in range(5):
            ScheduledTask.objects.create(
                task=f"demo.old{i}", status=ScheduledTask.DONE,
                finished_at=timezone.now() - timedelta(minutes=i),
            )
        ScheduledTask.prune(keep=2)
        self.assertEqual(
            ScheduledTask.objects.filter(status=ScheduledTask.DONE).count(), 2
        )


class HeartbeatTests(TestCase):
    def test_beat_then_alive(self):
        SchedulerHeartbeat.beat()
        self.assertTrue(SchedulerHeartbeat.is_alive())
        self.assertIsNotNone(SchedulerHeartbeat.seconds_since())

    def test_no_beat_is_not_alive(self):
        self.assertFalse(SchedulerHeartbeat.is_alive())
        self.assertIsNone(SchedulerHeartbeat.seconds_since())

    def test_stale_beat_is_not_alive(self):
        SchedulerHeartbeat.objects.create(
            pk=1, beat_at=timezone.now() - timedelta(hours=1)
        )
        self.assertFalse(SchedulerHeartbeat.is_alive())


class InviteTestEnqueueTests(TestCase):
    """The 'send myself a test invite' button now enqueues instead of blocking."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_configured_send_enqueues_and_returns_instantly(self):
        from core.models import EmailSettings

        with mock.patch.object(EmailSettings, "is_configured_for", return_value=True):
            resp = self.client.post(
                reverse("calendar_sync:invite-test"), {"to": "me@example.com"}
            )
        self.assertEqual(resp.status_code, 302)
        task = ScheduledTask.objects.get(task="calendar.test_invite")
        self.assertEqual(task.status, ScheduledTask.PENDING)
        self.assertEqual(task.payload["to"], "me@example.com")

    def test_unconfigured_email_errors_and_enqueues_nothing(self):
        from core.models import EmailSettings

        with mock.patch.object(EmailSettings, "is_configured_for", return_value=False):
            resp = self.client.post(
                reverse("calendar_sync:invite-test"), {"to": "me@example.com"}
            )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ScheduledTask.objects.exists())
