from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from . import services


class HelpKeyword(models.Model):
    """Reusable search tag shared across articles (chip input in the editor)."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @classmethod
    def get_or_create_by_name(cls, name):
        name = name.strip()
        obj, _ = cls.objects.get_or_create(
            slug=slugify(name), defaults={"name": name}
        )
        return obj


class HelpPage(models.Model):
    """A page-context the popup can attach articles to. ``key`` is normally a URL
    view-name (``request.resolver_match.view_name``); the editor lists these as a
    checklist, so page assignment is never a free-typed string. Rows are synced
    from ``services.HELP_PAGE_CONTEXTS``."""

    key = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=120)

    class Meta:
        ordering = ["label"]

    def __str__(self):
        return f"{self.label} ({self.key})"


class HelpArticleQuerySet(models.QuerySet):
    def live(self):
        """Not in the Trash."""
        return self.filter(archived_at__isnull=True)

    def archived(self):
        """In the Trash (soft-deleted)."""
        return self.filter(archived_at__isnull=False)

    def published(self):
        return self.live().filter(is_published=True)

    def visible_to(self, user):
        """Published (and non-archived) articles the user may see. BitGigs is
        single-owner (owner is staff), so the owner sees everything; ``audience``
        is the hook for future multi-user first-party apps that reuse this app."""
        qs = self.published()
        if user is not None and (user.is_staff or user.is_superuser):
            return qs
        return qs.filter(audience=HelpArticle.Audience.EVERYONE)


class HelpArticle(models.Model):
    class Audience(models.TextChoices):
        EVERYONE = "everyone", "Everyone"
        STAFF = "staff", "Staff only"
        ADMIN = "admin", "Admins only"

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
        help_text="Optional parent article — sub-articles nest beneath it.",
    )
    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=160)
    summary = models.CharField(
        max_length=280,
        blank=True,
        help_text="One-line description shown in search results and the manual list.",
    )
    body_md = models.TextField(help_text="Article body in Markdown.")
    # Cached render of body_md, refreshed on every save (never edited directly).
    body_html = models.TextField(editable=False, blank=True)
    audience = models.CharField(
        max_length=10, choices=Audience.choices, default=Audience.EVERYONE
    )
    keywords = models.ManyToManyField(HelpKeyword, blank=True, related_name="articles")
    pages = models.ManyToManyField(HelpPage, blank=True, related_name="articles")
    is_published = models.BooleanField(default=True)
    order = models.IntegerField(default=100, help_text="Lower numbers sort first.")
    # Soft delete: set → the article is in the Trash (hidden everywhere but
    # restorable). Cleared on restore; a real delete only happens on purge.
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = HelpArticleQuerySet.as_manager()

    class Meta:
        ordering = ["order", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:80]
        self.body_html = services.render_markdown(self.body_md)
        # update_or_create (help_import's upsert) passes update_fields limited
        # to its defaults, which would silently drop the derived fields from
        # the UPDATE — the cached render must always land with the markdown.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"slug", "body_html"}
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("help:manual-article", args=[self.slug])

    def archive(self):
        """Soft-delete: move to the Trash (no re-render, no cascade)."""
        type(self).objects.filter(pk=self.pk).update(archived_at=timezone.now())

    def restore(self):
        type(self).objects.filter(pk=self.pk).update(archived_at=None)

    def ancestors(self):
        """Parent chain from the root down to (but excluding) this article.
        Guarded against loops so a corrupt parent link can't spin forever."""
        chain = []
        seen = {self.pk}
        node = self.parent
        while node is not None and node.pk not in seen:
            chain.append(node)
            seen.add(node.pk)
            node = node.parent
        chain.reverse()
        return chain

    def descendant_ids(self):
        """All descendant pks (for excluding them from the parent picker)."""
        ids, frontier = set(), [self.pk]
        while frontier:
            children = HelpArticle.objects.filter(parent_id__in=frontier).values_list(
                "id", flat=True
            )
            new = [c for c in children if c not in ids]
            ids.update(new)
            frontier = new
        return ids


class HelpArticleRevision(models.Model):
    """Snapshot written on every editor save so a bad edit (or "deleted all the
    text and saved") can be reverted at runtime. Pruned to the most recent
    ``PRUNE_KEEP`` per article by ``services.prune_revisions``."""

    PRUNE_KEEP = 20

    article = models.ForeignKey(
        HelpArticle, on_delete=models.CASCADE, related_name="revisions"
    )
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=280, blank=True)
    body_md = models.TextField()
    editor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-saved_at"]

    def __str__(self):
        return f"{self.title} @ {self.saved_at:%Y-%m-%d %H:%M}"
