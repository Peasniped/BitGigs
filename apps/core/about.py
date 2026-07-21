"""Deployment facts for the Settings → About tab.

Everything here is read-only introspection of the running process: what version
it is, how it was built, how it's deployed, and which database it's talking to.
Baked build metadata (the git commit and build date) arrives via environment
variables set at Docker build time; on a raw-Python checkout none of those are
set, so we fall back to reading the local git repo — a dev install still shows
something useful. No value gathered here ever leaves the server.
"""
from __future__ import annotations

import os
import platform
import random
import subprocess
import sys
from pathlib import Path

import django
from django.conf import settings
from django.utils import timezone

import bitgigs


# Subtitles shown under the app name on the About hero — one picked at random per
# page load. Curate this list freely; a random one is chosen from whatever's here.
SLOGANS = [
    "Shifts, salary, sorted",
    "From clocked-in to cashed-out",
    "Gross in, net out",
    "Your paycheck, before payday",
    "Because SKAT won't do the math for you",
    "Because “roughly” isn't a salary",
    "Shifts today, kroner tomorrow",
    "From vagt to værdi",
    "Little bits, real gigs",
]


def slogan():
    """A random subtitle for the About hero, or a safe default if the list is
    somehow emptied."""
    return random.choice(SLOGANS) if SLOGANS else "Shifts & Danish net-pay tracking"


def _git(*args):
    """Run a read-only ``git`` command from the repo root, or return ``None``.

    Guarded against every way it can fail off a dev machine: git not installed
    (``FileNotFoundError``), not a checkout (``.git`` excluded from the Docker
    image), a slow/hung call (timeout). Never raises."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value or None


def app_version():
    return getattr(bitgigs, "__version__", "unknown")


def build_commit():
    """Short git commit the running code was built from, or ``None``."""
    return os.environ.get("BITGIGS_GIT_COMMIT") or _git("rev-parse", "--short", "HEAD")


def build_date():
    """ISO date the image was built (Docker) or the checked-out commit's date."""
    return os.environ.get("BITGIGS_BUILD_DATE") or _git(
        "log", "-1", "--format=%cd", "--date=short"
    )


def deployment():
    """How the app is being served, as a ``(label, icon)`` pair.

    Trusts the explicit ``BITGIGS_DEPLOYMENT`` env var (the Docker image sets it
    to ``docker``), then sniffs for the container marker file, else calls it a
    raw-Python install."""
    declared = os.environ.get("BITGIGS_DEPLOYMENT", "").strip().lower()
    if declared == "docker" or Path("/.dockerenv").exists():
        return ("Docker", "bi-box-seam")
    return ("Raw Python", "bi-terminal")


def server_kind():
    """Best-effort name of the WSGI server, or ``None`` under bare imports."""
    if "gunicorn" in sys.modules:
        return "Gunicorn"
    argv = " ".join(sys.argv)
    if "runserver" in argv:
        return "Django dev server"
    return None


def database():
    """The default database as a ``(label, icon)`` pair, from its engine."""
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    if "postgres" in engine:
        return ("PostgreSQL", "bi-database-fill")
    if "sqlite" in engine:
        return ("SQLite", "bi-database")
    return (engine or "Unknown", "bi-database")


def about_context(request=None):
    """Everything the About tab renders. ``request`` supplies the host header."""
    deploy_label, deploy_icon = deployment()
    db_label, db_icon = database()
    return {
        "about_slogan": slogan(),
        "about_version": app_version(),
        "about_commit": build_commit(),
        "about_build_date": build_date(),
        "about_deployment": deploy_label,
        "about_deployment_icon": deploy_icon,
        "about_server": server_kind(),
        "about_python": platform.python_version(),
        "about_django": django.get_version(),
        "about_database": db_label,
        "about_database_icon": db_icon,
        "about_debug": settings.DEBUG,
        "about_timezone": settings.TIME_ZONE,
        "about_server_time": timezone.localtime(),
        "about_sso_enabled": settings.SSO_ENABLED,
        "about_host": request.get_host() if request is not None else None,
    }
