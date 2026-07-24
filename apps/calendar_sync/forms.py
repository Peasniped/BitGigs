"""Forms for the Settings → Calendar tab (both directions)."""
from django import forms

from .models import (
    CalendarInviteSettings,
    CalendarSubscription,
    WorkplaceCalendarConfig,
)


class CalendarSubscriptionForm(forms.ModelForm):
    """Add/edit a calendar subscription. The URL is write-only — like the SMTP
    password, the stored value is never rendered back; blank on edit keeps it."""

    url = forms.URLField(
        assume_scheme="https",
        required=False,
        label="Calendar URL (iCal)",
        help_text="The private iCal (.ics) URL from your calendar provider. "
                  "Leave blank when editing to keep the stored one.",
        widget=forms.URLInput(attrs={"placeholder": "https://…/basic.ics"}),
    )

    class Meta:
        model = CalendarSubscription
        fields = ["label", "url", "color", "enabled"]
        widgets = {
            "color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["url"].initial = ""  # never echo the stored URL

    def clean_url(self):
        url = self.cleaned_data.get("url", "").strip()
        if not url and not self.instance.pk:
            raise forms.ValidationError("A calendar URL is required.")
        return url

    def save(self, commit=True):
        instance = super().save(commit=False)
        url = self.cleaned_data.get("url")
        if url:
            instance.url = url
        if commit:
            instance.save()
        return instance


class CalendarInviteSettingsForm(forms.ModelForm):
    class Meta:
        model = CalendarInviteSettings
        fields = ["enabled", "owner_address", "default_remote_address"]
        labels = {
            "enabled": "Send calendar invites",
            "owner_address": "Invite my own calendar",
            "default_remote_address": "Default remote location",
        }
        help_texts = {
            "default_remote_address": "Used for remote shifts when a workplace sets "
                                      "no location of its own — an address or a named "
                                      "place (e.g. “Home” or a street address).",
        }


class WorkplaceCalendarConfigForm(forms.ModelForm):
    class Meta:
        model = WorkplaceCalendarConfig
        fields = [
            "send_invites", "recipients",
            "title_onsite", "title_remote",
            "address_onsite", "address_remote",
        ]
        widgets = {
            "recipients": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Clearing a title shouldn't error — it just falls back to the default.
        self.fields["title_onsite"].required = False
        self.fields["title_remote"].required = False

    def clean_title_onsite(self):
        return (self.cleaned_data.get("title_onsite")
                or WorkplaceCalendarConfig.TITLE_ONSITE_DEFAULT)

    def clean_title_remote(self):
        return (self.cleaned_data.get("title_remote")
                or WorkplaceCalendarConfig.TITLE_REMOTE_DEFAULT)
