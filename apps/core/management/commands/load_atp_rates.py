from django.core.management.base import BaseCommand

from core.rate_loaders import load_atp_rates


class Command(BaseCommand):
    help = "Load ATP rates from data/atp_rates.csv into the database (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Replace brackets for ATP configurations that already exist.",
        )

    def handle(self, *args, **options):
        counts = load_atp_rates(force=options["force"])
        self.stdout.write(self.style.SUCCESS(
            "ATP rates loaded: "
            f"{counts['configs_created']} created, "
            f"{counts['configs_updated']} updated, "
            f"{counts['configs_skipped']} skipped, "
            f"{counts['brackets_created']} brackets."
        ))
