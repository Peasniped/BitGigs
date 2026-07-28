"""Settings → Features: the switches, the nav, and the URL guard.

The load-bearing case is that Payroll, Vacation and Commuting all live in the
``payroll:`` namespace — a namespace- or path-based guard would switch off all
three together, which is why the registry matches on view-name prefixes.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core import features
from core.models import UserSettings


class FeatureRegistryTests(TestCase):
    def test_every_feature_maps_to_a_real_settings_field(self):
        settings = UserSettings.load()
        for feature in features.FEATURES:
            self.assertTrue(
                hasattr(settings, feature.setting),
                f"{feature.key} names a field UserSettings doesn't have",
            )

    def test_everything_is_on_by_default(self):
        # An upgrade must never hide a page the owner was already using.
        self.assertEqual(
            set(features.enabled_map().values()), {True}
        )

    def test_view_names_resolve_to_the_right_feature(self):
        cases = {
            "payroll:period-list": "payroll",
            "payroll:payslip-add-line": "payroll",
            "payroll:vacation-overview": "vacation",
            "payroll:commuting-list": "commuting",
            "analytics:rate-history": "analytics",
        }
        for view_name, key in cases.items():
            self.assertEqual(features.feature_for_view(view_name).key, key, view_name)

    def test_an_unowned_view_belongs_to_no_feature(self):
        self.assertIsNone(features.feature_for_view("workplaces:workplace-list"))
        self.assertIsNone(features.feature_for_view(""))


class FeatureGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def _switch(self, **flags):
        settings = UserSettings.load()
        for key, value in flags.items():
            setattr(settings, f"feature_{key}", value)
        settings.save()

    def test_an_enabled_feature_answers_normally(self):
        self.assertEqual(self.client.get("/payroll/periods/").status_code, 200)
        self.assertEqual(self.client.get("/analytics/").status_code, 200)

    def test_a_disabled_feature_redirects_to_the_dashboard(self):
        self._switch(analytics=False)
        resp = self.client.get("/analytics/")
        self.assertRedirects(resp, reverse("core:dashboard"))

    def test_disabling_one_payroll_feature_leaves_its_siblings_alone(self):
        """All three share the ``payroll:`` namespace — the whole reason the
        guard matches view-name prefixes rather than namespaces."""
        self._switch(payroll=False)
        self.assertEqual(self.client.get("/payroll/periods/").status_code, 302)
        self.assertEqual(self.client.get("/payroll/vacation/").status_code, 200)
        self.assertEqual(self.client.get("/payroll/commuting/").status_code, 200)

    def test_switching_back_on_restores_the_page(self):
        self._switch(commuting=False)
        self.assertEqual(self.client.get("/payroll/commuting/").status_code, 302)
        self._switch(commuting=True)
        self.assertEqual(self.client.get("/payroll/commuting/").status_code, 200)

    def test_the_nav_drops_a_disabled_entry(self):
        resp = self.client.get(reverse("core:dashboard"))
        self.assertContains(resp, reverse("payroll:vacation-overview"))
        self._switch(vacation=False)
        resp = self.client.get(reverse("core:dashboard"))
        self.assertNotContains(resp, reverse("payroll:vacation-overview"))

    def test_the_admin_is_never_gated(self):
        # The escape hatch: an owner who switched something off must still be
        # able to reach the data through the admin.
        self._switch(payroll=False)
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.assertEqual(self.client.get("/admin/").status_code, 200)


class FeatureSettingsTabTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def test_saving_the_tab_writes_the_switches(self):
        resp = self.client.post("/settings/", {
            "tab": "features",
            "feature_payroll": "on",
            # vacation/commuting/analytics omitted = unchecked
            "projection_method": "ema",
            "projection_trailing_months": "6",
        })
        self.assertEqual(resp.status_code, 302)
        settings = UserSettings.load()
        self.assertTrue(settings.feature_payroll)
        self.assertFalse(settings.feature_vacation)
        self.assertFalse(settings.feature_analytics)

    def test_saving_with_analytics_off_keeps_its_settings(self):
        """The settings panel is hidden, not removed, so its fields still post —
        turning the feature back on must find it configured as it was."""
        settings = UserSettings.load()
        settings.projection_trailing_months = 9
        settings.save()

        self.client.post("/settings/", {
            "tab": "features",
            "projection_method": "ema",
            "projection_trailing_months": "9",
        })
        settings.refresh_from_db()
        self.assertFalse(settings.feature_analytics)
        self.assertEqual(settings.projection_trailing_months, 9)

    def test_the_features_tab_does_not_touch_display_settings(self):
        settings = UserSettings.load()
        settings.week_start = 6
        settings.save()
        self.client.post("/settings/", {
            "tab": "features",
            "feature_payroll": "on",
            "projection_method": "ema",
            "projection_trailing_months": "6",
        })
        settings.refresh_from_db()
        self.assertEqual(settings.week_start, 6)
