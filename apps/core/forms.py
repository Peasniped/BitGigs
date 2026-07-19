from decimal import Decimal

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.validators import validate_email

from .models import TaxProfile, UserSettings


class OnboardingUserCreationForm(UserCreationForm):
    """Account creation for onboarding step 1. The username IS the email: it must
    be a valid email address and is copied into the User.email field on save.

    A display name is **required** here: the username is an email address, so
    without one every greeting in the app would address the owner by their email.
    It is stored in ``User.first_name`` (the SSO bootstrap fills the same field
    from the IdP's ``name`` claim, so both account routes end up equivalent).

    The setup key is *not* a field here — it is verified on the preceding page and
    recorded in the session (core.setup_key.SESSION_FLAG), which is what the views
    check before letting anyone reach this form."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("first_name", "username")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Drop the "set/disable password" toggle Django adds by default — this is
        # a normal single-user account.
        self.fields.pop("usable_password", None)
        name = self.fields["first_name"]
        name.label = "Display name"
        name.required = True   # blank=True on the model would make it optional
        name.help_text = ""
        name.widget.attrs.update({"autocomplete": "name", "autofocus": True})
        email = self.fields["username"]
        email.label = "Email"
        email.help_text = ""
        email.widget.attrs.update({"autocomplete": "email"})

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

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


class AccountDetailsForm(forms.ModelForm):
    """Display name + sign-in email for the owner account (Settings → Sign-in).

    The username **is** the email (see `OnboardingUserCreationForm`), so saving
    here rewrites both fields together — they must never drift apart, or the
    login form and `core.adapters`' owner match (which compares both) would
    disagree about who the owner is. That is also why the email is capped at
    `User.username`'s 150 chars rather than `User.email`'s 254."""

    class Meta:
        model = User
        fields = ("first_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        name = self.fields["first_name"]
        name.label = "Display name"
        name.required = True   # blank=True on the model would make it optional
        name.widget.attrs.update({"autocomplete": "name"})
        email = self.fields["email"]
        email.label = "Email"
        email.required = True
        email.max_length = 150
        email.widget.attrs.update({"autocomplete": "email", "maxlength": 150})

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        validate_email(email)  # raises ValidationError on a non-email
        if len(email) > 150:
            raise forms.ValidationError(
                "Use an email address of 150 characters or fewer — it doubles as "
                "your username."
            )
        clash = User.objects.exclude(pk=self.instance.pk).filter(username__iexact=email)
        if clash.exists():
            raise forms.ValidationError("That email is already in use.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
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
    """The settings page renders one tab at a time, so the form is scoped to that
    tab's fields. ``construct_instance`` only writes the fields still in
    ``self.fields``, which is what keeps the other tabs' values intact when a
    partial POST comes back."""

    # Tab slug → the fields that tab owns. Order here is the render order.
    TABS = {
        "display": ["theme", "accent_color", "secondary_color", "week_start",
                    "show_shift_type_colors", "show_help_button"],
        "analytics": ["projection_method", "projection_trailing_months",
                      "use_planned_shifts"],
    }

    class Meta:
        model = UserSettings
        fields = [
            "theme",
            "accent_color",
            "secondary_color",
            "week_start",
            "show_shift_type_colors",
            "show_help_button",
            "projection_method",
            "projection_trailing_months",
            "use_planned_shifts",
        ]
        widgets = {
            # Driven by the swatch/wheel picker in settings.html (settings.js);
            # a bare text input would just invite typos.
            "accent_color": forms.HiddenInput(),
            "secondary_color": forms.HiddenInput(),
        }

    def __init__(self, *args, tab=None, **kwargs):
        super().__init__(*args, **kwargs)
        keep = self.TABS.get(tab)
        if keep is not None:
            for name in list(self.fields):
                if name not in keep:
                    del self.fields[name]

    def clean_accent_color(self):
        return self.cleaned_data["accent_color"].lower()

    def clean_secondary_color(self):
        return self.cleaned_data["secondary_color"].lower()
