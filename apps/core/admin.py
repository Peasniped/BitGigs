from django.contrib import admin
from .models import UserSettings


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ["week_start", "updated_at"]

    def has_add_permission(self, request):
        # Only allow one instance
        return not UserSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
