from django.contrib import admin
from .models import TaxProfile, ATPConfiguration, ATPBracket


@admin.register(TaxProfile)
class TaxProfileAdmin(admin.ModelAdmin):
    list_display = [
        "effective_from",
        "monthly_deduction",
        "tax_percent",
        "church_tax_percent",
        "am_bidrag_percent",
    ]
    ordering = ["-effective_from"]


class ATPBracketInline(admin.TabularInline):
    model = ATPBracket
    extra = 1


@admin.register(ATPConfiguration)
class ATPConfigurationAdmin(admin.ModelAdmin):
    list_display = ["effective_from"]
    ordering = ["-effective_from"]
    inlines = [ATPBracketInline]
