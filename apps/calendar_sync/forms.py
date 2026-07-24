"""Forms for the Settings → Calendar tab (both directions) and the per-contract
invite configuration edited on the contract page."""
from django import forms

from .models import (
    CalendarInviteSettings,
    CalendarSubscription,
    ContractCalendarConfig,
    TITLE_ONSITE_DEFAULT,
    TITLE_REMOTE_DEFAULT,
)


def _account_email():
    """The single owner account's email (its login is the email)."""
    from django.contrib.auth.models import User

    owner = (
        User.objects.filter(is_superuser=True).order_by("pk").first()
        or User.objects.order_by("pk").first()
    )
    if not owner:
        return ""
    return owner.email or owner.username


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
    """Global invite settings + operator-level defaults (items 6, 10, 13)."""

    class Meta:
        model = CalendarInviteSettings
        fields = [
            "enabled",
            "send_to_personal", "owner_address",
            "default_title_onsite", "default_title_remote",
            "default_remote_address",
        ]
        labels = {
            "enabled": "Send calendar invites",
            "send_to_personal": "Send invites to personal calendar",
            "owner_address": "Personal calendar address",
            "default_title_onsite": "Default on-site event title",
            "default_title_remote": "Default remote event title",
            "default_remote_address": "Default remote location",
        }
        help_texts = {
            "default_remote_address": "Used for remote shifts when a contract sets "
                                      "no location of its own — an address or a named "
                                      "place (e.g. “Home” or a street address).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A blank default title just falls back to the built-in default, so it
        # must not fail the save (and a partial POST shouldn't require it).
        self.fields["default_title_onsite"].required = False
        self.fields["default_title_remote"].required = False
        # item 10: the personal-calendar address defaults to the account email —
        # surface it as a placeholder so a blank field reads as "use my account
        # email", not "send to nobody" (send-time resolution does the same).
        acct = _account_email()
        if acct:
            self.fields["owner_address"].widget.attrs["placeholder"] = acct
            self.fields["owner_address"].help_text = (
                f"Leave blank to use your account email ({acct})."
            )

    def clean_default_title_onsite(self):
        return self.cleaned_data.get("default_title_onsite") or TITLE_ONSITE_DEFAULT

    def clean_default_title_remote(self):
        return self.cleaned_data.get("default_title_remote") or TITLE_REMOTE_DEFAULT


class ContractCalendarConfigForm(forms.ModelForm):
    """Per-contract invite config, edited on the contract page (items 7, 8).

    Every field but ``address_onsite`` inherits an operator default unless its
    ``override_*`` toggle is on; the toggle is what makes an override obvious.
    The contract page's JS enables/disables each value field from its toggle.
    """

    class Meta:
        model = ContractCalendarConfig
        fields = [
            "send_invites",
            "recipient", "address_onsite",
            "override_title_onsite", "title_onsite",
            "override_title_remote", "title_remote",
            "override_address_remote", "address_remote",
        ]
        labels = {
            "send_invites": "Send calendar invites for this contract",
            "recipient": "Work e-mail address",
            "address_onsite": "On-site location",
            "override_title_onsite": "Override default on-site title",
            "title_onsite": "On-site event title",
            "override_title_remote": "Override default remote title",
            "title_remote": "Remote event title",
            "override_address_remote": "Override default remote location",
            "address_remote": "Remote location",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Everything is optional at field level; clean() makes the work e-mail and
        # on-site location required *when invites are on*, and treats a blank
        # override as inheriting.
        for name in ("recipient", "address_onsite", "title_onsite",
                     "title_remote", "address_remote"):
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        # An override toggled on with an empty value is a no-op that would read as
        # "custom, but blank" — treat it as inheriting instead of silently sending
        # nothing/an empty title.
        for toggle, value in (
            ("override_title_onsite", "title_onsite"),
            ("override_title_remote", "title_remote"),
            ("override_address_remote", "address_remote"),
        ):
            if cleaned.get(toggle) and not (cleaned.get(value) or "").strip():
                cleaned[toggle] = False
        # Invites on → a work recipient and an on-site location are required.
        if cleaned.get("send_invites"):
            if not (cleaned.get("recipient") or "").strip():
                self.add_error("recipient", "Add a work e-mail address to invite.")
            if not (cleaned.get("address_onsite") or "").strip():
                self.add_error("address_onsite", "Add the on-site location.")
        return cleaned
