from django.contrib import admin

from .models import ScheduledJob, ScheduledTask, SchedulerHeartbeat


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


@admin.register(ScheduledTask)
class ScheduledTaskAdmin(admin.ModelAdmin):
    list_display = ("task", "status", "run_at", "attempts", "created_at", "finished_at")
    list_filter = ("status", "task")
    readonly_fields = (
        "task", "payload", "status", "attempts", "max_attempts",
        "created_at", "started_at", "finished_at", "last_error", "result",
    )


@admin.register(SchedulerHeartbeat)
class SchedulerHeartbeatAdmin(admin.ModelAdmin):
    list_display = ("beat_at",)
    readonly_fields = ("beat_at",)
