"""
Shared utilities used across multiple apps.
"""
import re
from decimal import Decimal


WEEKS_PER_MONTH = Decimal("4.33")

# SVG sanitisation — strip active content that could execute in the browser.
_SVG_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_SVG_SELF_CLOSING_SCRIPT_RE = re.compile(r"<script\b[^>]*/>", re.IGNORECASE)
_SVG_EVENT_ATTR_RE = re.compile(
    r"""\s+on[a-zA-Z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.IGNORECASE
)
_SVG_JS_URI_RE = re.compile(
    r"""((?:xlink:)?href)\s*=\s*(["'])\s*javascript:[^"']*\2""", re.IGNORECASE
)


def sanitize_svg(data: bytes) -> bytes:
    """Remove <script> elements, on* event handlers and javascript: URIs from SVG bytes."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    text = _SVG_SCRIPT_RE.sub("", text)
    text = _SVG_SELF_CLOSING_SCRIPT_RE.sub("", text)
    text = _SVG_EVENT_ATTR_RE.sub("", text)
    text = _SVG_JS_URI_RE.sub(r'\1=\2#\2', text)
    return text.encode("utf-8")

# Palette of pleasant colours for workplace avatars
_AVATAR_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#ef4444", "#f97316",
    "#eab308", "#22c55e", "#14b8a6", "#06b6d4", "#3b82f6",
]


def avatar_for_name(name: str) -> tuple[str, str]:
    """Return (initials, hex colour) for a workplace name."""
    parts = name.strip().split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[1][0]).upper()
    elif parts:
        initials = parts[0][:2].upper()
    else:
        initials = "?"
    color = _AVATAR_COLORS[sum(ord(c) for c in name) % len(_AVATAR_COLORS)]
    return initials, color


def prev_next_month(year: int, month: int) -> tuple[int, int, int, int]:
    """Return (prev_year, prev_month, next_year, next_month)."""
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    return prev_year, prev_month, next_year, next_month
