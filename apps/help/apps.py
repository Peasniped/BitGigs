from django.apps import AppConfig


class HelpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "help"

    def ready(self):
        # Sync page-context rows and seed baseline articles after migrate.
        from django.db.models.signals import post_migrate
        from . import signals

        post_migrate.connect(signals.seed_help, sender=self)
