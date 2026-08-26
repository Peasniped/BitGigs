from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _seed_atp_rates(sender, **kwargs):
    """Seed ATP rates from data/atp_rates.csv after migrations (create-if-missing)."""
    from tax.rate_loaders import load_atp_rates
    load_atp_rates()


class TaxConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tax"
    verbose_name = "Danish Tax"

    def ready(self):
        post_migrate.connect(_seed_atp_rates, sender=self)
