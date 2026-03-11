from django.contrib import admin
from .models import Workplace


@admin.register(Workplace)
class WorkplaceAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "employment_type",
        "tax_card_type",
        "is_active",
        "payroll_period_start_day",
        "pension_employee_percent",
        "pension_employer_percent",
        "fritvalgskonto_percent",
    ]
    list_filter = ["employment_type", "tax_card_type", "is_active"]
    search_fields = ["name"]
