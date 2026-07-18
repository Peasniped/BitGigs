from django.core.management.base import BaseCommand

from help import services


class Command(BaseCommand):
    help = "Export help articles from the DB to apps/help/articles/*.md (commit these to ship them)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            dest="directory",
            default=None,
            help="Target directory (defaults to apps/help/articles/).",
        )

    def handle(self, *args, **options):
        count = services.export_articles(options["directory"])
        target = options["directory"] or services.ARTICLES_DIR
        self.stdout.write(
            self.style.SUCCESS(f"Exported {count} article(s) to {target}.")
        )
