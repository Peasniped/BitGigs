"""Workplace-related business logic."""
import re
from datetime import date

from django.db.models import Q
from django.utils import timezone

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
