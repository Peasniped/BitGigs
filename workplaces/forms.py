from datetime import date
from decimal import Decimal

from django import forms
from .models import Workplace, WorkplaceContract, ContractTermSet


class WorkplaceForm(forms.ModelForm):
    """Appearance-only form: name, slug, active status."""

    class Meta:
        model = Workplace
        fields = ["name", "slug"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["slug"].help_text = "Leave blank to auto-generate from name."


class WorkplaceContractForm(forms.ModelForm):
    """Contract metadata: name (optional), start/end dates."""

    class Meta:
        model = WorkplaceContract
        fields = ["name", "start_date", "end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, workplace=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workplace = workplace
        self.fields["start_date"].required = True
        self.fields["end_date"].required = False
        if not self.initial.get("start_date") and not self.data:
            self.initial["start_date"] = date.today()


class ContractTermSetForm(forms.ModelForm):
    """All employment-settings fields, plus the effective_from date."""

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
        model = ContractTermSet
        fields = [
            "effective_from",
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
            "fritvalgskonto_enabled",
            "fritvalgskonto_percent",
            "fritvalgskonto_payout_type",
            "ferietillaeg_enabled",
            "ferietillaeg_percent",
            "ferietillaeg_payout_months",
            "hour_goal_type",
            "hour_goal_min",
            "hour_goal_max",
        ]
        widgets = {
            "effective_from": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, contract=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Contract whose bounds constrain effective_from. Falls back to the
        # instance's contract when editing an existing termset.
        self.contract = contract or (
            self.instance.contract if self.instance and self.instance.contract_id else None
        )

        for f in [
            "hourly_rate", "monthly_salary", "weekly_hours_fixed",
            "weekly_hours_min", "weekly_hours_max",
            "pension_employee_percent", "pension_employer_percent",
            "fritvalgskonto_percent", "fritvalgskonto_payout_type",
            "ferietillaeg_percent", "ferietillaeg_payout_months",
        ]:
            self.fields[f].required = False

        # Seed model defaults so blank fields don't fail validation
        _defaults = {
            "pension_employee_percent": Decimal("0"),
            "pension_employer_percent": Decimal("0"),
            "fritvalgskonto_percent": Decimal("0"),
            "ferietillaeg_percent": Decimal("1.00"),
            "fritvalgskonto_payout_type": ContractTermSet.FritvalgsPayoutType.ACCRUES,
            "ferietillaeg_payout_months": "5,8",
            "payroll_period_start_day": 1,
        }
        if not self.data:  # only for unbound (GET) forms
            for field, default in _defaults.items():
                if not self.initial.get(field):
                    self.initial[field] = default

        if not self.initial.get("effective_from") and not self.data:
            self.initial["effective_from"] = date.today()
        if not self.initial.get("employment_type") and not self.data:
            self.initial["employment_type"] = ContractTermSet.EmploymentType.SALARIED
        if not self.initial.get("work_time_type") and not self.data:
            self.initial["work_time_type"] = "fuldtid"
        if not self.initial.get("hours_type") and not self.data:
            self.initial["hours_type"] = "fixed"

        if self.instance and self.instance.pk:
            if self.instance.employment_type == ContractTermSet.EmploymentType.SALARIED:
                if self.instance.weekly_hours_fixed == Decimal("37.00"):
                    self.initial["work_time_type"] = "fuldtid"
                else:
                    self.initial["work_time_type"] = "deltid"
            elif self.instance.employment_type == ContractTermSet.EmploymentType.HOURLY:
                if self.instance.weekly_hours_fixed is not None:
                    self.initial["hours_type"] = "fixed"
                elif self.instance.weekly_hours_min is not None:
                    self.initial["hours_type"] = "variable"

    def clean(self):
        cleaned = super().clean()
        emp_type = cleaned.get("employment_type")

        # effective_from must fall within the parent contract's date range
        eff = cleaned.get("effective_from")
        if eff and self.contract:
            if eff < self.contract.start_date:
                self.add_error("effective_from", (
                    f"Must be on or after the contract start "
                    f"({self.contract.start_date})."
                ))
            elif self.contract.end_date and eff > self.contract.end_date:
                self.add_error("effective_from", (
                    f"Must be on or before the contract end "
                    f"({self.contract.end_date})."
                ))

        if emp_type == ContractTermSet.EmploymentType.SALARIED:
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

        elif emp_type == ContractTermSet.EmploymentType.HOURLY:
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

        goal_min = cleaned.get("hour_goal_min")
        goal_max = cleaned.get("hour_goal_max")
        goal_mode = self.data.get("goalMode", "target")
        if goal_mode == "range" and goal_min is not None and goal_max is None:
            self.add_error("hour_goal_max", "Max is required when using range mode.")
        if goal_min is not None and goal_max is not None and goal_min >= goal_max:
            self.add_error("hour_goal_max", "Max must be greater than min.")

        return cleaned
