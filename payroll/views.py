import json
from datetime import date

from django.db import models
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.views import View

from workplaces.models import Workplace
from .models import PayrollPeriod, PayslipLine, CommutingRecord, VacationBalance
from .services import (
    PayrollPeriodService,
    SalaryEstimateService,
    FlexTimeService,
    PayslipService,
    VacationService,
    CommutingService,
)
from worksessions.services import SessionSummaryService


class PayrollPeriodListView(View):
    def get(self, request):
        periods = PayrollPeriod.objects.select_related("workplace").all()[:50]
        workplaces = Workplace.objects.filter(is_active=True)
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

        # Build payslip (reads existing lines — standard lines should already exist)
        payslip = PayslipService.build_payslip(period)

        # Session summary for the period
        summary = SessionSummaryService.period_summary(
            period.start_date, period.end_date, workplace.id
        )

        # Salary estimate
        estimate = SalaryEstimateService.estimate(
            workplace, summary.total_hours, as_of=period.start_date
        )

        # Flex time (salaried only)
        flex = None
        if workplace.employment_type == Workplace.EmploymentType.SALARIED:
            flex = FlexTimeService.calculate(
                workplace, period.start_date, period.end_date
            )

        return render(
            request,
            "payroll/period_detail.html",
            {
                "period": period,
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
        amount = request.POST.get("amount", "0")
        line_type = request.POST.get("line_type", "pre_tax_deduct")
        try:
            from decimal import Decimal as D
            amount_dec = D(amount.replace(",", "."))
        except Exception:
            amount_dec = Decimal("0")

        # Place after last standard line, before any existing custom lines
        max_sort = PayslipLine.objects.filter(
            payroll_period=period
        ).aggregate(models.Max("sort_order"))["sort_order__max"] or 0

        PayslipLine.objects.create(
            payroll_period=period,
            name=name,
            amount=amount_dec,
            line_type=line_type,
            is_editable=True,
            sort_order=max_sort + 1,
        )
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
