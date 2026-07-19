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
    "#6366f1", "#8b5cf6", "#ec4899", "#ef4444", "#f97316",
    "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#1e293b",
]

# App-wide accent presets (Settings → Display): the same family minus the
# near-black, which is unusable as the primary on dark surfaces.
APP_ACCENT_CHOICES = ACCENT_COLOR_CHOICES[:-1]

DEFAULT_ACCENT = "#6366f1"
