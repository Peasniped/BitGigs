"""Template context processors."""
from django.conf import settings


def sso_status(request):
    """Expose ``sso_enabled`` (the OIDC_* env vars are configured) so the login
    page can offer the SSO button and the settings page its sign-in card, plus
    ``sso_brand`` — the provider's name/colour/icon, which every SSO page prints
    instead of naming a provider. Without the env vars this is False everywhere
    and BitGigs is password-only.

    Pure settings arithmetic, no DB, so it is cheap enough to run per request."""
    from .sso import get_brand

    return {
        "sso_enabled": settings.SSO_ENABLED,
        "sso_provider_id": settings.SSO_PROVIDER_ID,
        "sso_brand": get_brand(),
    }


def display_settings(request):
    """Expose global display preferences (from the ``UserSettings`` singleton):
    ``show_shift_type_colors`` (chips coloured by shift type),
    ``show_help_button`` (the floating help button on every page),
    ``theme`` (light/dark/auto — base.html turns it into ``data-bs-theme``)
    and the accent/secondary colours (base.html overrides ``--primary``/
    ``--primary-rgb``/``--secondary`` inline on <html>, each independently,
    whenever it differs from its default — every other colour derives from
    those tokens)."""
    from .constants import DEFAULT_ACCENT, DEFAULT_SECONDARY
    from .models import UserSettings
    from .utils import hex_to_rgb_str

    settings = UserSettings.load()
    accent = (settings.accent_color or DEFAULT_ACCENT).lower()
    secondary = (settings.secondary_color or DEFAULT_SECONDARY).lower()
    return {
        "show_shift_type_colors": settings.show_shift_type_colors,
        "show_help_button": settings.show_help_button,
        "mask_money": settings.mask_money,
        "theme": settings.theme,
        "accent_color": accent,
        "accent_color_rgb": hex_to_rgb_str(accent),
        "accent_is_default": accent == DEFAULT_ACCENT,
        "secondary_color": secondary,
        "secondary_is_default": secondary == DEFAULT_SECONDARY,
    }


def onboarding_status(request):
    """Expose ``onboarding_complete`` to every template so the base layout can
    hide the main navigation until first-time setup is finished.

    Mirrors OnboardingRequiredMiddleware's gate — ``onboarding.setup_finished``,
    which is the data check *plus* "the wizard is actually over". The middleware
    caches the result in the session once true, so the DB check only runs while
    onboarding is still in progress."""
    if getattr(request, "session", None) is not None and request.session.get("onboarding_complete"):
        return {"onboarding_complete": True, "setup_in_progress": False}

    from . import onboarding

    finished = onboarding.setup_finished(request)
    return {
        "onboarding_complete": finished,
        # Pages exempt from the funnel (the help manual, most visibly) render the
        # normal layout, which would hand a half-set-up owner the full navigation.
        # This lets base.html keep the wizard's minimal chrome on them.
        "setup_in_progress": bool(
            getattr(getattr(request, "user", None), "is_authenticated", False) and not finished
        ),
    }
