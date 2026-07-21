"""Settings → About tab: deployment facts gathered by core.about."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core import about


class LoggedInTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()


class AboutModuleTest(TestCase):
    def test_version_comes_from_package(self):
        self.assertEqual(about.app_version(), __import__("bitgigs").__version__)

    def test_env_vars_win_over_git(self):
        with mock.patch.dict(
            "os.environ",
            {"BITGIGS_GIT_COMMIT": "abc1234", "BITGIGS_BUILD_DATE": "2026-07-21"},
        ):
            self.assertEqual(about.build_commit(), "abc1234")
            self.assertEqual(about.build_date(), "2026-07-21")

    def test_deployment_declared_docker(self):
        with mock.patch.dict("os.environ", {"BITGIGS_DEPLOYMENT": "docker"}):
            label, icon = about.deployment()
        self.assertEqual(label, "Docker")
        self.assertTrue(icon)

    def test_database_label(self):
        # Dev/test runs on SQLite.
        label, _ = about.database()
        self.assertIn(label, ("SQLite", "PostgreSQL"))

    def test_slogan_from_list(self):
        self.assertIn(about.slogan(), about.SLOGANS)

    def test_slogan_falls_back_when_empty(self):
        with mock.patch.object(about, "SLOGANS", []):
            self.assertTrue(about.slogan())

    def test_git_helper_never_raises(self):
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertIsNone(about._git("rev-parse"))


class AboutTabViewTest(LoggedInTestCase):
    def test_tab_renders_with_facts(self):
        response = self.client.get(reverse("core:settings"), {"tab": "about"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "about")
        self.assertContains(response, "Version")
        self.assertContains(response, response.context["about_version"])
        self.assertContains(response, response.context["about_python"])

    def test_other_tabs_do_not_gather_about_facts(self):
        response = self.client.get(reverse("core:settings"), {"tab": "display"})
        self.assertNotIn("about_version", response.context)
