"""Branding for the optional single sign-on button.

Credentials come from OIDC_SERVER_URL/_CLIENT_ID/_CLIENT_SECRET. Everything the
user *sees* — the provider's name, the button colour, its icon — is cosmetic, and
is resolved here from four optional OIDC_PROVIDER_* env vars.

BitGigs works with any OpenID Connect provider, so nothing here may assume
Authentik. It ships Authentik's icon and brand colour as a one-word preset
(``OIDC_PROVIDER_BRAND=authentik``) because that is the icon we bundle; every
other provider gets a neutral button unless the operator points
``OIDC_PROVIDER_ICON`` at artwork of their own.
"""
from dataclasses import dataclass

from django.conf import settings

from .constants import DEFAULT_ACCENT

# Presets only exist for providers whose icon we actually ship. Adding one means
# vendoring someone else's trademark, so the bar is deliberately high.
PRESETS = {
    "authentik": {
        "name": "Authentik",
        # authentik's own colour, taken from the icon they ship.
        "color": "#fd4b2d",
        # ...and their own label colour. On that orange, dark text technically
        # scores the better contrast ratio, but a preset exists to reproduce a
        # vendor's branding, not to second-guess it. Derivation is for colours we
        # know nothing about.
        "text": "#ffffff",
        "icon": "graphics/authentik_icon.svg",
        # That icon is brand-coloured, so it needs tinting to read on the button.
        "tint_icon": True,
    },
}

DEFAULT_NAME = "SSO"
DEFAULT_COLOR = DEFAULT_ACCENT  # the app's default --primary (core.constants)
GLYPH = "bi-shield-lock"        # stands in when there is no icon file

_LIGHT_TEXT = "#ffffff"
_DARK_TEXT = "#1e293b"  # --text in style.css


@dataclass(frozen=True)
class SSOBrand:
    """Everything _sso_button.html needs to draw the button."""

    name: str
    color: str
    text_color: str
    ring: str
    icon: str        # static path; "" when the glyph should be used instead
    glyph: str       # Bootstrap Icons class, drawn when there is no icon file
    tint_icon: bool
    tint_invert: str  # "1" tints the icon white, "0" black — follows text_color


def _parse_hex(value):
    """Return (r, g, b) for #rgb / #rrggbb, or None if it isn't a colour.

    The value comes from an env var, so a typo must degrade to the default
    rather than emit broken CSS."""
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6:
        return None
    try:
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _relative_luminance(rgb):
    """WCAG relative luminance."""
    def channel(value):
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _readable_text(rgb):
    """Pick white or dark text — whichever contrasts better with the button.

    A pale brand colour would otherwise render white-on-white; comparing both
    contrast ratios avoids picking a magic luminance threshold."""
    background = _relative_luminance(rgb)
    on_light = (background + 0.05) / (_relative_luminance((30, 41, 59)) + 0.05)
    on_white = 1.05 / (background + 0.05)
    return _DARK_TEXT if on_light > on_white else _LIGHT_TEXT


def get_brand():
    """Resolve the SSO button's appearance from settings.

    Precedence per field: the explicit OIDC_PROVIDER_* var, then the preset it
    belongs to, then BitGigs' neutral default."""
    preset = PRESETS.get((settings.OIDC_PROVIDER_BRAND or "").strip().lower(), {})

    custom_icon = (settings.OIDC_PROVIDER_ICON or "").strip()
    name = (settings.OIDC_PROVIDER_NAME or "").strip() or preset.get("name") or DEFAULT_NAME
    icon = custom_icon or preset.get("icon", "")
    # Only the bundled preset icon may be recoloured. An operator's own logo is
    # finished artwork — it may already be white, or multicoloured, and tinting
    # it would destroy it.
    tint_icon = bool(preset.get("tint_icon")) and not custom_icon

    custom_rgb = _parse_hex(settings.OIDC_PROVIDER_COLOR)
    rgb = custom_rgb or _parse_hex(preset.get("color")) or _parse_hex(DEFAULT_COLOR)

    # A preset may state its vendor's own label colour; derive only when the
    # colour is one we were handed and know nothing about.
    text_color = _readable_text(rgb)
    if not custom_rgb and preset.get("text"):
        text_color = preset["text"]

    return SSOBrand(
        name=name,
        color="#%02x%02x%02x" % rgb,
        text_color=text_color,
        ring="rgba(%d, %d, %d, .35)" % rgb,
        icon=icon,
        glyph=GLYPH,
        tint_icon=tint_icon,
        # The tinted icon must match the label, or a dark-text button gets a white
        # mark floating on it.
        tint_invert="1" if text_color == _LIGHT_TEXT else "0",
    )
