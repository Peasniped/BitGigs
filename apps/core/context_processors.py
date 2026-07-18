"""Template context processors."""
from django.conf import settings


def sso_status(request):
    """Expose ``sso_enabled`` (the AUTHENTIK_* env vars are configured) so the
    login page can offer the SSO button and the settings page its sign-in card.
    Without the env vars this is False everywhere and BitGigs is password-only."""
    return {
        "sso_enabled": settings.SSO_ENABLED,
        "sso_provider_id": settings.SSO_PROVIDER_ID,
    }


def display_settings(request):
    """Expose global display preferences (from the ``UserSettings`` singleton):
    ``show_shift_type_colors`` (chips coloured by shift type) and
    ``show_help_button`` (the floating help button on every page)."""
    from .models import UserSettings

    settings = UserSettings.load()
    return {
        "show_shift_type_colors": settings.show_shift_type_colors,
        "show_help_button": settings.show_help_button,
    }


def onboarding_status(request):
    """Expose ``onboarding_complete`` to every template so the base layout can
    hide the main navigation until first-time setup is finished.

    Mirrors OnboardingRequiredMiddleware's completion signal (a tax profile and
    at least one term set exist). The middleware caches the result in the session
    once true, so the DB check only runs while onboarding is still in progress."""
    if getattr(request, "session", None) is not None and request.session.get("onboarding_complete"):
        return {"onboarding_complete": True}

    from .models import TaxProfile
    from workplaces.models import ContractTermSet

    complete = TaxProfile.objects.exists() and ContractTermSet.objects.exists()
    return {"onboarding_complete": complete}
