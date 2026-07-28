"""The scheduler loop.

Run as a **standalone process** — one code path in dev, bare-metal prod and
Docker, so dev and prod behave the same. It is deliberately *not* an in-process
thread: gunicorn runs several workers and each would fire the loop, so a thread
would need a cross-worker lease. A single process sidesteps that entirely.

    python manage.py run_scheduler [--tick SECONDS] [--once] [--no-reload]

Ticks every SCHEDULER_TICK_SECONDS (default 30), runs whatever is due, sleeps.
Stops cleanly on Ctrl+C (SIGINT) and on SIGTERM (systemd / `docker stop`).

Under ``DEBUG`` it runs inside Django's **autoreloader**, the same one runserver
uses. Without it the loop keeps executing whatever code it started with while
runserver quietly reloads, so a just-edited task handler silently doesn't take
effect — which reads as "the feature doesn't work" rather than "restart me".
Production (DEBUG off) never reloads; a deploy restarts the service anyway.
"""
import logging
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import autoreload, timezone

from scheduler import services
from scheduler.models import ScheduledJob, SchedulerHeartbeat

logger = logging.getLogger("scheduler")

DEFAULT_TICK = 10


class Command(BaseCommand):
    help = "Run the BitGigs task-scheduler loop (a long-lived process)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tick",
            type=float,
            default=None,
            help="Seconds between checks for due jobs (default: SCHEDULER_TICK_SECONDS).",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run whatever is due right now, then exit (no loop).",
        )
        parser.add_argument(
            "--no-reload",
            action="store_true",
            help="Don't restart on code changes (the reloader is on under DEBUG).",
        )

    def handle(self, *args, **options):
        tick = options["tick"] or getattr(
            settings, "SCHEDULER_TICK_SECONDS", DEFAULT_TICK
        )
        self._stop = threading.Event()

        if options["once"]:
            SchedulerHeartbeat.beat()
            services.reap_stuck_tasks(log=logger)
            jobs = services.run_due(log=logger)
            tasks = services.run_pending_tasks(log=logger)
            self.stdout.write(self.style.SUCCESS(
                f"Ran {len(jobs)} due job(s): {jobs}; {len(tasks)} task(s): {tasks}"
            ))
            return

        if settings.DEBUG and not options["no_reload"]:
            # Same reloader as runserver: it re-executes this command in a child
            # process and restarts it whenever a watched file changes.
            autoreload.run_with_reloader(self._loop, tick)
        else:
            self._loop(tick)

    def _loop(self, tick):
        # Under the reloader this runs in a worker thread, so the signal handlers
        # can't be installed (they're main-thread only) — that's fine, the
        # reloader owns Ctrl+C there. _install_signal_handlers already tolerates it.
        self._install_signal_handlers()
        SchedulerHeartbeat.beat()
        self._announce(tick)

        while not self._stop.is_set():
            try:
                SchedulerHeartbeat.beat()
                # First: release rows a previous process died holding, so a crash
                # can't leave work RUNNING for ever with nothing able to touch it.
                services.reap_stuck_tasks(log=logger)
                services.run_due(log=logger)
                services.run_pending_tasks(log=logger)
            except Exception:  # a bug in the engine must not kill the loop
                logger.exception("Scheduler tick failed")
            self._stop.wait(tick)

        self.stdout.write(self.style.WARNING("Scheduler stopped."))

    # ── helpers ──────────────────────────────────────────────────────────────

    def _install_signal_handlers(self):
        # Handlers must be set from the main thread — a management command runs
        # there. SIGTERM may be absent/unsettable on some platforms; ignore that.
        for name in ("SIGTERM", "SIGINT"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self._request_stop)
            except (ValueError, OSError):
                pass

    def _request_stop(self, signum, frame):
        self.stdout.write("")  # break out of a partial line
        self._stop.set()

    def _announce(self, tick):
        self.stdout.write(
            self.style.SUCCESS(f"Scheduler started (tick {tick:g}s). Registered jobs:")
        )
        rows = ScheduledJob.objects.all()
        if not rows:
            self.stdout.write("  (none)")
        for row in rows:
            state = "on" if row.enabled else "OFF"
            nxt = (
                timezone.localtime(row.next_run_at).strftime("%Y-%m-%d %H:%M")
                if row.next_run_at
                else "—"
            )
            self.stdout.write(f"  [{state:>3}] {row.key} — {row.cadence_label}, next {nxt}")
