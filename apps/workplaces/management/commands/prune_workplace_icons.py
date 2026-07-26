"""Remove orphaned custom workplace-icon files from media/workplace_icons/.

Deleting a Workplace leaves its uploaded icon on disk, so this sweeps any file
no Workplace.custom_icon references. Runs automatically at most once a day (see
workplaces.services.maybe_prune_orphan_icons); this command is the manual entry
point for on-demand runs or an external scheduler.
"""
from django.core.management.base import BaseCommand

from workplaces.services import prune_orphan_icons


class Command(BaseCommand):
    help = "Delete orphaned custom workplace-icon files no workplace references."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the orphaned files without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        removed = prune_orphan_icons(dry_run=dry_run)
        if not removed:
            self.stdout.write(self.style.SUCCESS("No orphaned workplace icons found."))
            return
        verb = "Would remove" if dry_run else "Removed"
        self.stdout.write(f"{verb} {len(removed)} orphaned workplace icon(s):")
        for name in sorted(removed):
            self.stdout.write(f"  {name}")
