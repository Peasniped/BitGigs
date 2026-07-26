"""Workplace-related business logic."""
import logging
import os
import re
from datetime import date, timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# Custom-icon upload constraints, shared by the customize view and data_io
# import so no path can write an unchecked file to media.
ALLOWED_ICON_CONTENT_TYPES = {"image/png", "image/svg+xml"}
ALLOWED_ICON_EXTS = {".png", ".svg"}
MAX_ICON_SIZE = 512 * 1024  # 512 KB

# Appearance-field guards, shared by the customize view and data_io import.
# These values end up inside style attributes and JS-built markup, so only a
# strict hex colour / icon-class shape may ever be stored.
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
ICON_CLASS_RE = re.compile(r"^[A-Za-z0-9-]{1,50}$")  # e.g. "bi-briefcase"


def valid_hex_color(value: str) -> bool:
    """True for '' (unset) or a strict #RRGGBB colour."""
    return value == "" or bool(HEX_COLOR_RE.match(value))


def valid_icon_class(value: str) -> bool:
    """True for '' (unset) or a plausible Bootstrap Icons class name."""
    return value == "" or bool(ICON_CLASS_RE.match(value))


def workplaces_active_in_period(start: date, end: date):
    """Workplaces with at least one term set whose span overlaps [start, end].
    Contracts have no dates of their own, so activity is judged from term-set
    dates (effective_from .. effective_until, the latter open-ended if blank)."""
    from .models import Workplace
    return (
        Workplace.objects.filter(contracts__term_sets__effective_from__lte=end)
        .filter(
            Q(contracts__term_sets__effective_until__isnull=True)
            | Q(contracts__term_sets__effective_until__gte=start)
        )
        .distinct()
    )


def workplaces_active_today():
    """Workplaces with at least one currently active contract (today)."""
    today = timezone.localdate()
    return workplaces_active_in_period(today, today)


def hidden_workplace_count(active_count: int) -> int:
    """How many workplaces are excluded by period filtering.

    Returns 0 unless *active_count* is 0, so the notice only appears when the
    period filter hid everything (per product requirement).
    """
    if active_count > 0:
        return 0
    from .models import Workplace
    return Workplace.objects.count()


# ─── Orphaned custom-icon cleanup ────────────────────────────────────────────
# Deleting a Workplace does not remove its uploaded icon file (Django's
# FileField leaves the file on disk), so the media/workplace_icons/ directory
# slowly accumulates orphans. These helpers remove any file there that no
# Workplace.custom_icon points at.

ICON_SUBDIR = "workplace_icons"
ICON_PRUNE_INTERVAL = timedelta(hours=24)


def _referenced_icon_names() -> set:
    """Base filenames every Workplace.custom_icon currently points at."""
    from .models import Workplace
    names = set()
    for stored in (
        Workplace.objects.exclude(custom_icon="")
        .values_list("custom_icon", flat=True)
    ):
        if stored:
            names.add(os.path.basename(stored))
    return names


def prune_orphan_icons(dry_run: bool = False) -> list:
    """Remove files in MEDIA_ROOT/workplace_icons/ that no workplace references.

    Returns the list of orphan filenames removed (or, when *dry_run*, that would
    be removed). Safe to call when the directory does not exist yet.
    """
    icon_dir = os.path.join(settings.MEDIA_ROOT, ICON_SUBDIR)
    if not os.path.isdir(icon_dir):
        return []

    referenced = _referenced_icon_names()
    removed = []
    for name in os.listdir(icon_dir):
        path = os.path.join(icon_dir, name)
        if not os.path.isfile(path) or name in referenced:
            continue
        removed.append(name)
        if dry_run:
            continue
        try:
            os.remove(path)
        except OSError:
            logger.warning("Could not remove orphaned workplace icon %s", name, exc_info=True)
            removed.pop()

    if removed:
        verb = "Would prune" if dry_run else "Pruned"
        logger.info("%s %d orphaned workplace icon(s): %s", verb, len(removed), ", ".join(sorted(removed)))
    return removed


def maybe_prune_orphan_icons() -> None:
    """Run prune_orphan_icons at most once per ICON_PRUNE_INTERVAL.

    The last-run time is the mtime of settings.ICON_PRUNE_MARKER_PATH. Called
    opportunistically from a normal request (the dashboard), so it never raises
    into the page — any failure is logged and swallowed. Does nothing unless
    settings.ICON_PRUNE_AUTO is on (off in dev, where a db.sqlite3.bak may share
    the media directory — see the setting's comment).
    """
    if not getattr(settings, "ICON_PRUNE_AUTO", True):
        return
    marker = str(settings.ICON_PRUNE_MARKER_PATH)
    try:
        now = timezone.now().timestamp()
        try:
            due = (now - os.path.getmtime(marker)) >= ICON_PRUNE_INTERVAL.total_seconds()
        except OSError:
            due = True  # marker missing → first run
        if not due:
            return
        # Stamp the marker *before* pruning so a slow/failing prune can't make
        # every request retry it; a genuine 24h cadence is enough.
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(timezone.now().isoformat())
        prune_orphan_icons()
    except Exception:  # never break the page over housekeeping
        logger.warning("Opportunistic workplace-icon prune failed", exc_info=True)
