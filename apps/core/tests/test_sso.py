"""Optional OIDC single sign-on.

The rules that matter: with no OIDC_* env vars BitGigs is unchanged and
password-only; with them, SSO may sign in the *existing owner* and nobody else —
it must never create a second User, because the app is single-tenant and every
User sees the same data.

Branding (the button's name/colour/icon) is covered by test_sso_branding.py.
"""
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings

from core import setup_key
from core.adapters import (
    BOOTSTRAP_CONFIRMED_SESSION_KEY,
    PENDING_SSO_SESSION_KEY,
    NoSignupAccountAdapter,
    OwnerOnlySocialAccountAdapter,
)
from core.models import TaxProfile
from core.tests.test_auth import SetupKeyMixin
from workplaces.models import Workplace, WorkplaceContract, ContractTermSet

VALID_PW = "Vqz#8mtLp4"

SSO_SETTINGS = dict(
    SSO_ENABLED=True,
    SSO_PROVIDER_ID="sso",
    # Pinned so the assertions below describe an unbranded install, whatever the
    # developer happens to have in their own .env.
    OIDC_PROVIDER_BRAND="",
    OIDC_PROVIDER_NAME="",
    OIDC_PROVIDER_COLOR="",
    OIDC_PROVIDER_ICON="",
    SOCIALACCOUNT_PROVIDERS={
        "openid_connect": {
            "APPS": [{
                "provider_id": "sso",
                "name": "SSO",
                "client_id": "cid",
                "secret": "sec",
                "settings": {"server_url": "http://localhost:9000/application/o/bitgigs/"},
            }]
        }
    },
)


# Stands in for the IdP's discovery document, so no test ever hits the network.
_ISSUER = "http://localhost:9000/application/o/bitgigs/"
OPENID_CONFIG = {
    "issuer": _ISSUER,
    "authorization_endpoint": _ISSUER + "authorize/",
    "token_endpoint": _ISSUER + "token/",
    "userinfo_endpoint": _ISSUER + "userinfo/",
    "jwks_uri": _ISSUER + "jwks/",
    "end_session_endpoint": _ISSUER + "end-session/",
}


def _sociallogin(email, request=None):
    """A not-yet-linked social login carrying the given email. It needs a real
    provider attached, or serialize() (used by the confirm hand-off) blows up."""
    from allauth.socialaccount.adapter import get_adapter
    provider = get_adapter().get_provider(request, "sso") if request else None
    return SocialLogin(
        user=User(username=email, email=email),
        account=SocialAccount(provider="sso", uid=email),
        provider=provider,
    )


@override_settings(**SSO_SETTINGS)
class AdapterTest(TestCase):
    """core.adapters is the gate that keeps SSO from minting users."""

    def setUp(self):
        self.factory = RequestFactory()
        self.owner = User.objects.create_superuser("owner@example.com", email="owner@example.com",
                                                   password=VALID_PW)
        self.adapter = OwnerOnlySocialAccountAdapter()

    def _request(self):
        request = self.factory.get("/accounts/login/")
        # messages framework needs somewhere to write
        from django.contrib.messages.storage.fallback import FallbackStorage
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        return request

    def test_signup_is_closed_on_both_adapters(self):
        self.assertFalse(NoSignupAccountAdapter().is_open_for_signup(self._request()))
        self.assertFalse(self.adapter.is_open_for_signup(self._request(), _sociallogin("x@example.com")))

    def test_matching_email_is_linked_to_the_owner(self):
        login = _sociallogin("owner@example.com")
        self.adapter.pre_social_login(self._request(), login)
        self.assertEqual(login.user.pk, self.owner.pk)
        self.assertEqual(User.objects.count(), 1)

    def test_email_match_is_case_insensitive(self):
        login = _sociallogin("Owner@Example.COM")
        self.adapter.pre_social_login(self._request(), login)
        self.assertEqual(login.user.pk, self.owner.pk)

    def test_a_stranger_is_refused_and_no_user_is_created(self):
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(self._request(), _sociallogin("someone-else@example.com"))
        self.assertEqual(User.objects.count(), 1)

    def test_identity_without_an_email_is_refused(self):
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(self._request(), _sociallogin(""))
        self.assertEqual(User.objects.count(), 1)


