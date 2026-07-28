#!/usr/bin/env python
"""One-command dev runner: the web server and the task scheduler together.

    python scripts/dev.py [runserver args...]

Starts ``manage.py runserver`` and ``manage.py run_scheduler`` as child
processes that share this console — output interleaves (ANSI colours intact, no
prefixing) and Ctrl+C stops both. It forces ``--settings=bitgigs.settings.local``
on each, so a dev run can never accidentally boot production settings.

Only **one** dev stack may run at a time (see ``_take_lock``): a second one means
a second scheduler draining the same queue, which quietly doubles the rate mail
leaves the server at — enough to trip a provider's sending limit on its own, and
maddening to diagnose. Pass ``--allow-multiple`` if you really do want two.

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
LOCK_PATH = REPO / "instance" / "dev.lock"

# Held open for the life of the process — releasing it is what frees the lock.
_lock_handle = None


def _take_lock():
    """Claim the single-dev-stack lock, or return the PID already holding it.

    An OS **byte-range lock** rather than a PID file we check ourselves: the
    kernel drops it the moment the process dies however it dies, so there is no
    stale lock to clear after a crash or a hard kill. The PID is written into the
    file purely so the second run can name who has it.
    """
    global _lock_handle

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Read the holder's PID *before* locking, and from offset 1: on Windows the
    # locked byte itself can't be read by anyone else, so byte 0 is a throwaway
    # marker and the PID lives after it.
    other = ""
    try:
        with open(LOCK_PATH, "rb") as fh:
            fh.seek(1)
            other = fh.read().decode("utf-8", "replace").strip()
    except OSError:
        pass

    handle = open(LOCK_PATH, "r+b" if LOCK_PATH.exists() else "w+b")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # byte 0 only
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return other or "unknown"

    _lock_handle = handle  # kept open, and therefore locked, for our lifetime
    handle.seek(0)
    handle.truncate()
    handle.write(f"#{os.getpid()}".encode("utf-8"))
    handle.flush()
    return None


def _spawn(subcommand, extra=()):
    return subprocess.Popen(
        [sys.executable, str(MANAGE), subcommand, f"--settings={SETTINGS}", *extra],
        cwd=str(REPO),
    )


def _stop(proc):
    """Stop a child **and its children**.

    Both children run their real work in a grandchild under Django's
    autoreloader, and on Windows killing the parent leaves that grandchild
    orphaned — an invisible scheduler still sending mail. ``terminate()`` is
    already an abrupt TerminateProcess there, so taskkill /T is no less graceful,
    just thorough. (A console Ctrl+C reaches every process in the group anyway;
    this is for the paths that don't go through the console.)
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True
        )
    else:
        proc.terminate()


def _terminate(procs):
    """Ask both children to stop, then hard-kill any that overstay the grace."""
    for name, proc in procs.items():
        if proc.poll() is None:
            _stop(proc)
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
    extra = [a for a in sys.argv[1:] if a != "--allow-multiple"]

    if len(extra) == len(sys.argv[1:]):  # the flag wasn't passed
        holder = _take_lock()
        if holder:
            print(
                f"[dev] A dev stack is already running (PID {holder}).\n"
                "[dev] Starting a second one would run a second scheduler against "
                "the same queue,\n[dev] which doubles how fast mail leaves the "
                "server. Stop the other console first,\n[dev] or pass "
                "--allow-multiple if that's really what you want.",
                file=sys.stderr,
            )
            return 1

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
