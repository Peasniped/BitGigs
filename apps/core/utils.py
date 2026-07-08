"""
Shared utilities used across multiple apps.
"""
import re
from datetime import date, time
from decimal import Decimal, InvalidOperation

from django.utils.formats import get_format
from django.utils.text import slugify as _slugify


_DK_TRANSLIT = str.maketrans({
    "æ": "ae", "ø": "oe", "å": "aa",
    "Æ": "ae", "Ø": "oe", "Å": "aa",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "á": "a", "à": "a", "â": "a", "ä": "a",
    "ó": "o", "ò": "o", "ô": "o", "ö": "o",
    "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ç": "c", "ñ": "n", "ß": "ss",
})


def dk_slugify(value: str) -> str:
    """Slugify with Danish/Nordic transliteration applied before Django's ASCII
    slugify, so æ→ae, ø→oe, å→aa (and common accents) survive instead of being
    dropped. 'Jåd Kå Æf' → 'jaad-kaa-aef' (bare slugify would give 'jd-k-f')."""
    if not value:
        return ""
    return _slugify(value.translate(_DK_TRANSLIT))


def parse_int_param(value, default=None):
    """Parse a request parameter as int; *default* on missing/bad input."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_iso_date_param(value):
    """Parse an ISO date string from a request; None on missing/bad input."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def parse_iso_time_param(value):
    """Parse an HH:MM time string from a request; None on missing/bad input."""
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return None


WEEKS_PER_YEAR = Decimal("52")
MONTHS_PER_YEAR = Decimal("12")
# Exact average weeks per month (52/12 = 4.3333...). Matches the Danish
# full-time standard of 160.33 monthly hours (37 * 52/12).
WEEKS_PER_MONTH = WEEKS_PER_YEAR / MONTHS_PER_YEAR


def weekly_to_monthly_hours(weekly_hours: Decimal) -> Decimal:
    """Convert weekly hours to the monthly equivalent (52 weeks / 12 months).

    Returns the unrounded product; callers quantize as needed.
    """
    return weekly_hours * WEEKS_PER_YEAR / MONTHS_PER_YEAR


def date_spans_overlap(a_start, a_end, b_start, b_end) -> bool:
    """True if the closed date spans [a_start, a_end] and [b_start, b_end]
    overlap. A ``None`` end means open-ended (still active); a ``None`` start
    means no span at all (never overlaps)."""
    if a_start is None or b_start is None:
        return False
    return (a_end is None or a_end >= b_start) and (b_end is None or b_end >= a_start)


def active_dated_row(qs, as_of, field="effective_from"):
    """Return the row whose ``field`` is the latest value <= ``as_of``.

    Falls back to the earliest row if none is effective on that date (e.g. a
    row created after the date being queried).
    """
    row = qs.filter(**{f"{field}__lte": as_of}).order_by(f"-{field}").first()
    if row is None:
        row = qs.order_by(field).first()
    return row


def parse_danish_decimal(value: str) -> Decimal | None:
    """Parse a locale-formatted number string (e.g. 1.234,56) into a Decimal.

    Uses the active locale's separators (via ``get_format``): strips the
    thousands separator and normalises the decimal separator to a dot. Returns
    None for empty or unparseable input.
    """
    if not value:
        return None
    thousand_sep = get_format("THOUSAND_SEPARATOR")
    decimal_sep = get_format("DECIMAL_SEPARATOR")
    try:
        normalized = str(value).replace(thousand_sep, "").replace(decimal_sep, ".")
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None

# SVG sanitisation — allowlist parse: only known-static elements/attributes
# survive, so script, foreignObject, event handlers, animation-based attribute
# injection and external references are all dropped structurally (immune to
# the encoding/nesting tricks a regex blocklist can be fooled by).
import xml.etree.ElementTree as _ET

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_ET.register_namespace("", _SVG_NS)
_ET.register_namespace("xlink", _XLINK_NS)

_SVG_ALLOWED_ELEMENTS = {
    "svg", "g", "defs", "symbol", "use", "title", "desc", "style",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "textPath",
    "linearGradient", "radialGradient", "stop",
    "clipPath", "mask", "pattern", "marker",
}
_SVG_ALLOWED_ATTRS = {
    # core / structure
    "id", "class", "style", "transform", "viewBox", "preserveAspectRatio",
    "version", "href",
    # geometry
    "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
    "width", "height", "d", "points", "dx", "dy", "rotate", "pathLength",
    # paint
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "stroke-dashoffset", "stroke-opacity",
    "opacity", "color", "stop-color", "stop-opacity", "vector-effect",
    "clip-path", "clip-rule", "mask", "marker-start", "marker-mid",
    "marker-end", "display", "visibility", "overflow",
    # gradient / pattern / clip plumbing
    "offset", "gradientUnits", "gradientTransform", "spreadMethod",
    "patternUnits", "patternContentUnits", "patternTransform",
    "maskUnits", "maskContentUnits", "clipPathUnits",
    "refX", "refY", "markerWidth", "markerHeight", "markerUnits", "orient",
    # text
    "font-family", "font-size", "font-weight", "font-style", "text-anchor",
    "dominant-baseline", "letter-spacing", "word-spacing", "text-decoration",
    "baseline-shift", "space",
}
# url(...) may only reference same-document fragments: url(#id)
_SVG_URL_REF_RE = re.compile(r"url\(\s*['\"]?\s*(.)", re.IGNORECASE)


def _svg_value_is_safe(value: str) -> bool:
    """Reject values that smuggle scripts or external/data references."""
    compact = re.sub(r"\s+", "", value).lower()
    if "javascript:" in compact or "data:" in compact or "expression(" in compact or "@import" in compact:
        return False
    return all(m.group(1) == "#" for m in _SVG_URL_REF_RE.finditer(value))


def _svg_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sanitize_svg(data: bytes) -> bytes | None:
    """Return the SVG reduced to allowlisted static content, or None if the
    input is not parseable XML with an <svg> root (caller should reject it)."""
    try:
        root = _ET.fromstring(data.decode("utf-8", errors="replace"))
    except _ET.ParseError:
        return None
    if _svg_local_name(root.tag) != "svg":
        return None

    def clean(element):
        for child in list(element):
            name = _svg_local_name(child.tag)
            if name not in _SVG_ALLOWED_ELEMENTS:
                element.remove(child)
                continue
            if name == "style" and not _svg_value_is_safe("".join(child.itertext())):
                element.remove(child)
                continue
            clean(child)
        for attr in list(element.attrib):
            local = _svg_local_name(attr)
            value = element.attrib[attr]
            if local not in _SVG_ALLOWED_ATTRS or not _svg_value_is_safe(value):
                del element.attrib[attr]
            elif local == "href" and not value.startswith("#"):
                del element.attrib[attr]

    clean(root)
    return _ET.tostring(root, encoding="unicode").encode("utf-8")

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
