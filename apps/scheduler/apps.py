from django.apps import AppConfig


class SchedulerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scheduler"

    def ready(self):
        # Reconcile the DB-backed schedule table against the job registry after
        # migrate (new jobs get a row, defunct ones are removed).
        from django.db.models.signals import post_migrate
        from . import signals

        post_migrate.connect(signals.seed_scheduled_jobs, sender=self)
