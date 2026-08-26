import logging
import os
import sys
from pathlib import Path

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Commands that run their work inside Django's autoreloader (see run_scheduler's
# docstring for why the scheduler is one of them).
_RELOADING_COMMANDS = ("runserver", "run_scheduler")
# Flags that mean this invocation won't reload after all, so it is the only
# process there will be. --once is run_scheduler's: it does its work and returns
# before the reloader branch is ever reached.
_NO_RELOAD_FLAGS = ("--noreload", "--no-reload", "--once")


def _is_reloader_parent() -> bool:
    """True only in the watcher process the autoreloader forks its worker from.

    That process re-execs a child which repeats every startup line, so anything
    said here is said twice — with `dev.py` running two such commands, a single
    line appeared four times. Django marks the worker child with RUN_MAIN, but
    that alone can't tell the parent apart from a process with no reloader at
    all, so the reloading commands are named explicitly. Every unrecognised
    case falls through to False: better a repeated line than a missing one.
    """
    from django.conf import settings

    if os.environ.get("RUN_MAIN") == "true":
        return False  # we are the worker child
    if not settings.DEBUG:
        return False  # production never reloads
    if any(flag in sys.argv for flag in _NO_RELOAD_FLAGS):
        return False
    return any(command in sys.argv for command in _RELOADING_COMMANDS)


def _process_label() -> str:
    """Which command this process is running.

    The startup line is emitted from core/apps.py in *every* process, so the
    source column reads `[core.apps]` for all of them — true, but it leaves two
    otherwise identical lines with nothing to tell them apart, and `dev.py`
    starts two processes. This is the disambiguator: `runserver` vs
    `run_scheduler`. Falls back to argv[0]'s name for anything started without a
    manage.py subcommand (gunicorn, a bare interpreter).
    """
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            return arg
    name = Path(sys.argv[0]).name if sys.argv and sys.argv[0] else ""
    return name if name and not name.startswith("-") else "python"


def _announce_log_level():
    """Say which level is in force, *at* that level so it is always visible.

    Logging it at a fixed level would defeat the purpose — at INFO it would
    vanish the moment someone set WARNING, i.e. exactly when they are trying to
    confirm the setting took. Emitting at the configured level means the line
    survives whatever the level is, and its absence is itself the signal that
    logging isn't configured the way you think.
    """
    from django.conf import settings

    level_name = getattr(settings, "LOG_LEVEL", "INFO")
    sinks = "console"
    if getattr(settings, "LOG_FILE", ""):
        sinks += f" + file {settings.LOG_FILE}"
    logger.log(
        getattr(logging, level_name, logging.INFO),
        "Using Loglevel: %s (%s, %s, logging to %s)",
        level_name,
        _process_label(),
        getattr(settings, "LOG_LEVEL_SOURCE", "from the environment"),
        sinks,
    )


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core Settings"

    def ready(self):
        # Django configures logging before it populates the app registry, so a
        # handler is in place by the time ready() runs.
        if not _is_reloader_parent():
            _announce_log_level()
