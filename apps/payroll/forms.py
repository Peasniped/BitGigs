from django import forms
from .models import PayslipLine, PayslipLineTemplate, CommutingRecord


class PayslipLineForm(forms.ModelForm):
    class Meta:
        model = PayslipLine
        fields = ["name", "quantity", "rate", "amount", "line_type", "sort_order"]


class PayslipLineTemplateForm(forms.ModelForm):
    class Meta:
        model = PayslipLineTemplate
        fields = [
            "name",
            "default_quantity",
            "default_rate",
            "default_amount",
            "line_type",
            "sort_order",
        ]


class CommutingRecordForm(forms.ModelForm):
    class Meta:
        model = CommutingRecord
        fields = ["workplace", "year", "month", "commuting_days"]
