"""Help-system services: Markdown rendering, the page-context registry, the
client-side search index, revision pruning, and repo import/export of articles.

Everything here runs on-server. Nothing in this module (or the help app at large)
makes an external/network call — see the hard constraint at the top of CLAUDE.md.

Model-using helpers import models lazily so ``models.py`` can import
``render_markdown`` at module load without a circular import.
"""
import re
from pathlib import Path

import markdown as _markdown
from django.core.cache import cache
from django.urls import reverse

ARTICLES_DIR = Path(__file__).resolve().parent / "articles"

# Author-friendly Markdown: tables + fenced code, single newline → <br> (nl2br),
# plus pymdown-extensions for task lists (- [ ] …), strikethrough (~~…~~) and
# smarter bold/italic (betterem handles ***bold italic*** and mixed markers).
# sane_lists is deliberately NOT used — it refuses lists that start right after a
# paragraph, which surprised authors.
_MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "nl2br",
    "pymdownx.betterem",
    "pymdownx.tasklist",
    "pymdownx.tilde",
]
_MD_EXTENSION_CONFIGS = {
    "pymdownx.tilde": {"subscript": False},  # ~~strike~~ only, no ~sub~
}

# Page-contexts the popup can attach articles to. Keys are URL view-names
# (request.resolver_match.view_name); labels are what the editor checklist shows.
# Synced to HelpPage rows by sync_page_contexts().
HELP_PAGE_CONTEXTS = [
    ("core:dashboard", "Dashboard"),
    ("workplaces:workplace-list", "Workplaces"),
    ("workplaces:workplace-detail", "Workplace detail"),
    ("calendar_view:planning", "Planning calendar"),
    ("calendar_view:month", "Month calendar"),
    ("calendar_view:approve-shifts", "Approve shifts"),
    ("shifts:daily-overview", "Daily overview"),
    ("shifts:monthly-overview", "Monthly overview"),
    ("payroll:period-list", "Payroll periods"),
    ("payroll:period-detail", "Payslip detail"),
    ("payroll:commuting-list", "Commuting"),
    ("payroll:vacation-overview", "Vacation"),
    ("analytics:overview", "Analytics"),
    ("analytics:rate-history", "Rate history"),
    ("core:taxprofile-list", "Tax profiles"),
    ("core:settings", "Settings"),
    ("data_io:main", "Import / Export"),
    # Onboarding steps. The account pages run before login exists, so they only
    # surface ``public``-audience articles (see HelpArticle.objects.visible_to).
    ("core:onboarding-account", "Onboarding: claim instance"),
    ("core:onboarding-account-method", "Onboarding: sign-in method"),
    ("core:onboarding-account-email", "Onboarding: create account"),
    ("core:onboarding-tax", "Onboarding: tax profile"),
    ("core:onboarding-workplace", "Onboarding: workplace"),
    ("core:onboarding-terms", "Onboarding: pay terms"),
]

_SEARCH_KEYS = [
    "help:search-index:staff",
    "help:search-index:public",
    "help:search-index:anon",
]
_ENABLED_KEY = "help:enabled"


def render_markdown(text):
    """Render trusted (staff-authored) Markdown to an HTML string.

    The editor is admin-gated, so article bodies are trusted the same way the app
    trusts its own templates; callers render the result with ``|safe``. If
    non-admin authoring is ever enabled, sanitize here with an allowlist parser
    (cf. ``core.utils.sanitize_svg``)."""
    return _markdown.markdown(
        text or "",
        extensions=_MD_EXTENSIONS,
        extension_configs=_MD_EXTENSION_CONFIGS,
        output_format="html5",
    )


def _plain_text(html):
    """Strip tags/whitespace from rendered HTML for the search-index body field."""
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def sync_page_contexts():
    """Ensure a HelpPage row exists for each configured context. Idempotent."""
    from .models import HelpPage

    for key, label in HELP_PAGE_CONTEXTS:
        HelpPage.objects.update_or_create(key=key, defaults={"label": label})


def articles_for_page(view_name, user):
    """Published, visible articles mapped to the page with this URL view-name."""
    from .models import HelpArticle

    return (
        HelpArticle.objects.visible_to(user)
        .filter(pages__key=view_name)
        .distinct()
    )


