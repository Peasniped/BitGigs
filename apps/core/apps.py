import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


def _seed_atp_rates(sender, **kwargs):
    """Seed ATP rates from data/atp_rates.csv after migrations (create-if-missing)."""
    from core.rate_loaders import load_atp_rates
    load_atp_rates()


def _announce_log_level():
    """Say which level is in force, *at* that level so it is always visible.

    Logging it at a fixed level would defeat the purpose — at INFO it would
    vanish the moment someone set WARNING, i.e. exactly when they are trying to
    confirm the setting took. Emitting at the configured level means the line
    survives whatever the level is, and its absence is itself the signal that
    logging isn't configured the way you think.
    """
    from django.conf import settings

    level_name = getattr(settings, "LOG_LEVEL", "INFO")
    sinks = "console"
    if getattr(settings, "LOG_FILE", ""):
        sinks += f" + file {settings.LOG_FILE}"
    logger.log(
        getattr(logging, level_name, logging.INFO),
        "Using Loglevel: %s (%s)",
        level_name,
        sinks,
    )


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core Settings"

    def ready(self):
        post_migrate.connect(_seed_atp_rates, sender=self)
        # Django configures logging before it populates the app registry, so a
        # handler is in place by the time ready() runs.
        _announce_log_level()
