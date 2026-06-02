from django.contrib import admin
from .models import Workplace, WorkplaceContract, ContractTermSet


@admin.register(Workplace)
class WorkplaceAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "slug"]
    list_filter = ["is_active"]
    search_fields = ["name"]


@admin.register(WorkplaceContract)
class WorkplaceContractAdmin(admin.ModelAdmin):
    list_display = ["workplace", "name", "start_date", "end_date"]
    list_filter = ["workplace"]
    search_fields = ["workplace__name", "name"]


@admin.register(ContractTermSet)
class ContractTermSetAdmin(admin.ModelAdmin):
    list_display = ["contract", "effective_from", "employment_type", "hourly_rate", "monthly_salary"]
    list_filter = ["employment_type", "tax_card_type"]
    search_fields = ["contract__workplace__name"]
