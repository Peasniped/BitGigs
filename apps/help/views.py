from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST

from . import services
from .forms import HelpArticleForm
from .models import HelpArticle, HelpArticleRevision, HelpKeyword, HelpPage


# ─── Reader views ─────────────────────────────────────────────────────────────
# Marked login_not_required so the pre-login onboarding/account pages can show
# help; ``visible_to`` limits anonymous visitors to ``public``-audience
# articles, so everything else stays behind the login gate as before.


@method_decorator(login_not_required, name="dispatch")
class HelpManualView(View):
    """Full-page manual: sidebar of articles + the selected article body."""

    def get(self, request, slug=None):
        articles = list(
            HelpArticle.objects.visible_to(request.user).select_related("parent")
        )
        current = None
        if slug:
            current = get_object_or_404(
                HelpArticle.objects.visible_to(request.user), slug=slug
            )
        elif articles:
            current = articles[0]
        tree = services.build_tree(articles)
        prev_article = next_article = None
        if current:
            ordered = services.flatten_tree(tree)
            slugs = [a.slug for a in ordered]
            if current.slug in slugs:
                i = slugs.index(current.slug)
                prev_article = ordered[i - 1] if i > 0 else None
                next_article = ordered[i + 1] if i < len(ordered) - 1 else None
        return render(
            request,
            "help/manual.html",
            {
                "articles": articles,
                "tree": tree,
                "current": current,
                "breadcrumbs": current.ancestors() if current else [],
                "prev_article": prev_article,
                "next_article": next_article,
                "can_edit": request.user.is_staff,
            },
        )


@method_decorator(login_not_required, name="dispatch")
class HelpArticleFragmentView(View):
    """Rendered single-article fragment for the popup (AJAX)."""

    def get(self, request, slug):
        article = get_object_or_404(
            HelpArticle.objects.visible_to(request.user), slug=slug
        )
        return render(request, "help/_article.html", {"article": article})


@method_decorator(login_not_required, name="dispatch")
class HelpContextView(View):
    """The article(s) mapped to a page (by URL view-name) as a fragment."""

    APPROVE_SLUG = "approving-shifts"

    def get(self, request):
        page = request.GET.get("page", "").strip()
        articles = list(services.articles_for_page(page, request.user)) if page else []
        # Surface the approve-shifts help on any page that currently has shifts to
        # approve (dashboard, workplace detail) — pushed to the top when the
        # approval modal is open. The client sends these flags from the DOM.
        if request.GET.get("approve"):
            approve = (
                HelpArticle.objects.visible_to(request.user)
                .filter(slug=self.APPROVE_SLUG)
                .first()
            )
            if approve and approve not in articles:
                if request.GET.get("approve_open"):
                    articles.insert(0, approve)
                else:
                    articles.append(approve)
        return render(
            request, "help/_context.html", {"articles": articles, "page": page}
        )


@method_decorator(login_not_required, name="dispatch")
class HelpSearchIndexView(View):
    """The JSON index the client searches as-you-type."""

    def get(self, request):
        return JsonResponse({"articles": services.build_search_index(request.user)})


# ─── Editor (staff only) ──────────────────────────────────────────────────────


class StaffRequiredMixin(UserPassesTestMixin):
    # Logged-in non-staff get a 403 rather than a bounce to the login page.
    raise_exception = True

    def test_func(self):
        return self.request.user.is_staff


def _snapshot(article, editor):
    """Record a revision then prune old ones."""
    HelpArticleRevision.objects.create(
        article=article,
        title=article.title,
        summary=article.summary,
        body_md=article.body_md,
        editor=editor,
    )
    services.prune_revisions(article)


