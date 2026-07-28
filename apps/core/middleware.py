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
        "/sso/",
        # API requests answer with JSON, never with a redirect into the wizard —
        # the /api/v1/ endpoints do their own key auth, and the key-management
        # POSTs are harmless mid-onboarding.
        "/api/",
        # Help is read-only and shown on the logged-in onboarding steps (F1 /
        # the help button), so its popup endpoints and the manual must not
        # bounce back into the wizard.
        "/help/",
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
        # leads to the create-account step — there is nobody to log in as. The
        # exceptions are /accounts/oidc/ and /sso/, because the account step offers
        # "create the account with single sign-on", and that round-trip (including the
        # "not you?" re-authentication) runs while still anonymous.
        if not request.user.is_authenticated:
            from django.contrib.auth.models import User
            if (not request.path.startswith(("/onboarding/account/", "/accounts/oidc/", "/sso/",
                                             "/static/", "/media/", "/favicon", "/api/v1/",
                                             # public-audience help on the account pages
                                             "/help/"))
                    and not User.objects.exists()):
                return redirect(reverse("core:onboarding-account"))
            # Otherwise anonymous requests are LoginRequiredMiddleware's job;
            # onboarding checks only make sense once someone is logged in.
            return self.get_response(request)

        if _is_onboarding_flow_url(request.path):
            return self.get_response(request)

        if request.session.get("onboarding_complete"):
            return self.get_response(request)

        from core import onboarding

        if onboarding.setup_finished(request):
            request.session["onboarding_complete"] = True
            return self.get_response(request)

        # Onboarding still in progress → into the wizard.
        return redirect(reverse("core:onboarding"))


class FeatureEnabledMiddleware:
    """Refuse the URLs of a feature switched off on Settings → Features.

    Hiding the nav entry is not the same as turning something off: a bookmark, a
    link in a help article or the browser's own history would still walk straight
    into a page the owner has disabled. This is what makes the switch mean it.

    Implemented as ``process_view`` rather than ``__call__`` because it matches on
    the resolved **view name** (``payroll:vacation-overview``) — three features
    share the ``payroll:`` namespace, so a path or namespace test would switch off
    all three at once. Anonymous requests are left to the login gate, and the
    admin is deliberately never gated: it is the escape hatch.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        from django.contrib import messages

        from core import features

        if not request.user.is_authenticated:
            return None
        match = request.resolver_match
        if match is None or request.path.startswith("/admin/"):
            return None

        blocked = features.blocked_feature(match.view_name)
        if blocked is None:
            return None
        # Say *why* and where to undo it — a bare redirect to the dashboard reads
        # as a broken link rather than as a setting doing its job.
        messages.info(
            request,
            f"“{blocked.label}” is switched off. You can turn it back on under "
            "Settings → Features.",
        )
        return redirect(reverse("core:dashboard"))
