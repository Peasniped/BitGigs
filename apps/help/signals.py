"""post_migrate hook: keep the page-context registry in sync and seed the
shipped baseline articles on a fresh install (empty table only, so it never
clobbers live edits)."""


def seed_help(sender, **kwargs):
    from . import services
    from .models import HelpArticle

    services.sync_page_contexts()
    if not HelpArticle.objects.exists():
        services.import_articles()
