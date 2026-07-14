"""Print (or rotate) the setup key needed to claim a fresh BitGigs install."""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core import setup_key


class Command(BaseCommand):
    help = "Show the setup key required to create the owner account on a fresh install."

    def add_arguments(self, parser):
        parser.add_argument(
            "--regenerate",
            action="store_true",
            help="Throw the current key away and issue a new one.",
        )

    def handle(self, *args, **options):
        if User.objects.exists():
            self.stdout.write(self.style.WARNING(
                "This instance already has an owner — the setup key is no longer used."
            ))
            return

        key = setup_key.regenerate_key() if options["regenerate"] else setup_key.get_or_create_key()
        self.stdout.write("Setup key: " + self.style.SUCCESS(key))
        self.stdout.write(f"Saved to:  {setup_key.key_path()}")
