"""allauth adapters.

BitGigs is single-tenant: Workplace, TaxProfile and UserSettings carry no user
FK, so *every* User sees and edits the same data. A second account is therefore
not a second tenant — it is a full compromise of the owner's data. Both adapters
below exist to make sure SSO can never create one.
"""
import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# The fresh-install bootstrap is a two-leg flow: the IdP sends us an identity, we
# park it here and ask the operator to confirm it, and only then is the owner
# created. core.views.OnboardingAccountConfirmView drives the second leg.
PENDING_SSO_SESSION_KEY = "pending_sso_bootstrap"
BOOTSTRAP_CONFIRMED_SESSION_KEY = "sso_bootstrap_confirmed"
# Linking from the settings page gets the same treatment: with a live IdP session
# the round-trip is instant and invisible, so you would bind whichever account you
# happen to be signed in as without ever seeing which one that is.
LINK_CONFIRMED_SESSION_KEY = "sso_link_confirmed"


def claim(sociallogin, name):
    """A claim exactly as the IdP sent it.

    Worth going to the source rather than reading it off `sociallogin.user`:
    allauth silently drops an email it considers invalid (so a blank claim and a
    missing one both leave user.email == ""), and it derives first/last name by
    splitting on a space — which mangles providers like authentik that send the
    whole display name as `given_name` (you get "Morten Zink Zink").
    """
    data = getattr(sociallogin.account, "extra_data", None) or {}
    if not isinstance(data, dict):
        return None
    # allauth reads userinfo first, then falls back to the id_token.
    for section in ("userinfo", "id_token"):
        claims = data.get(section)
        if isinstance(claims, dict) and name in claims:
            return claims[name]
    return None


class NoSignupAccountAdapter(DefaultAccountAdapter):
    """Closes allauth's own signup route. The owner account is created solely by
    the onboarding wizard (core.views.OnboardingAccountView)."""

    def is_open_for_signup(self, request):
        return False


class OwnerOnlySocialAccountAdapter(DefaultSocialAccountAdapter):
    """Lets the owner sign in through the IdP, and nobody else.

    An incoming identity is accepted only when its verified email matches the
    single existing account (whose username *is* its email). It is then linked to
    that account. Anything else — no account yet, a different email, no email at
    all — is refused outright; we never fall back to creating a user, because
    that user would inherit the owner's data.
    """

    def is_open_for_signup(self, request, sociallogin):
        return False

    def get_connect_redirect_url(self, request, socialaccount):
        """Back to the settings page. allauth's default lands on its own
        `socialaccount_connections` view, which this project has no template for."""
        from django.urls import reverse
        return reverse("core:settings")

    def pre_social_login(self, request, sociallogin):
        from allauth.core.exceptions import ImmediateHttpResponse
        from django.contrib import messages
        from django.shortcuts import redirect

        if sociallogin.is_existing:  # already linked to a user → nothing to do
            return

        def refuse(message):
            messages.error(request, message)
            raise ImmediateHttpResponse(redirect("/accounts/login/"))

        email = (sociallogin.user.email or "").strip()
        if not email:
            # An empty email claim and a missing one look identical from the user's
            # side but have different causes (blank user.email at the IdP vs. the
            # scope never being granted), so log which one it was.
            logger.warning(
                "SSO login refused: no usable email. Raw email claim: %r",
                claim(sociallogin, "email"),
            )
            refuse("Your identity provider did not supply an email address, so it "
                   "cannot be matched to this BitGigs account.")

        owner = User.objects.order_by("pk").first()
        if owner is None:
            # Fresh install: this identity is about to *become* the owner. Only
            # allowed straight after the account step accepted the setup key —
            # otherwise anyone who could reach the OIDC URL could claim the
            # instance just by getting there first.
            from django.urls import reverse
            from core import setup_key
            if not request.session.get(setup_key.SESSION_FLAG):
                refuse("Enter the setup key on the welcome page before claiming this "
                       "BitGigs instance with single sign-on.")

            if not request.session.pop(BOOTSTRAP_CONFIRMED_SESSION_KEY, False):
                # First leg: show the operator who the IdP says they are, and let
                # them approve it before an account exists.
                request.session[PENDING_SSO_SESSION_KEY] = sociallogin.serialize()
                raise ImmediateHttpResponse(redirect(reverse("core:onboarding-account-confirm")))

            owner = self._bootstrap_owner(email)
            request.session.pop(setup_key.SESSION_FLAG, None)
            request.session.pop(PENDING_SSO_SESSION_KEY, None)
            sociallogin.connect(request, owner)
            return

        # Username is the email here (OnboardingUserCreationForm), but compare
        # against both so a manually-created account still matches.
        candidates = {owner.email.casefold(), owner.username.casefold()}
        if email.casefold() not in candidates:
            refuse(f"{email} is not the owner of this BitGigs instance.")

        # Linking from the settings page: show which identity is about to be bound
        # before binding it. (A plain login doesn't need this — the email already
        # had to match the owner, and the user asked to log in as themselves.)
        process = (getattr(sociallogin, "state", None) or {}).get("process", "login")
        if process == "connect" and not request.session.pop(LINK_CONFIRMED_SESSION_KEY, False):
            from django.urls import reverse
            request.session[PENDING_SSO_SESSION_KEY] = sociallogin.serialize()
            raise ImmediateHttpResponse(redirect(reverse("core:sso-link-confirm")))

        sociallogin.connect(request, owner)

    def _bootstrap_owner(self, email):
        """Create the single owner/admin from an IdP identity. No password is set —
        the IdP is the only way in until one is added from the settings page."""
        from core import setup_key
        owner = User(username=email, email=email, is_staff=True, is_superuser=True)
        owner.set_unusable_password()
        owner.save()
        setup_key.clear_key()  # claimed
        return owner
