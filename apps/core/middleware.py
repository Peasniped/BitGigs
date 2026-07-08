from django.shortcuts import redirect
from django.urls import reverse


def _is_onboarding_flow_url(path):
    """True for URLs that must stay reachable during onboarding / infrastructure."""
    return path.startswith((
        "/onboarding/",
        "/admin/",
        "/static/",
        "/media/",
        "/favicon",
        "/accounts/",
    ))


class OnboardingRequiredMiddleware:
    """Funnel every page into the onboarding wizard until first-time setup is
    finished. The wizard itself (``/onboarding/``) holds each step's input in the
    session and only writes to the database on the final "Finish" step, so a tax
    profile + at least one term set existing is the completion signal."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Fresh install (no account yet): everything, including the login page,
        # leads to the create-account step — you can't log in anyway.
        if not request.user.is_authenticated:
            from django.contrib.auth.models import User
            if (not request.path.startswith(("/onboarding/account/", "/static/", "/media/", "/favicon"))
                    and not User.objects.exists()):
                return redirect(reverse("core:onboarding-account"))
            # Otherwise anonymous requests are LoginRequiredMiddleware's job;
            # onboarding checks only make sense once someone is logged in.
            return self.get_response(request)

        if _is_onboarding_flow_url(request.path):
            return self.get_response(request)

        if request.session.get("onboarding_complete"):
            return self.get_response(request)

        from core.models import TaxProfile
        from workplaces.models import ContractTermSet

        if TaxProfile.objects.exists() and ContractTermSet.objects.exists():
            request.session["onboarding_complete"] = True
            return self.get_response(request)

        # Onboarding still in progress → into the wizard.
        return redirect(reverse("core:onboarding"))
