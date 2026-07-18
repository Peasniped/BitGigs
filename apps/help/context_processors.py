"""Expose ``help_enabled`` (any published article exists) so base.html can show
or hide the help icon + F1 popup. Cached; invalidated on any article change via
``services.invalidate_caches``."""
from django.core.cache import cache

# Pages that render a calendar of shifts. The shift-type legend used to sit on
# each calendar; it now lives in the help panel and shows automatically on these
# pages (no click needed). Keep in sync with where the calendar grid is shown.
CALENDAR_VIEW_NAMES = {
    "core:dashboard",
    "workplaces:workplace-detail",
    "calendar_view:planning",
    "calendar_view:month",
    "calendar_view:payroll-period",
}


def help_status(request):
    enabled = cache.get("help:enabled")
    if enabled is None:
        from .models import HelpArticle

        enabled = HelpArticle.objects.filter(is_published=True).exists()
        cache.set("help:enabled", enabled, 300)
    match = getattr(request, "resolver_match", None)
    view_name = match.view_name if match else ""
    return {
        "help_enabled": enabled,
        "page_has_calendar": view_name in CALENDAR_VIEW_NAMES,
    }
