"""Orphaned-icon cleanup: prune_orphan_icons + the once-a-day opportunistic guard."""
import io
import os
import shutil
import tempfile
import time
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from workplaces.models import Workplace
from workplaces import services


class IconPruneMixin:
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.icon_dir = Path(self.tmp) / services.ICON_SUBDIR
        self.icon_dir.mkdir(parents=True)
        self.marker = Path(self.tmp) / "last_icon_prune"
        self._override = override_settings(
            MEDIA_ROOT=self.tmp, ICON_PRUNE_MARKER_PATH=str(self.marker),
            ICON_PRUNE_AUTO=True,
        )
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _stray_file(self, name):
        p = self.icon_dir / name
        p.write_bytes(b"x")
        return p

    def _workplace_with_icon(self, slug, name):
        wp = Workplace.objects.create(name=slug, slug=slug)
        wp.custom_icon.save(name, ContentFile(b"icon"), save=True)
        return wp


class PruneOrphanIconsTests(IconPruneMixin, TestCase):
    def test_removes_orphan_keeps_referenced(self):
        kept = self._workplace_with_icon("acme", "acme_icon.png")
        orphan = self._stray_file("ghost_icon.png")

        removed = services.prune_orphan_icons()

        self.assertEqual(removed, ["ghost_icon.png"])
        self.assertFalse(orphan.exists())
        self.assertTrue(Path(self.tmp, kept.custom_icon.name).exists())

    def test_dry_run_reports_but_keeps(self):
        orphan = self._stray_file("ghost_icon.png")

        removed = services.prune_orphan_icons(dry_run=True)

        self.assertEqual(removed, ["ghost_icon.png"])
        self.assertTrue(orphan.exists())

    def test_missing_directory_is_safe(self):
        shutil.rmtree(self.icon_dir)
        self.assertEqual(services.prune_orphan_icons(), [])

    def test_command_dry_run(self):
        # Capture the command's own output — left on stdout it printed into the
        # middle of the suite's results, reading like a stray production run.
        out = io.StringIO()
        self._stray_file("ghost_icon.png")
        call_command("prune_workplace_icons", "--dry-run", stdout=out)
        self.assertTrue((self.icon_dir / "ghost_icon.png").exists())
        self.assertIn("ghost_icon.png", out.getvalue())
        call_command("prune_workplace_icons", stdout=out)
        self.assertFalse((self.icon_dir / "ghost_icon.png").exists())


class MaybePruneTests(IconPruneMixin, TestCase):
    def test_runs_when_marker_absent(self):
        self._stray_file("ghost_icon.png")
        services.maybe_prune_orphan_icons()
        self.assertFalse((self.icon_dir / "ghost_icon.png").exists())
        self.assertTrue(self.marker.exists())

    def test_skips_when_recently_run(self):
        self.marker.write_text("now")  # fresh marker → not due
        self._stray_file("ghost_icon.png")
        services.maybe_prune_orphan_icons()
        self.assertTrue((self.icon_dir / "ghost_icon.png").exists())

    def test_runs_when_marker_is_stale(self):
        self.marker.write_text("old")
        old = time.time() - services.ICON_PRUNE_INTERVAL.total_seconds() - 60
        os.utime(self.marker, (old, old))
        self._stray_file("ghost_icon.png")
        services.maybe_prune_orphan_icons()
        self.assertFalse((self.icon_dir / "ghost_icon.png").exists())

    def test_disabled_auto_is_a_noop(self):
        with override_settings(ICON_PRUNE_AUTO=False):
            self._stray_file("ghost_icon.png")
            services.maybe_prune_orphan_icons()
        self.assertTrue((self.icon_dir / "ghost_icon.png").exists())
        self.assertFalse(self.marker.exists())
