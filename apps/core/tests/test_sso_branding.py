"""SSO button branding.

BitGigs works with any OpenID Connect provider, so the button must never claim to
be one the operator isn't running. These pin the three states: unconfigured
(neutral), a bundled preset, and the operator's own name/colour/icon.
"""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.sso import DEFAULT_COLOR, DEFAULT_NAME, get_brand

VALID_PW = "Vqz#8mtLp4"

# The credential half of an enabled install; the branding half is what varies.
SSO_ON = dict(
    SSO_ENABLED=True,
    SSO_PROVIDER_ID="sso",
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

UNBRANDED = dict(
    OIDC_PROVIDER_BRAND="", OIDC_PROVIDER_NAME="",
    OIDC_PROVIDER_COLOR="", OIDC_PROVIDER_ICON="",
)


@override_settings(**UNBRANDED)
class BrandResolutionTest(TestCase):
    def test_unconfigured_is_neutral(self):
        brand = get_brand()
        self.assertEqual(brand.name, DEFAULT_NAME)
        self.assertEqual(brand.color, DEFAULT_COLOR)
        self.assertEqual(brand.icon, "")       # falls back to the glyph
        self.assertFalse(brand.tint_icon)

    @override_settings(OIDC_PROVIDER_BRAND="authentik")
    def test_preset_supplies_all_three(self):
        brand = get_brand()
        self.assertEqual(brand.name, "Authentik")
        self.assertEqual(brand.color, "#fd4b2d")
        self.assertEqual(brand.icon, "graphics/authentik_icon.svg")
        self.assertTrue(brand.tint_icon)  # the bundled icon is brand-coloured

    @override_settings(OIDC_PROVIDER_BRAND="AuThEnTiK")
    def test_preset_lookup_ignores_case(self):
        self.assertEqual(get_brand().name, "Authentik")

    @override_settings(OIDC_PROVIDER_BRAND="keycloak")
    def test_unknown_preset_falls_back_instead_of_failing(self):
        # A typo or an unbundled provider must not 500 the login page.
        self.assertEqual(get_brand().name, DEFAULT_NAME)

    @override_settings(OIDC_PROVIDER_BRAND="authentik", OIDC_PROVIDER_NAME="Company SSO")
    def test_explicit_field_overrides_its_preset(self):
        brand = get_brand()
        self.assertEqual(brand.name, "Company SSO")
        self.assertEqual(brand.color, "#fd4b2d")  # the rest of the preset survives

    @override_settings(OIDC_PROVIDER_BRAND="authentik", OIDC_PROVIDER_ICON="graphics/mine.svg")
    def test_a_custom_icon_is_never_recoloured(self):
        # Tinting is only safe for artwork we ship. Someone's own logo may already
        # be white, or multicoloured, and tinting would destroy it.
        brand = get_brand()
        self.assertEqual(brand.icon, "graphics/mine.svg")
        self.assertFalse(brand.tint_icon)

    def test_colour_accepts_shorthand_hex(self):
        with self.settings(OIDC_PROVIDER_COLOR="#0a0"):
            self.assertEqual(get_brand().color, "#00aa00")

    def test_unparseable_colour_falls_back_to_the_default(self):
        # It comes from an env var, so a typo must not emit broken CSS.
        for junk in ("rebeccapurple", "#12345", "", "#xyzxyz"):
            with self.settings(OIDC_PROVIDER_COLOR=junk):
                self.assertEqual(get_brand().color, DEFAULT_COLOR, junk)


@override_settings(**UNBRANDED)
class ButtonContrastTest(TestCase):
    """A brand colour is arbitrary, so the label colour is derived, not assumed."""

    def test_dark_button_gets_light_text(self):
        with self.settings(OIDC_PROVIDER_COLOR="#1a1a2e"):
            self.assertEqual(get_brand().text_color, "#ffffff")

    def test_light_button_gets_dark_text(self):
        # The bug this prevents: white-on-near-white, i.e. an invisible button.
        with self.settings(OIDC_PROVIDER_COLOR="#ffd700"):
            self.assertEqual(get_brand().text_color, "#1e293b")

    @override_settings(OIDC_PROVIDER_BRAND="authentik")
    def test_a_preset_keeps_its_vendors_label_colour(self):
        # On #fd4b2d dark text scores the better ratio, but authentik brands with
        # white — a preset reproduces branding rather than second-guessing it.
        self.assertEqual(get_brand().text_color, "#ffffff")

    @override_settings(OIDC_PROVIDER_BRAND="authentik", OIDC_PROVIDER_COLOR="#ffd700")
    def test_overriding_a_presets_colour_re_derives_the_label(self):
        # The preset's white would be invisible on the operator's new colour.
        self.assertEqual(get_brand().text_color, "#1e293b")

    def test_icon_tint_follows_the_label_colour(self):
        # Otherwise a dark-text button gets a white mark floating on it.
        with self.settings(OIDC_PROVIDER_COLOR="#1a1a2e"):
            self.assertEqual(get_brand().tint_invert, "1")
        with self.settings(OIDC_PROVIDER_COLOR="#ffd700"):
            self.assertEqual(get_brand().tint_invert, "0")


@override_settings(**{**SSO_ON, **UNBRANDED})
class LoginPageBrandingTest(TestCase):
    def setUp(self):
        User.objects.create_superuser("owner@example.com", email="owner@example.com", password=VALID_PW)

    def test_unbranded_login_page_names_no_provider(self):
        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, "Sign in with SSO")
        self.assertNotContains(resp, "Authentik")

    @override_settings(OIDC_PROVIDER_NAME="Keycloak")
    def test_the_configured_name_reaches_the_button(self):
        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, "Sign in with Keycloak")
        self.assertNotContains(resp, "Authentik")

    @override_settings(OIDC_PROVIDER_COLOR="#4d4d4d")
    def test_the_configured_colour_reaches_the_button(self):
        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, "--sso-bg: #4d4d4d")

    @override_settings(OIDC_PROVIDER_BRAND="authentik")
    def test_the_preset_still_gets_full_authentik_branding(self):
        # The whole point of keeping a preset: one env var, branded button.
        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, "Sign in with Authentik")
        self.assertContains(resp, "authentik_icon.svg")
        self.assertContains(resp, "--sso-bg: #fd4b2d")
