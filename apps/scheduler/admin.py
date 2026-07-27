from django.contrib import admin

from .models import ScheduledJob


@admin.register(ScheduledJob)
class ScheduledJobAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "enabled",
        "cadence_label",
        "next_run_at",
        "last_run_at",
        "last_status",
    )
    list_filter = ("enabled", "kind", "last_status")
    list_editable = ("enabled",)
    readonly_fields = (
        "last_run_at",
        "last_status",
        "last_error",
        "last_duration_ms",
    )
    fields = (
        "key",
        "enabled",
        "kind",
        "interval_seconds",
        "daily_time",
        "next_run_at",
        "last_run_at",
        "last_status",
        "last_duration_ms",
        "last_error",
    )
