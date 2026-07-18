from django.core.management.base import BaseCommand

from help import services


class Command(BaseCommand):
    help = "Import help articles from apps/help/articles/*.md into the DB (upsert by slug)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            dest="directory",
            default=None,
            help="Source directory (defaults to apps/help/articles/).",
        )

    def handle(self, *args, **options):
        services.sync_page_contexts()
        results = services.import_articles(options["directory"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported help articles: {results['created']} created, "
                f"{results['updated']} updated."
            )
        )
