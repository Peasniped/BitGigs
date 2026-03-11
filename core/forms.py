from decimal import Decimal

from django import forms
from .models import TaxProfile, UserSettings


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
        fields = ["week_start"]
