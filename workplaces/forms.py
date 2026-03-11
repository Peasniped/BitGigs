from decimal import Decimal

from django import forms
from .models import Workplace


class WorkplaceForm(forms.ModelForm):
    WORK_TIME_CHOICES = [
        ("fuldtid", "Fuldtid (160,33 h/mo)"),
        ("deltid", "Deltid"),
    ]
    HOURS_TYPE_CHOICES = [
        ("fixed", "Fixed hours"),
        ("variable", "Variable hours"),
    ]

    work_time_type = forms.ChoiceField(
        choices=WORK_TIME_CHOICES,
        required=False,
        widget=forms.RadioSelect,
    )
    hours_type = forms.ChoiceField(
        choices=HOURS_TYPE_CHOICES,
        required=False,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Workplace
        fields = [
            "name",
            "is_active",
            "employment_type",
            "hourly_rate",
            "monthly_salary",
            "weekly_hours_fixed",
            "weekly_hours_min",
            "weekly_hours_max",
            "payroll_period_start_day",
            "tax_card_type",
            "vacation_type",
            "pension_employee_percent",
            "pension_employer_percent",
            "fritvalgskonto_percent",
            "fritvalgskonto_payout_type",
            "ferietillaeg_enabled",
            "ferietillaeg_percent",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make conditional fields not required at form level
        for f in [
            "hourly_rate", "monthly_salary", "weekly_hours_fixed",
            "weekly_hours_min", "weekly_hours_max",
        ]:
            self.fields[f].required = False

        # Sensible defaults for new forms
        if not self.initial.get("employment_type") and not self.data:
            self.initial["employment_type"] = Workplace.EmploymentType.SALARIED
        if not self.initial.get("work_time_type") and not self.data:
            self.initial["work_time_type"] = "fuldtid"
        if not self.initial.get("hours_type") and not self.data:
            self.initial["hours_type"] = "fixed"

        # Derive toggles from existing instance
        if self.instance and self.instance.pk:
            if self.instance.employment_type == Workplace.EmploymentType.SALARIED:
                if self.instance.weekly_hours_fixed == Decimal("37.00"):
                    self.initial["work_time_type"] = "fuldtid"
                else:
                    self.initial["work_time_type"] = "deltid"
            elif self.instance.employment_type == Workplace.EmploymentType.HOURLY:
                if self.instance.weekly_hours_fixed is not None:
                    self.initial["hours_type"] = "fixed"
                elif self.instance.weekly_hours_min is not None:
                    self.initial["hours_type"] = "variable"

    def clean(self):
        cleaned = super().clean()
        emp_type = cleaned.get("employment_type")

        if emp_type == Workplace.EmploymentType.SALARIED:
            cleaned["hourly_rate"] = None
            cleaned["weekly_hours_min"] = None
            cleaned["weekly_hours_max"] = None
            cleaned["payroll_period_start_day"] = 1

            wtt = cleaned.get("work_time_type", "")
            if wtt == "fuldtid":
                cleaned["weekly_hours_fixed"] = Decimal("37.00")
            elif not cleaned.get("weekly_hours_fixed"):
                self.add_error("weekly_hours_fixed", "Hours per week is required for deltid.")

            if not cleaned.get("monthly_salary"):
                self.add_error("monthly_salary", "Grundløn is required for salaried employment.")

        elif emp_type == Workplace.EmploymentType.HOURLY:
            cleaned["monthly_salary"] = None

            if not cleaned.get("hourly_rate"):
                self.add_error("hourly_rate", "Hourly rate is required.")

            ht = cleaned.get("hours_type", "")
            if ht == "variable":
                cleaned["weekly_hours_fixed"] = None
                if not cleaned.get("weekly_hours_min") or not cleaned.get("weekly_hours_max"):
                    self.add_error("weekly_hours_min", "Both min and max hours are required.")
            else:
                cleaned["weekly_hours_min"] = None
                cleaned["weekly_hours_max"] = None
                if not cleaned.get("weekly_hours_fixed"):
                    self.add_error("weekly_hours_fixed", "Hours per week is required.")

        return cleaned
