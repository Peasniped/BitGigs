"""The per-workplace accent scope.

``.wp-accent-scope`` re-points --primary and friends at the workplace's own
colour, so every rule that already follows the app accent follows the workplace
instead. Two things have to hold or the scope silently drains the colour out of
everything inside it — see the CSS block in assets/static/css/style.css:

* the class and both custom properties are emitted together;
* nothing is emitted at all without an accent colour, because a
  ``--wp-accent: var(--primary)`` fallback is a custom-property *cycle*.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from workplaces.models import Workplace
from workplaces.templatetags.wp_accent import wp_accent_scope


class AccentRgbTests(TestCase):
    def test_hex_becomes_the_rgb_triplet_the_css_token_wants(self):
        wp = Workplace(name="Acme", accent_color="#0e61de")
        self.assertEqual(wp.accent_rgb, "14,97,222")

    def test_no_accent_means_no_rgb(self):
        self.assertEqual(Workplace(name="Acme").accent_rgb, "")

    def test_an_unparseable_accent_reads_as_unset(self):
        """Better a plain app-accent page than a scope with a broken token."""
        self.assertEqual(Workplace(name="Acme", accent_color="#zzz").accent_rgb, "")


class AccentScopeTagTests(TestCase):
    def test_emits_the_class_and_both_custom_properties(self):
        wp = Workplace(name="Acme", accent_color="#0e61de")
        out = wp_accent_scope(wp, "row justify-content-center")
        self.assertIn('class="row justify-content-center wp-accent-scope"', out)
        self.assertIn("--wp-accent:#0e61de", out)
        self.assertIn("--wp-accent-rgb:14,97,222", out)

    def test_no_accent_opens_no_scope(self):
        out = wp_accent_scope(Workplace(name="Acme"), "row")
        self.assertEqual(out, 'class="row"')

    def test_rgb_and_accent_are_never_emitted_apart(self):
        """--primary-rgb cannot be derived from a hex in CSS: without the
        triplet, .bg-primary and the focus ring resolve to nothing."""
        out = wp_accent_scope(Workplace(name="Acme", accent_color="#zzzzzz"), "")
        self.assertNotIn("wp-accent-scope", out)


class AccentScopeOnPagesTests(TestCase):
    """Every workplace-owned page opens the scope; the rest of the app doesn't."""

    def setUp(self):
        self.user = User.objects.create_user("owner", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()
        self.wp = Workplace.objects.create(name="Acme", slug="acme",
                                           accent_color="#0e61de")
        self.plain = Workplace.objects.create(name="Beta", slug="beta")

    def test_workplace_pages_carry_the_scope(self):
        for name in ("workplaces:workplace-detail", "workplaces:workplace-update",
                     "workplaces:contract-create"):
            with self.subTest(name):
                response = self.client.get(reverse(name, args=[self.wp.slug]))
                self.assertContains(response, "wp-accent-scope")
                self.assertContains(response, "--wp-accent:#0e61de")

    def test_a_workplace_without_an_accent_keeps_the_app_accent(self):
        response = self.client.get(
            reverse("workplaces:workplace-detail", args=[self.plain.slug]))
        self.assertNotContains(response, "wp-accent-scope")
        self.assertNotContains(response, "--wp-accent")
