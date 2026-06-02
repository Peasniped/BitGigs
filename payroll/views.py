import json
from datetime import date

from django.db import models
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.views import View

from workplaces.models import Workplace
from workplaces.services import workplaces_active_today
from .models import PayrollPeriod, PayslipLine, CommutingRecord, VacationBalance
from .services import (
    PayrollPeriodService,
    SalaryEstimateService,
    FlexTimeService,
    PayslipService,
    VacationService,
    CommutingService,
)
from shifts.services import ShiftSummaryService


class PayrollPeriodListView(View):
    def get(self, request):
        periods = PayrollPeriod.objects.select_related("workplace").all()[:50]
        workplaces = workplaces_active_today()
        return render(
            request,
            "payroll/period_list.html",
            {"periods": periods, "workplaces": workplaces},
        )


class PayrollPeriodGenerateView(View):
    """Generate a payroll period for a given workplace/month."""

    def post(self, request):
        workplace_id = request.POST.get("workplace")
        year = int(request.POST.get("year", date.today().year))
        month = int(request.POST.get("month", date.today().month))
        workplace = get_object_or_404(Workplace, pk=workplace_id)
        period, _ = PayrollPeriodService.get_or_create_period(workplace, year, month)
        # Always recalculate standard lines from current data
        PayslipService.populate_standard_lines(period)
        return redirect("payroll:period-detail", pk=period.pk)


class PayrollPeriodDetailView(View):
    def get(self, request, pk):
        period = get_object_or_404(
            PayrollPeriod.objects.select_related("workplace"), pk=pk
        )
        workplace = period.workplace
        from workplaces.models import ContractTermSet
        terms = workplace.active_termset_on(period.start_date)

        # Recalculate standard lines to reflect current data + custom adjustments
        if not period.is_locked:
            PayslipService.populate_standard_lines(period)

        # Build payslip (reads existing lines)
        payslip = PayslipService.build_payslip(period)

        # Session summary for the period
        summary = ShiftSummaryService.period_summary(
            period.start_date, period.end_date, workplace.id
        )

        # Salary estimate (use tax pull date for profile lookup)
        estimate = None
        flex = None
        if terms is not None:
            tax_pull_date = PayrollPeriodService.get_tax_pull_date(
                terms, period.end_date.year, period.end_date.month
            )
            estimate = SalaryEstimateService.estimate(
                terms, summary.total_hours, as_of=tax_pull_date
            )

            if terms.employment_type == ContractTermSet.EmploymentType.SALARIED:
                flex = FlexTimeService.calculate(
                    workplace, period.start_date, period.end_date
                )

        return render(
            request,
            "payroll/period_detail.html",
            {
                "period": period,
                "terms": terms,
                "payslip": payslip,
                "summary": summary,
                "estimate": estimate,
                "flex": flex,
            },
        )


class PayslipLineReorderView(View):
    """AJAX endpoint to reorder payslip lines via drag-and-drop."""

    def post(self, request, period_pk):
        try:
            data = json.loads(request.body)
            order = data.get("order", [])
            for idx, line_id in enumerate(order):
                PayslipLine.objects.filter(
                    pk=line_id, payroll_period_id=period_pk
                ).update(sort_order=idx)
            return JsonResponse({"status": "ok"})
        except (json.JSONDecodeError, KeyError):
            return JsonResponse({"status": "error"}, status=400)


class PayslipLineAddView(View):
    """Add a custom line to a payslip."""

    def post(self, request, period_pk):
        period = get_object_or_404(PayrollPeriod, pk=period_pk)
        if period.is_locked:
            return redirect("payroll:period-detail", pk=period.pk)

        name = request.POST.get("name", "Custom line")
        quantity_str = request.POST.get("quantity", "").strip()
        rate_str = request.POST.get("rate", "").strip()
        raw_type = request.POST.get("line_type", "deduct")
        line_type = "pre_tax_add" if raw_type == "add" else "pre_tax_deduct"

        from decimal import Decimal as D, InvalidOperation

        def parse_dk(s):
            if not s:
                return None
            try:
                return D(s.replace(".", "").replace(",", "."))
            except (InvalidOperation, ValueError):
                return None

        quantity = parse_dk(quantity_str) or D("1")
        rate = parse_dk(rate_str) or D("0")
        amount = (quantity * rate).quantize(D("0.01"))

        # Place after last line
        max_sort = PayslipLine.objects.filter(
            payroll_period=period
        ).aggregate(models.Max("sort_order"))["sort_order__max"] or 0

        PayslipLine.objects.create(
            payroll_period=period,
            name=name,
            quantity=quantity,
            rate=rate,
            amount=amount,
            line_type=line_type,
            is_editable=True,
            sort_order=max_sort + 1,
        )
        return redirect("payroll:period-detail", pk=period.pk)


