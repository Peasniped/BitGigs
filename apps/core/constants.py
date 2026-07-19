"""Shared UI constants.

Kept import-free so any app can use them without dependency cycles
(workplaces re-imports the swatch rows from here; core must never import
from workplaces at module level).
"""

# Per-workplace customize-modal swatches (avatar background / accent).
BG_COLOR_CHOICES = [
    "#c7d2fe", "#ddd6fe", "#fbcfe8", "#fecaca", "#fed7aa",
    "#fef08a", "#bbf7d0", "#99f6e4", "#bfdbfe", "#ffffff",
]

ACCENT_COLOR_CHOICES = [
    "#0e61de", "#8b5cf6", "#ec4899", "#ef4444", "#f97316",
    "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#1e293b",
]

DEFAULT_ACCENT = "#0e61de"
DEFAULT_SECONDARY = "#9fd6fb"

# Each app colour picker (Settings → Display) pins its *own* default to the
# far left, ahead of a divider — that is what its "Default" button restores.
# The pair is listed here only so the presets below can exclude both.
_APP_BRAND_COLORS = (DEFAULT_ACCENT, DEFAULT_SECONDARY)

# The rest of the app-wide presets: the shared family minus the near-black
# (unusable as the primary on dark surfaces) and minus both brand colours, so
# a picker never shows its own default twice.
APP_ACCENT_CHOICES = [
    c for c in ACCENT_COLOR_CHOICES[:-1] if c not in _APP_BRAND_COLORS
]
