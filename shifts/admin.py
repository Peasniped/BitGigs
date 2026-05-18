from django.contrib import admin
from .models import Shift, PlannedShift


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = [
        "workplace",
        "date",
        "start_time",
        "end_time",
        "shift_type",
        "net_hours",
    ]
    list_filter = ["workplace", "shift_type", "date"]


@admin.register(PlannedShift)
class PlannedShiftAdmin(admin.ModelAdmin):
    list_display = [
        "workplace",
        "date",
        "start_time",
        "end_time",
        "shift_type",
        "status",
        "net_hours",
    ]
    list_filter = ["workplace", "status", "shift_type", "date"]
    date_hierarchy = "date"
    search_fields = ["workplace__name", "notes"]
