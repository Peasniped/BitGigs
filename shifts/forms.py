from django import forms
from .models import Shift


class ShiftForm(forms.ModelForm):
    class Meta:
        model = Shift
        fields = [
            "workplace",
            "date",
            "start_time",
            "end_time",
            "break_minutes",
            "shift_type",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class ShiftFilterForm(forms.Form):
    """Filter shifts by date range and/or workplace."""

    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    workplace = forms.IntegerField(required=False, widget=forms.HiddenInput())
