"""Expose ``help_enabled`` (any published article exists) so base.html can show
or hide the help icon + F1 popup. Cached; invalidated on any article change via
``services.invalidate_caches``."""
from django.core.cache import cache


def help_status(request):
    enabled = cache.get("help:enabled")
    if enabled is None:
        from .models import HelpArticle

        enabled = HelpArticle.objects.filter(is_published=True).exists()
        cache.set("help:enabled", enabled, 300)
    return {"help_enabled": enabled}
