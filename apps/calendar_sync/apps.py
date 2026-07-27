from django.apps import AppConfig


class CalendarSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "calendar_sync"

    def ready(self):
        # Keep emitted invites current across every shift edit path (Direction 2).
        from . import signals

        signals.connect()
        # Register scheduler task handlers (e.g. the async test-invite send).
        from . import tasks  # noqa: F401