class HelpArticleManageView(StaffRequiredMixin, View):
    def get(self, request):
        articles = HelpArticle.objects.live().prefetch_related("keywords", "pages")
        trashed = HelpArticle.objects.archived().order_by("-archived_at")
        # Distinct pages/keywords in use, for the column filter dropdowns.
        used_pages = (
            HelpPage.objects.filter(articles__archived_at__isnull=True)
            .distinct()
            .order_by("label")
        )
        used_keywords = (
            HelpKeyword.objects.filter(articles__archived_at__isnull=True)
            .distinct()
            .order_by("name")
        )
        return render(
            request,
            "help/manage.html",
            {
                "articles": articles,
                "trashed": trashed,
                "used_pages": used_pages,
                "used_keywords": used_keywords,
            },
        )


class HelpArticleEditView(StaffRequiredMixin, View):
    def _article(self, slug):
        return get_object_or_404(HelpArticle, slug=slug) if slug else None

    def get(self, request, slug=None):
        article = self._article(slug)
        form = HelpArticleForm(instance=article)
        return render(request, "help/edit.html", {"form": form, "article": article})

    def post(self, request, slug=None):
        article = self._article(slug)
        form = HelpArticleForm(request.POST, instance=article)
        if form.is_valid():
            article = form.save()
            _snapshot(article, request.user)
            services.invalidate_caches()
            messages.success(request, f"Saved “{article.title}”.")
            return redirect("help:manage")
        return render(request, "help/edit.html", {"form": form, "article": article})


@method_decorator(require_POST, name="dispatch")
class HelpArticleDeleteView(StaffRequiredMixin, View):
    """Soft delete: move the article to the Trash (recoverable)."""

    def post(self, request, slug):
        article = get_object_or_404(HelpArticle.objects.live(), slug=slug)
        article.archive()
        services.invalidate_caches()
        messages.success(request, f"Moved “{article.title}” to Trash.")
        return redirect("help:manage")


@method_decorator(require_POST, name="dispatch")
class HelpArticleRestoreView(StaffRequiredMixin, View):
    def post(self, request, slug):
        article = get_object_or_404(HelpArticle.objects.archived(), slug=slug)
        article.restore()
        services.invalidate_caches()
        messages.success(request, f"Restored “{article.title}”.")
        return redirect("help:manage")


@method_decorator(require_POST, name="dispatch")
class HelpArticlePurgeView(StaffRequiredMixin, View):
    """Permanently delete a single trashed article (cascades its revisions)."""

    def post(self, request, slug):
        article = get_object_or_404(HelpArticle.objects.archived(), slug=slug)
        title = article.title
        article.delete()
        services.invalidate_caches()
        messages.success(request, f"Permanently deleted “{title}”.")
        return redirect("help:manage")


@method_decorator(require_POST, name="dispatch")
class HelpTrashEmptyView(StaffRequiredMixin, View):
    def post(self, request):
        trashed = HelpArticle.objects.archived()
        count = trashed.count()
        trashed.delete()
        services.invalidate_caches()
        messages.success(
            request, f"Emptied Trash ({count} article{'' if count == 1 else 's'})."
        )
        return redirect("help:manage")


class HelpArticleRevisionsView(StaffRequiredMixin, View):
    def get(self, request, slug):
        article = get_object_or_404(HelpArticle, slug=slug)
        return render(
            request,
            "help/revisions.html",
            {"article": article, "revisions": article.revisions.all()},
        )


@method_decorator(require_POST, name="dispatch")
class HelpArticleRevertView(StaffRequiredMixin, View):
    def post(self, request, slug, pk):
        article = get_object_or_404(HelpArticle, slug=slug)
        revision = get_object_or_404(HelpArticleRevision, pk=pk, article=article)
        article.title = revision.title
        article.summary = revision.summary
        article.body_md = revision.body_md
        article.save()
        _snapshot(article, request.user)
        services.invalidate_caches()
        messages.success(request, "Reverted to the selected version.")
        return redirect("help:edit", slug=article.slug)


@method_decorator(require_POST, name="dispatch")
class HelpPreviewView(StaffRequiredMixin, View):
    """Server-side render of the editor's Markdown, so the live preview matches
    the final output exactly."""

    def post(self, request):
        return HttpResponse(services.render_markdown(request.POST.get("body_md", "")))
