from django.contrib import admin
from .models import WorkSession


@admin.register(WorkSession)
class WorkSessionAdmin(admin.ModelAdmin):
    list_display = [
        "workplace",
        "date",
        "start_time",
        "end_time",
        "session_type",
        "net_hours",
    ]
    list_filter = ["workplace", "session_type", "date"]
    date_hierarchy = "date"
    search_fields = ["workplace__name", "notes"]
