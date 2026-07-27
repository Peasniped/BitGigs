#!/usr/bin/env python
"""One-command dev runner: the web server and the task scheduler together.

    python scripts/dev.py [runserver args...]

Starts ``manage.py runserver`` and ``manage.py run_scheduler`` as child
processes that share this console — output interleaves (ANSI colours intact, no
prefixing) and Ctrl+C stops both. It forces ``--settings=bitgigs.settings.local``
on each, so a dev run can never accidentally boot production settings.

Stdlib only, no dependencies. Extra arguments are forwarded to runserver
(e.g. ``python scripts/dev.py 0.0.0.0:8001``).
"""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANAGE = REPO / "manage.py"
SETTINGS = "bitgigs.settings.local"
GRACE_SECONDS = 8


def _spawn(subcommand, extra=()):
    return subprocess.Popen(
        [sys.executable, str(MANAGE), subcommand, f"--settings={SETTINGS}", *extra],
        cwd=str(REPO),
    )


def _terminate(procs):
    """Ask both children to stop, then hard-kill any that overstay the grace."""
    for name, proc in procs.items():
        if proc.poll() is None:
            proc.terminate()
    deadline = time.monotonic() + GRACE_SECONDS
    for name, proc in procs.items():
        remaining = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            print(f"[dev] {name} didn't stop in time — killing it.", file=sys.stderr)
            proc.kill()


def main():
    # A dev run always uses local settings; make that explicit for anything the
    # children read from the environment too.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS)
    extra = sys.argv[1:]

    procs = {
        "runserver": _spawn("runserver", extra),
        "scheduler": _spawn("run_scheduler"),
    }
    print("[dev] runserver + run_scheduler started. Ctrl+C to stop both.")

    exit_code = 0
    try:
        while True:
            for name, proc in procs.items():
                code = proc.poll()
                if code is not None:
                    # One child exited on its own — take the other down with it.
                    print(f"[dev] {name} exited ({code}); shutting the other down.")
                    exit_code = code or 0
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[dev] stopping…")
    finally:
        _terminate(procs)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
