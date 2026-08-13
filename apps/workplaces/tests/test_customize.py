"""Customize appearance: the avatar is one choice, not two that can disagree.

A workplace can carry a stored logo *and* a Bootstrap icon class, and every
template that draws an avatar prefers the logo. So picking an icon while a logo
was uploaded used to change nothing at all on screen — the reported bug, whose
only workaround was pressing "remove logo" first.
"""
import shutil
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse

from core.testing import LoggedInTestCase
from workplaces.models import Workplace


class CustomizeIconTests(LoggedInTestCase):
    username = "owner"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._override = override_settings(MEDIA_ROOT=self.tmp)
        self._override.enable()
        self.addCleanup(self._override.disable)

        super().setUp()

        self.wp = Workplace.objects.create(name="Acme", slug="acme")
        self.wp.custom_icon.save("acme_icon.png", ContentFile(b"logo"), save=True)
        self.url = reverse("workplaces:workplace-customize", args=[self.wp.slug])

    def post(self, **fields):
        data = {"icon": "", "color": "", "accent_color": ""}
        data.update(fields)
        return self.client.post(data=data, path=self.url)

    def test_choosing_an_icon_drops_the_stored_logo(self):
        stored = Path(self.wp.custom_icon.path)
        self.assertTrue(stored.exists())

        response = self.post(icon="bi-briefcase", remove_custom_icon="1")

        self.assertEqual(response.status_code, 200)
        self.wp.refresh_from_db()
        self.assertEqual(self.wp.icon, "bi-briefcase")
        self.assertFalse(self.wp.custom_icon)
        self.assertFalse(stored.exists())

    def test_an_icon_alone_is_enough_to_drop_the_logo(self):
        """Belt and braces: the two are mutually exclusive server-side too, so a
        client that forgets the remove flag can't recreate the bug."""
        self.post(icon="bi-briefcase")

        self.wp.refresh_from_db()
        self.assertEqual(self.wp.icon, "bi-briefcase")
        self.assertFalse(self.wp.custom_icon)

    def test_choosing_no_icon_at_all_drops_the_logo_too(self):
        """"None (initials)" is a choice as much as an icon is."""
        self.post(icon="", remove_custom_icon="1")

        self.wp.refresh_from_db()
        self.assertEqual(self.wp.icon, "")
        self.assertFalse(self.wp.custom_icon)

    def test_saving_colours_alone_keeps_the_logo(self):
        """The keep-the-logo path: no icon named, no removal asked for."""
        self.post(accent_color="#ff0000")

        self.wp.refresh_from_db()
        self.assertTrue(self.wp.custom_icon)
        self.assertEqual(self.wp.accent_color, "#ff0000")
