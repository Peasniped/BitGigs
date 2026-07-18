from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST

from . import services
from .forms import HelpArticleForm
from .models import HelpArticle, HelpArticleRevision


# ─── Reader (any logged-in user; the whole site is behind the login gate) ─────


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
        return render(
            request,
            "help/manual.html",
            {
                "articles": articles,
                "tree": services.build_tree(articles),
                "current": current,
                "breadcrumbs": current.ancestors() if current else [],
                "can_edit": request.user.is_staff,
            },
        )


class HelpArticleFragmentView(View):
    """Rendered single-article fragment for the popup (AJAX)."""

    def get(self, request, slug):
        article = get_object_or_404(
            HelpArticle.objects.visible_to(request.user), slug=slug
        )
        return render(request, "help/_article.html", {"article": article})


class HelpContextView(View):
    """The article(s) mapped to a page (by URL view-name) as a fragment."""

    def get(self, request):
        page = request.GET.get("page", "").strip()
        articles = list(services.articles_for_page(page, request.user)) if page else []
        return render(
            request, "help/_context.html", {"articles": articles, "page": page}
        )


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
        articles = HelpArticle.objects.all().prefetch_related("keywords", "pages")
        return render(request, "help/manage.html", {"articles": articles})


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
    def post(self, request, slug):
        article = get_object_or_404(HelpArticle, slug=slug)
        title = article.title
        article.delete()
        services.invalidate_caches()
        messages.success(request, f"Deleted “{title}”.")
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
