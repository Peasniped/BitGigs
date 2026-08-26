#!/usr/bin/env python
"""One-command dev runner: the web server and the task scheduler together.

    python scripts/dev.py [runserver args...]

Starts ``manage.py runserver`` and ``manage.py run_scheduler`` as child
processes that share this console — output interleaves (ANSI colours intact, no
prefixing) and Ctrl+C stops both. It forces ``--settings=config.settings.local``
on each, so a dev run can never accidentally boot production settings.

Only **one** dev stack may run at a time (see ``_take_lock``): a second one means
a second scheduler draining the same queue, which quietly doubles the rate mail
leaves the server at — enough to trip a provider's sending limit on its own, and
maddening to diagnose. Pass ``--allow-multiple`` if you really do want two.

No third-party dependencies. Extra arguments are forwarded to runserver
(e.g. ``python scripts/dev.py 0.0.0.0:8001``).
"""
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANAGE = REPO / "manage.py"
SETTINGS = "config.settings.local"
GRACE_SECONDS = 8
LOCK_PATH = REPO / "instance" / "dev.lock"

# The launcher writes to the same console as the two processes it starts, so it
# speaks their language rather than bare print()s — one console should read as
# one thing. This is not a Django process (it runs before django.setup() and has
# no settings), but core.logformat is stdlib-only by design, so borrowing the
# formatter costs nothing and keeps the layout defined in exactly one place.
sys.path.insert(0, str(REPO / "apps"))
from core.logformat import BitGigsFormatter  # noqa: E402

logger = logging.getLogger("dev")


def _setup_logging():
    """Wire `dev` to stderr with the app's formatter.

    Fixed at INFO rather than following LOG_LEVEL: this logger carries five
    messages, all of them "the launcher did something you need to know about",
    and reading LOG_LEVEL properly would mean duplicating settings' .env loader
    out here — which is exactly the kind of second copy that drifts.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(BitGigsFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

# Exit codes that mean "the console Ctrl+C took this child down", i.e. a clean
# stop rather than a crash. A console Ctrl+C reaches every process in the group,
# so a child usually dies of it before our own KeyboardInterrupt is raised —
# without this the shutdown is reported as "runserver exited (-1073741510)" and
# leaves a non-zero exit code behind.
CTRL_C_EXIT_CODES = {
    0xC000013A,   # STATUS_CONTROL_C_EXIT, as Windows reports it
    -1073741510,  # the same value, signed
    -signal.SIGINT,  # POSIX: killed by SIGINT
}

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


def _wait(proc, timeout):
    """``proc.wait()``, but a Ctrl+C arriving *during* it doesn't abort the wait.

    Pressing Ctrl+C again because the first press seemed to do nothing is the
    normal human response, and it used to land here — in the ``finally`` — where
    it escaped as a traceback and turned a clean stop into what looks like a
    crash. Shutdown has already been asked for; further presses are noise."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except KeyboardInterrupt:
            continue


def _terminate(procs):
    """Ask both children to stop, then hard-kill any that overstay the grace."""
    for name, proc in procs.items():
        if proc.poll() is None:
            try:
                _stop(proc)
            except KeyboardInterrupt:
                pass
    deadline = time.monotonic() + GRACE_SECONDS
    for name, proc in procs.items():
        remaining = max(0.0, deadline - time.monotonic())
        try:
            _wait(proc, remaining)
        except subprocess.TimeoutExpired:
            logger.warning("%s didn't stop in time — killing it.", name)
            proc.kill()


# Set by the Ctrl+C handler below; the poll loop watches it. A flag rather than
# a raised KeyboardInterrupt so shutdown runs at a known point in the loop
# instead of wherever the main thread happened to be.
_interrupted = False


def _on_interrupt(signum, frame):
    global _interrupted
    _interrupted = True


def _install_interrupt_handler():
    """Register Ctrl+C (and Windows' Ctrl+Break) as the ordinary way to stop.

    Without an explicit handler the console's default one can terminate us
    outright — the children are then orphaned and the console shows an abrupt
    exit code instead of a stop."""
    for name in ("SIGINT", "SIGBREAK", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _on_interrupt)
        except (ValueError, OSError):
            pass


def main():
    global _interrupted

    # A dev run always uses local settings; make that explicit for anything the
    # children read from the environment too.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS)
    _setup_logging()
    _install_interrupt_handler()
    extra = [a for a in sys.argv[1:] if a != "--allow-multiple"]

    if len(extra) == len(sys.argv[1:]):  # the flag wasn't passed
        holder = _take_lock()
        if holder:
            logger.error("A dev stack is already running (PID %s).", holder)
            logger.error(
                "Starting a second one would run a second scheduler against the "
                "same queue, which doubles how fast mail leaves the server. Stop "
                "the other console first, or pass --allow-multiple if that's "
                "really what you want."
            )
            return 1

    procs = {
        "runserver": _spawn("runserver", extra),
        "scheduler": _spawn("run_scheduler"),
    }
    logger.info("runserver + run_scheduler started. Ctrl+C to stop both.")

    exit_code = 0
    try:
        while not _interrupted:
            done = [(n, p.poll()) for n, p in procs.items() if p.poll() is not None]
            if done:
                name, code = done[0]
                if code in CTRL_C_EXIT_CODES:
                    # The console Ctrl+C reached the children before it reached
                    # us. That is the stop we were asked for, not a failure.
                    _interrupted = True
                else:
                    # One child exited on its own — take the other down with it.
                    logger.warning(
                        "%s exited (%s); shutting the other down.", name, code
                    )
                    exit_code = code or 0
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        _interrupted = True  # a press the handler didn't catch
    if _interrupted:
        print()  # break out of the line the console's ^C echo left open
        logger.info("Stopping…")
    try:
        _terminate(procs)
    except KeyboardInterrupt:
        pass
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