class PayslipLineEditView(View):
    """Edit a custom (non-standard) payslip line."""

    def post(self, request, period_pk, line_pk):
        line = get_object_or_404(
            PayslipLine, pk=line_pk, payroll_period_id=period_pk
        )
        if line.standard_line_key:
            return redirect("payroll:period-detail", pk=period_pk)

        period = line.payroll_period
        if period.is_locked:
            return redirect("payroll:period-detail", pk=period.pk)

        from decimal import Decimal as D, InvalidOperation

        def parse_dk(s):
            if not s:
                return None
            try:
                return D(s.replace(".", "").replace(",", "."))
            except (InvalidOperation, ValueError):
                return None

        name = request.POST.get("name", line.name)
        quantity = parse_dk(request.POST.get("quantity", "")) or D("1")
        rate = parse_dk(request.POST.get("rate", "")) or D("0")
        raw_type = request.POST.get("line_type", "add")
        line_type = "pre_tax_add" if raw_type == "add" else "pre_tax_deduct"

        line.name = name
        line.quantity = quantity
        line.rate = rate
        line.amount = (quantity * rate).quantize(D("0.01"))
        line.line_type = line_type
        line.save()

        return redirect("payroll:period-detail", pk=period.pk)


class PayslipLineDeleteView(View):
    """Delete a custom (non-standard) payslip line."""

    def post(self, request, period_pk, line_pk):
        line = get_object_or_404(
            PayslipLine, pk=line_pk, payroll_period_id=period_pk
        )
        if line.standard_line_key:
            # Cannot delete standard lines
            return redirect("payroll:period-detail", pk=period_pk)
        line.delete()
        return redirect("payroll:period-detail", pk=period_pk)


class PayslipRecalculateView(View):
    """Recalculate standard lines for a period."""

    def post(self, request, period_pk):
        period = get_object_or_404(PayrollPeriod, pk=period_pk)
        if not period.is_locked:
            PayslipService.populate_standard_lines(period)
        return redirect("payroll:period-detail", pk=period.pk)


class TaxPullDayUpdateView(View):
    """AJAX endpoint to update the tax card pull day on the active ContractTermSet."""

    def post(self, request, period_pk):
        period = get_object_or_404(PayrollPeriod, pk=period_pk)
        try:
            data = json.loads(request.body)
            day = int(data.get("tax_pull_day", 18))
            day = max(1, min(28, day))
            terms = period.workplace.active_termset_on(period.start_date)
            if terms is not None:
                terms.tax_pull_day = day
                terms.save(update_fields=["tax_pull_day"])
            return JsonResponse({"status": "ok", "tax_pull_day": day})
        except (json.JSONDecodeError, ValueError, TypeError):
            return JsonResponse({"status": "error"}, status=400)


class CommutingListView(View):
    def get(self, request):
        records = CommutingRecord.objects.select_related("workplace").all()
        return render(
            request, "payroll/commuting_list.html", {"records": records}
        )


class CommutingAutoUpdateView(View):
    """Recalculate commuting days from on-site sessions."""

    def post(self, request):
        workplace_id = request.POST.get("workplace")
        year = int(request.POST.get("year", date.today().year))
        month = int(request.POST.get("month", date.today().month))
        workplace = get_object_or_404(Workplace, pk=workplace_id)
        CommutingService.update_commuting(workplace, year, month)
        return redirect("payroll:commuting-list")


class VacationOverviewView(View):
    def get(self, request):
        balances = VacationBalance.objects.select_related("workplace").all()
        return render(
            request, "payroll/vacation_overview.html", {"balances": balances}
        )


class VacationUpdateView(View):
    """Recalculate vacation balance for a workplace/month."""

    def post(self, request):
        workplace_id = request.POST.get("workplace")
        year = int(request.POST.get("year", date.today().year))
        month = int(request.POST.get("month", date.today().month))
        workplace = get_object_or_404(Workplace, pk=workplace_id)
        VacationService.update_balance(workplace, year, month)
        return redirect("payroll:vacation-overview")

