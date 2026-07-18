from decimal import Decimal

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import validate_email

from .models import TaxProfile, UserSettings


class OnboardingUserCreationForm(UserCreationForm):
    """Account creation for onboarding step 1. The username IS the email: it must
    be a valid email address and is copied into the User.email field on save.

    The setup key is *not* a field here — it is verified on the preceding page and
    recorded in the session (core.setup_key.SESSION_FLAG), which is what the views
    check before letting anyone reach this form."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Drop the "set/disable password" toggle Django adds by default — this is
        # a normal single-user account.
        self.fields.pop("usable_password", None)
        email = self.fields["username"]
        email.label = "Email"
        email.help_text = ""
        email.widget.attrs.update({"autocomplete": "email", "autofocus": True})

    def clean_username(self):
        username = self.cleaned_data["username"]
        validate_email(username)  # raises ValidationError on a non-email
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["username"]
        if commit:
            user.save()
        return user


class TaxProfileForm(forms.ModelForm):
    is_folkekirken_member = forms.BooleanField(
        required=False,
        label="Member of folkekirken",
        initial=False,
    )

    class Meta:
        model = TaxProfile
        fields = [
            "effective_from",
            "monthly_deduction",
            "tax_percent",
            "church_tax_percent",
            "am_bidrag_percent",
        ]
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["church_tax_percent"].required = False
        # Derive checkbox from existing data
        if self.instance and self.instance.pk:
            self.initial["is_folkekirken_member"] = self.instance.church_tax_percent > 0

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("is_folkekirken_member"):
            cleaned["church_tax_percent"] = Decimal("0.00")
        elif not cleaned.get("church_tax_percent"):
            self.add_error(
                "church_tax_percent",
                "Church tax rate is required if you are a member of folkekirken.",
            )
        return cleaned


class UserSettingsForm(forms.ModelForm):
    class Meta:
        model = UserSettings
        fields = [
            "week_start",
            "show_shift_type_colors",
            "show_help_button",
            "projection_method",
            "projection_trailing_months",
            "use_planned_shifts",
        ]
