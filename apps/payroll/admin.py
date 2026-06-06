from django.contrib import admin
from .models import (
    PayrollPeriod,
    PayslipLine,
    PayslipLineTemplate,
    CommutingRecord,
    VacationBalance,
)


class PayslipLineInline(admin.TabularInline):
    model = PayslipLine
    extra = 1
    fields = ["sort_order", "name", "quantity", "rate", "amount", "line_type"]


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ["workplace", "start_date", "end_date", "is_locked"]
    list_filter = ["workplace", "is_locked"]
    inlines = [PayslipLineInline]


@admin.register(PayslipLineTemplate)
class PayslipLineTemplateAdmin(admin.ModelAdmin):
    list_display = ["workplace", "name", "line_type", "sort_order"]
    list_filter = ["workplace", "line_type"]


@admin.register(CommutingRecord)
class CommutingRecordAdmin(admin.ModelAdmin):
    list_display = ["workplace", "year", "month", "commuting_days"]
    list_filter = ["workplace", "year"]


@admin.register(VacationBalance)
class VacationBalanceAdmin(admin.ModelAdmin):
    list_display = [
        "workplace",
        "year",
        "month",
        "carried_over_hours",
        "accrued_hours",
        "used_hours",
        "balance",
    ]
    list_filter = ["workplace", "year"]
