import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from help import services
from help.models import HelpArticle, HelpArticleRevision, HelpKeyword, HelpPage


class HelpTestMixin:
    """Authenticated + onboarding-complete client (site-wide login gate)."""

    is_staff = True

    def setUp(self):
        services.sync_page_contexts()
        self.user = User.objects.create_user(
            "tester", password="pw", is_staff=self.is_staff
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["onboarding_complete"] = True
        session.save()

    def make_article(self, slug="alpha", **kwargs):
        defaults = dict(
            slug=slug,
            title=kwargs.pop("title", "Alpha"),
            body_md=kwargs.pop("body_md", "# Hello\n\nBody text."),
        )
        defaults.update(kwargs)
        return HelpArticle.objects.create(**defaults)


# ── Models / services ─────────────────────────────────────────────────────────


class HelpModelTests(HelpTestMixin, TestCase):
    def test_save_renders_and_caches_html(self):
        article = self.make_article(body_md="# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |")
        self.assertIn("<h1", article.body_html)
        self.assertIn("<table", article.body_html)  # tables extension active

    def test_visible_to_filters_by_audience_and_publish(self):
        self.make_article(slug="pub", audience=HelpArticle.Audience.EVERYONE)
        self.make_article(slug="draft", is_published=False)
        self.make_article(slug="staff-only", audience=HelpArticle.Audience.STAFF)

        staff = self.user
        visible_staff = set(
            HelpArticle.objects.visible_to(staff).values_list("slug", flat=True)
        )
        self.assertIn("pub", visible_staff)
        self.assertIn("staff-only", visible_staff)  # staff sees all published
        self.assertNotIn("draft", visible_staff)  # unpublished hidden from everyone

        member = User.objects.create_user("member", password="pw", is_staff=False)
        visible_member = set(
            HelpArticle.objects.visible_to(member).values_list("slug", flat=True)
        )
        self.assertIn("pub", visible_member)
        self.assertNotIn("staff-only", visible_member)

    def test_revision_pruning_keeps_recent(self):
        article = self.make_article()
        for i in range(HelpArticleRevision.PRUNE_KEEP + 5):
            HelpArticleRevision.objects.create(
                article=article, title=f"v{i}", body_md="x"
            )
        services.prune_revisions(article)
        self.assertEqual(article.revisions.count(), HelpArticleRevision.PRUNE_KEEP)


class HelpServiceTests(HelpTestMixin, TestCase):
    def test_render_markdown_no_external_calls_and_html(self):
        html = services.render_markdown("**bold** and `code`")
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<code>code</code>", html)

    def test_articles_for_page(self):
        # shifts:daily-overview isn't used by any seeded baseline article.
        article = self.make_article(slug="daily-help")
        article.pages.add(HelpPage.objects.get(key="shifts:daily-overview"))
        found = list(services.articles_for_page("shifts:daily-overview", self.user))
        self.assertEqual(found, [article])

    def test_import_links_parent_and_builds_tree(self):
        parent = self.make_article(slug="parent-a", title="Parent A")
        child = self.make_article(slug="child-a", title="Child A")
        child.parent = parent
        child.save()
        self.assertEqual(list(parent.children.all()), [child])
        self.assertEqual(child.ancestors(), [parent])

        tree = services.build_tree([parent, child])
        root = next(n for n in tree if n["article"].slug == "parent-a")
        self.assertEqual([c["article"].slug for c in root["children"]], ["child-a"])

    def test_parent_picker_excludes_self_and_descendants(self):
        from help.forms import HelpArticleForm

        parent = self.make_article(slug="p", title="P")
        child = self.make_article(slug="c", title="C", parent=parent)
        form = HelpArticleForm(instance=parent)
        choices = set(form.fields["parent"].queryset.values_list("slug", flat=True))
        self.assertNotIn("p", choices)  # can't be its own parent
        self.assertNotIn("c", choices)  # can't parent under a descendant

    def test_export_import_round_trip(self):
        article = self.make_article(slug="round", title="Round Trip")
        article.keywords.set([HelpKeyword.get_or_create_by_name("alpha")])
        article.pages.set([HelpPage.objects.get(key="analytics:overview")])

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            services.export_articles(tmp_dir)
            self.assertTrue((tmp_dir / "round.md").exists())

            article.delete()
            self.assertFalse(HelpArticle.objects.filter(slug="round").exists())

            results = services.import_articles(tmp_dir)

        self.assertEqual(results["created"], 1)
        restored = HelpArticle.objects.get(slug="round")
        self.assertEqual(restored.title, "Round Trip")
        self.assertEqual(
            list(restored.keywords.values_list("name", flat=True)), ["alpha"]
        )
        self.assertEqual(
            list(restored.pages.values_list("key", flat=True)), ["analytics:overview"]
        )


# ── Views ─────────────────────────────────────────────────────────────────────


class HelpReaderViewTests(HelpTestMixin, TestCase):
    def test_manual_page(self):
        self.make_article(slug="alpha", title="Alpha")
        resp = self.client.get(reverse("help:manual"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Alpha")

    def test_article_fragment(self):
        self.make_article(slug="alpha", body_md="Unique fragment marker")
        resp = self.client.get(reverse("help:fragment", args=["alpha"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Unique fragment marker")

    def test_context_lookup_by_page(self):
        article = self.make_article(slug="dash", title="Dashboard help")
        article.pages.add(HelpPage.objects.get(key="core:dashboard"))
        resp = self.client.get(reverse("help:context"), {"page": "core:dashboard"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Dashboard help")

    def test_search_index_json(self):
        self.make_article(slug="alpha", title="Alpha", summary="the summary")
        resp = self.client.get(reverse("help:search-index"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        slugs = [a["slug"] for a in data["articles"]]
        self.assertIn("alpha", slugs)


class HelpEditorViewTests(HelpTestMixin, TestCase):
    def test_create_article_writes_revision(self):
        resp = self.client.post(
            reverse("help:create"),
            {
                "title": "Made in editor",
                "slug": "",
                "summary": "s",
                "body_md": "# Body",
                "audience": "everyone",
                "order": "50",
                "is_published": "on",
                "keywords_text": "one, two",
                "pages": [str(HelpPage.objects.get(key="core:dashboard").pk)],
            },
        )
        self.assertEqual(resp.status_code, 302)
        article = HelpArticle.objects.get(slug="made-in-editor")
        self.assertEqual(article.revisions.count(), 1)
        self.assertEqual(
            set(article.keywords.values_list("name", flat=True)), {"one", "two"}
        )
        self.assertEqual(list(article.pages.values_list("key", flat=True)), ["core:dashboard"])

    def test_revert_restores_body(self):
        article = self.make_article(slug="rev", body_md="original")
        HelpArticleRevision.objects.create(
            article=article, title=article.title, body_md="original"
        )
        article.body_md = "changed"
        article.save()
        old_rev = article.revisions.get(body_md="original")

        resp = self.client.post(reverse("help:revert", args=["rev", old_rev.pk]))
        self.assertEqual(resp.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.body_md, "original")

    def test_preview_renders_markdown(self):
        resp = self.client.post(reverse("help:preview"), {"body_md": "**hi**"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "<strong>hi</strong>")


class HelpEditorGatingTests(HelpTestMixin, TestCase):
    is_staff = False  # a logged-in but non-staff user

    def test_editor_forbidden_for_non_staff(self):
        for name in ["help:manage", "help:create"]:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 403, name)

    def test_reader_allowed_for_non_staff(self):
        HelpArticle.objects.create(slug="alpha", title="Alpha", body_md="hi")
        resp = self.client.get(reverse("help:manual"))
        self.assertEqual(resp.status_code, 200)