@override_settings(**SSO_SETTINGS)
class BootstrapOwnerTest(SetupKeyMixin, TestCase):
    """Fresh install: the account step offers "create the account with SSO".
    That identity becomes the owner — but only behind the setup key, so a stranger
    can't claim the instance just by reaching the OIDC URL first."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        self.adapter = OwnerOnlySocialAccountAdapter()

    def _request(self, key_verified):
        from django.contrib.messages.storage.fallback import FallbackStorage
        request = self.factory.get("/accounts/login/")
        request.session = self.client.session
        if key_verified:
            request.session[setup_key.SESSION_FLAG] = True
        request._messages = FallbackStorage(request)
        return request

    def test_the_idp_alone_does_not_create_the_owner(self):
        # First leg: the identity is parked and the operator is sent to confirm it.
        request = self._request(key_verified=True)
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(request, _sociallogin("owner@example.com", request))
        self.assertEqual(User.objects.count(), 0)
        self.assertIn(PENDING_SSO_SESSION_KEY, request.session)

    def test_confirming_creates_the_owner(self):
        # Second leg: the operator approved it.
        request = self._request(key_verified=True)
        request.session[BOOTSTRAP_CONFIRMED_SESSION_KEY] = True
        login = _sociallogin("owner@example.com")
        self.adapter.pre_social_login(request, login)

        owner = User.objects.get()
        self.assertEqual(owner.username, "owner@example.com")
        self.assertEqual(owner.email, "owner@example.com")
        self.assertTrue(owner.is_superuser)
        # No password was chosen, so the IdP is the only way in until one is set.
        self.assertFalse(owner.has_usable_password())
        self.assertEqual(login.user.pk, owner.pk)
        self.assertFalse(setup_key.key_path().exists())  # claimed

    def test_bootstrap_is_refused_without_the_verified_setup_key(self):
        # Hitting the OIDC URL directly, skipping the account step.
        request = self._request(key_verified=False)
        request.session[BOOTSTRAP_CONFIRMED_SESSION_KEY] = True  # not enough on its own
        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(request, _sociallogin("owner@example.com"))
        self.assertEqual(User.objects.count(), 0)

    def test_a_second_identity_cannot_claim_the_instance(self):
        request = self._request(key_verified=True)
        request.session[BOOTSTRAP_CONFIRMED_SESSION_KEY] = True
        self.adapter.pre_social_login(request, _sociallogin("owner@example.com"))

        with self.assertRaises(ImmediateHttpResponse):
            self.adapter.pre_social_login(self._request(key_verified=True),
                                          _sociallogin("someone@example.com"))
        self.assertEqual(User.objects.count(), 1)

    def test_confirm_page_is_gated_by_the_key(self):
        self.assertRedirects(self.client.get("/onboarding/account/confirm/"), "/onboarding/account/")

    def test_confirm_page_without_a_pending_identity_goes_back(self):
        self.claim()
        self.assertRedirects(self.client.get("/onboarding/account/confirm/"),
                             "/onboarding/account/method/")

    def test_oidc_routes_survive_the_fresh_install_funnel(self):
        # OnboardingRequiredMiddleware redirects every anonymous request to the
        # account step while no user exists — except the OIDC round-trip.
        self.assertEqual(self.client.get("/").status_code, 302)
        resp = self.client.get("/accounts/oidc/sso/login/")
        self.assertNotEqual(resp.get("Location", ""), "/onboarding/account/")

    def test_the_key_leads_to_the_method_chooser(self):
        self.assertRedirects(self.claim(), "/onboarding/account/method/")
        resp = self.client.get("/onboarding/account/method/")
        # The SSO button posts straight to allauth — no interstitial page.
        self.assertContains(resp, "/accounts/oidc/sso/login/")
        self.assertContains(resp, "Use email &amp; password")

    def test_the_method_chooser_is_gated_by_the_key(self):
        self.assertRedirects(self.client.get("/onboarding/account/method/"), "/onboarding/account/")


class LoginPageTest(TestCase):
    def setUp(self):
        User.objects.create_superuser("owner@example.com", email="owner@example.com", password=VALID_PW)

    @override_settings(SSO_ENABLED=False)
    def test_no_sso_button_when_unconfigured(self):
        # Pinned explicitly: a developer with OIDC_* in their .env would
        # otherwise have SSO_ENABLED True here and this would pass vacuously.
        resp = self.client.get("/accounts/login/")
        self.assertNotContains(resp, "Sign in with SSO")

    @override_settings(**SSO_SETTINGS)
    def test_sso_button_appears_when_configured(self):
        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, "Sign in with SSO")
        self.assertContains(resp, "/accounts/oidc/sso/login/")

    @override_settings(**SSO_SETTINGS)
    def test_password_box_is_hidden_once_password_signin_is_off(self):
        owner = User.objects.get()
        owner.set_unusable_password()
        owner.save()

        resp = self.client.get("/accounts/login/")
        self.assertNotContains(resp, 'name="password"')  # no dead-end form
        self.assertContains(resp, "Sign in with SSO")
        self.assertContains(resp, "Can't access SSO?")
        self.assertContains(resp, "changepassword")

    @override_settings(**SSO_SETTINGS)
    def test_password_box_stays_when_password_signin_is_on(self):
        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, 'name="password"')
        self.assertContains(resp, "Forgot your password?")

    @override_settings(SSO_ENABLED=False)
    def test_password_box_is_never_hidden_without_an_idp(self):
        # No IdP: hiding the password form would lock the owner out of their app.
        owner = User.objects.get()
        owner.set_unusable_password()
        owner.save()

        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, 'name="password"')

    def test_allauth_signup_route_cannot_create_a_user(self):
        # allauth renders a "signup closed" page (200) rather than 404ing, so the
        # thing worth asserting is that posting to it mints nobody.
        self.client.post("/accounts/signup/", {
            "email": "intruder@example.com",
            "password1": VALID_PW,
            "password2": VALID_PW,
        })
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(User.objects.filter(username="intruder@example.com").exists())


class PasswordSignInToggleTest(TestCase):
    """Password sign-in may only be switched off once an IdP identity is linked,
    so the owner always has a way back in."""

    def setUp(self):
        self.owner = User.objects.create_superuser("owner@example.com", email="owner@example.com",
                                                   password=VALID_PW)
        # Onboarding must look complete or the middleware funnels us into the wizard.
        TaxProfile.objects.create(effective_from="2026-01-01", monthly_deduction=4000,
                                  tax_percent=37, am_bidrag_percent=8)
        wp = Workplace.objects.create(name="Test")
        contract = WorkplaceContract.objects.create(workplace=wp)
        ContractTermSet.objects.create(contract=contract, effective_from="2026-01-01",
                                       employment_type="salaried", monthly_salary=40000,
                                       payroll_period_start_day=1, tax_card_type="hovedkort",
                                       vacation_type="feriekonto")
        self.client.force_login(self.owner)

    def _link_sso(self):
        SocialAccount.objects.create(user=self.owner, provider="sso", uid="owner@example.com")

    def test_disable_is_refused_while_no_idp_is_linked(self):
        self.client.post("/settings/sign-in/", {"action": "disable"})
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.has_usable_password())  # still able to log in

    def test_disable_works_once_linked(self):
        self._link_sso()
        self.client.post("/settings/sign-in/", {"action": "disable"})
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.has_usable_password())

    def test_password_can_be_turned_back_on(self):
        self._link_sso()
        self.client.post("/settings/sign-in/", {"action": "disable"})
        new_pw = "Nkt#7wqRz2"
        self.client.post("/settings/sign-in/", {
            "action": "set_password", "new_password1": new_pw, "new_password2": new_pw,
        })
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.has_usable_password())
        self.assertTrue(self.owner.check_password(new_pw))

    def test_disabled_password_actually_refuses_login(self):
        self._link_sso()
        self.client.post("/settings/sign-in/", {"action": "disable"})
        self.client.logout()
        ok = self.client.login(username="owner@example.com", password=VALID_PW)
        self.assertFalse(ok)

    def test_unlinking_the_idp_needs_a_password(self):
        # The mirror of the rule above: never leave the owner with no way in.
        self._link_sso()
        self.client.post("/settings/sign-in/", {"action": "disable"})  # password now off
        self.client.post("/settings/sign-in/", {"action": "unlink_sso"})
        self.assertTrue(SocialAccount.objects.filter(user=self.owner).exists())

    def test_unlinking_the_idp_works_with_a_password(self):
        self._link_sso()
        self.client.post("/settings/sign-in/", {"action": "unlink_sso"})
        self.assertFalse(SocialAccount.objects.filter(user=self.owner).exists())
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.has_usable_password())  # still a way in

    @override_settings(**SSO_SETTINGS)
    def test_linking_shows_the_identity_before_binding_it(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from core.adapters import LINK_CONFIRMED_SESSION_KEY, PENDING_SSO_SESSION_KEY

        request = RequestFactory().get("/settings/")
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        request.user = self.owner

        login = _sociallogin("owner@example.com", request)
        login.state = {"process": "connect"}

        # A live IdP session would otherwise bind silently — the adapter parks it.
        with self.assertRaises(ImmediateHttpResponse):
            OwnerOnlySocialAccountAdapter().pre_social_login(request, login)
        self.assertFalse(SocialAccount.objects.filter(user=self.owner).exists())
        self.assertIn(PENDING_SSO_SESSION_KEY, request.session)

        # Confirmed → it links.
        request.session[LINK_CONFIRMED_SESSION_KEY] = True
        OwnerOnlySocialAccountAdapter().pre_social_login(request, login)
        self.assertEqual(login.user.pk, self.owner.pk)

    @override_settings(**SSO_SETTINGS)
    def test_a_plain_login_is_not_interrupted_by_the_confirm_page(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        request = RequestFactory().get("/accounts/login/")
        request.session = self.client.session
        request._messages = FallbackStorage(request)

        login = _sociallogin("owner@example.com", request)
        login.state = {"process": "login"}
        OwnerOnlySocialAccountAdapter().pre_social_login(request, login)
        self.assertEqual(login.user.pk, self.owner.pk)

    @override_settings(**SSO_SETTINGS)
    def test_launch_url_starts_the_sso_login(self):
        # The IdP's app tile points here: it should sign you in, not show a form.
        self.client.logout()
        resp = self.client.get("/sso/launch/")
        self.assertContains(resp, "/accounts/oidc/sso/login/")
        self.assertContains(resp, "Signing you in with SSO")

    @override_settings(**SSO_SETTINGS)
    def test_launch_offers_to_link_when_signed_in_but_unlinked(self):
        # The IdP just vouched for us, so this is the moment to offer the link.
        resp = self.client.get("/sso/launch/")
        self.assertContains(resp, 'value="connect"')
        self.assertContains(resp, "Linking your SSO account")

    @override_settings(**SSO_SETTINGS)
    def test_launch_just_opens_the_app_when_already_linked(self):
        SocialAccount.objects.create(user=self.owner, provider="sso", uid="owner@example.com")
        self.assertRedirects(self.client.get("/sso/launch/"), "/")

    @override_settings(**SSO_SETTINGS)
    def test_not_you_signs_out_of_the_idp(self):
        from unittest import mock
        from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter

        # allauth would fetch the IdP's discovery document over the network.
        with mock.patch.object(OpenIDConnectOAuth2Adapter, "openid_config",
                               new_callable=mock.PropertyMock,
                               return_value=OPENID_CONFIG):
            resp = self.client.post("/sso/idp-logout/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], OPENID_CONFIG["end_session_endpoint"])

    @override_settings(**SSO_SETTINGS)
    def test_settings_offers_a_way_to_link_again(self):
        # Unlinking must not be a one-way door.
        resp = self.client.get("/settings/?tab=signin")
        self.assertContains(resp, "/accounts/oidc/sso/login/")
        self.assertContains(resp, 'value="connect"')

    def test_connect_redirects_back_to_settings(self):
        # allauth's default post-connect page has no template here, so it must not win.
        from core.adapters import OwnerOnlySocialAccountAdapter
        self.assertEqual(
            OwnerOnlySocialAccountAdapter().get_connect_redirect_url(None, None),
            "/settings/",
        )
