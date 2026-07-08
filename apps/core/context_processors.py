"""Template context processors."""


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
