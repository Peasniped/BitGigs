"""Admin registration for calendar subscriptions.

A stop-gap management surface until the Calendar settings tab lands (Phase 3):
the owner is a superuser, so this lets a subscription be added/tested from
``/admin/`` in the meantime. The URL is write-through-encrypted via the model's
``url`` property, so the admin never touches ``url_encrypted`` directly.
"""
from django import forms
from django.contrib import admin

from .models import CalendarSubscription


class CalendarSubscriptionForm(forms.ModelForm):
    url = forms.URLField(
        assume_scheme="https",
        required=False,
        help_text="The private iCal (.ics) URL from your calendar provider. "
                  "Leave blank to keep the stored one.",
        widget=forms.URLInput(attrs={"size": 80}),
    )

    class Meta:
        model = CalendarSubscription
        fields = ["label", "url", "enabled", "color"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Never render the stored URL back into the form — treat it write-only,
        # like the SMTP password field. Blank on submit means "keep it".
        self.fields["url"].initial = ""

    def save(self, commit=True):
        instance = super().save(commit=False)
        submitted = self.cleaned_data.get("url")
        if submitted:
            instance.url = submitted
        if commit:
            instance.save()
        return instance


@admin.register(CalendarSubscription)
class CalendarSubscriptionAdmin(admin.ModelAdmin):
    form = CalendarSubscriptionForm
    list_display = ["label", "enabled", "color", "last_fetch_at", "last_fetch_ok"]
    readonly_fields = ["last_fetch_at", "last_fetch_ok", "last_error"]