def build_tree(articles):
    """Turn a flat, ordered list of articles into a nested tree for the manual
    sidebar. A child whose parent isn't in the list (e.g. an unpublished parent)
    is lifted to the top level so it never disappears."""
    ids = {a.pk for a in articles}
    nodes = {a.pk: {"article": a, "children": []} for a in articles}
    roots = []
    for a in articles:
        node = nodes[a.pk]
        if a.parent_id and a.parent_id in ids:
            nodes[a.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def flatten_tree(nodes):
    """Depth-first list of articles in reading order (matches the sidebar tree),
    used to compute prev/next navigation on the manual."""
    ordered = []
    for node in nodes:
        ordered.append(node["article"])
        ordered.extend(flatten_tree(node["children"]))
    return ordered


def build_search_index(user):
    """Return (and cache) the list of article records the client searches."""
    from .models import HelpArticle

    if user is None or not user.is_authenticated:
        variant = "anon"
    elif user.is_staff or user.is_superuser:
        variant = "staff"
    else:
        variant = "public"
    cache_key = f"help:search-index:{variant}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    items = []
    for art in HelpArticle.objects.visible_to(user).prefetch_related("keywords"):
        items.append(
            {
                "slug": art.slug,
                "title": art.title,
                "summary": art.summary,
                "keywords": [k.name for k in art.keywords.all()],
                "body": _plain_text(art.body_html)[:1500],
                "url": reverse("help:manual-article", args=[art.slug]),
            }
        )
    cache.set(cache_key, items, 300)
    return items


def invalidate_caches():
    """Drop cached search indexes + the help-enabled flag after any article change."""
    cache.delete_many(_SEARCH_KEYS + [_ENABLED_KEY])


def prune_revisions(article, keep=None):
    """Keep only the most recent ``keep`` revisions of ``article``."""
    from .models import HelpArticleRevision

    keep = keep or HelpArticleRevision.PRUNE_KEEP
    stale_ids = list(article.revisions.values_list("id", flat=True)[keep:])
    if stale_ids:
        HelpArticleRevision.objects.filter(id__in=stale_ids).delete()


# ─── Repo import / export ────────────────────────────────────────────────────
# Articles ship as Markdown files with a small frontmatter block, so they are
# git-versioned and seed fresh installs. Frontmatter is hand-parsed (key: value,
# lists as [a, b]) to avoid a YAML dependency.


def _parse_frontmatter(text):
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    block, body = text[4:end], text[end + 5:]
    meta = {}
    for line in block.split("\n"):
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [v.strip() for v in inner.split(",") if v.strip()] if inner else []
        else:
            meta[key] = value
    return meta, body


def _as_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def article_to_markdown(article):
    """Serialize a HelpArticle to frontmatter + Markdown body."""
    keywords = ", ".join(k.name for k in article.keywords.all())
    pages = ", ".join(p.key for p in article.pages.all())
    front = [
        "---",
        f"title: {article.title}",
        f"slug: {article.slug}",
        f"summary: {article.summary}",
        f"parent: {article.parent.slug if article.parent else ''}",
        f"audience: {article.audience}",
        f"order: {article.order}",
        f"published: {'true' if article.is_published else 'false'}",
        f"keywords: [{keywords}]",
        f"pages: [{pages}]",
        "---",
        "",
    ]
    return "\n".join(front) + article.body_md.replace("\r\n", "\n").rstrip() + "\n"


def export_articles(directory=None):
    """Write every article to ``<directory>/<slug>.md``. Returns the count."""
    from .models import HelpArticle

    directory = Path(directory) if directory else ARTICLES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    count = 0
    for art in HelpArticle.objects.live().prefetch_related("keywords", "pages"):
        (directory / f"{art.slug}.md").write_text(
            article_to_markdown(art), encoding="utf-8"
        )
        count += 1
    return count


def import_articles(directory=None):
    """Upsert articles (by slug) from ``<directory>/*.md``. Returns counts.

    Unknown page keys are ignored (only contexts that exist as HelpPage rows are
    attached), so run ``sync_page_contexts()`` first."""
    from .models import HelpArticle, HelpKeyword, HelpPage

    directory = Path(directory) if directory else ARTICLES_DIR
    results = {"created": 0, "updated": 0}
    if not directory.is_dir():
        return results

    parent_by_slug = {}  # child slug -> parent slug, resolved in a second pass
    for path in sorted(directory.glob("*.md")):
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        slug = meta.get("slug") or path.stem
        try:
            order = int(meta.get("order", 100) or 100)
        except (TypeError, ValueError):
            order = 100
        article, created = HelpArticle.objects.update_or_create(
            slug=slug,
            defaults={
                "title": meta.get("title", slug),
                "summary": meta.get("summary", ""),
                "body_md": body.strip() + "\n",
                "audience": meta.get("audience", HelpArticle.Audience.EVERYONE),
                "order": order,
                "is_published": _as_bool(meta.get("published", True)),
                # Re-importing a shipped article also restores it from the Trash.
                "archived_at": None,
            },
        )
        results["created" if created else "updated"] += 1
        article.keywords.set(
            [HelpKeyword.get_or_create_by_name(n) for n in meta.get("keywords", [])]
        )
        article.pages.set(list(HelpPage.objects.filter(key__in=meta.get("pages", []))))
        if meta.get("parent"):
            parent_by_slug[slug] = meta["parent"]

    # Second pass: link parents now that every article exists.
    for child_slug, parent_slug in parent_by_slug.items():
        parent = HelpArticle.objects.filter(slug=parent_slug).first()
        if parent and parent.slug != child_slug:
            HelpArticle.objects.filter(slug=child_slug).update(parent=parent)

    invalidate_caches()
    return results
