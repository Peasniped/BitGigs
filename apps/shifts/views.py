from datetime import date, timedelta

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.views import View

from .models import Shift
from .forms import ShiftForm
from .services import ShiftSummaryService
from core.services import TaxCalculationService
from core.utils import prev_next_month


class ShiftCreateView(View):
    def get(self, request):
        initial = {}
        workplace_id = request.GET.get("workplace")
        if "date" in request.GET:
            initial["date"] = request.GET["date"]
        if workplace_id:
            initial["workplace"] = workplace_id
        form = ShiftForm(initial=initial)
        hide_workplace = bool(workplace_id)
        return render(
            request,
            "shifts/shift_form.html",
            {"form": form, "hide_workplace": hide_workplace, "workplace_id": workplace_id},
        )

    def post(self, request):
        form = ShiftForm(request.POST)
        workplace_id = request.POST.get("workplace") or request.GET.get("workplace")
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        if form.is_valid():
            shift = form.save()
            warning = TaxCalculationService.coverage_warning(shift.date)
            if warning:
                messages.warning(request, warning)
            if is_ajax:
                return JsonResponse({
                    "status": "ok",
                    "shift": {
                        "pk": shift.pk,
                        "start_time": shift.start_time.strftime("%H:%M"),
                        "end_time": shift.end_time.strftime("%H:%M"),
                        "net_hours": str(shift.net_hours),
                        "shift_type": shift.get_shift_type_display(),
                        "break_minutes": shift.break_minutes,
                    },
                })
            if shift.workplace_id:
                from django.urls import reverse
                url = reverse("workplaces:workplace-detail", args=[shift.workplace.slug])
                day_param = shift.date.isoformat()
                return redirect(f"{url}?day={day_param}")
            return redirect("core:dashboard")

        if is_ajax:
            return JsonResponse({"status": "error", "errors": form.errors}, status=400)
        return render(
            request,
            "shifts/shift_form.html",
            {"form": form, "hide_workplace": False, "workplace_id": workplace_id},
        )


class ShiftUpdateView(View):
    def get(self, request, pk):
        shift = get_object_or_404(Shift, pk=pk)
        form = ShiftForm(instance=shift)
        return render(
            request,
            "shifts/shift_form.html",
            {"form": form, "shift": shift},
        )

    def post(self, request, pk):
        shift = get_object_or_404(Shift, pk=pk)
        form = ShiftForm(request.POST, instance=shift)
        if form.is_valid():
            form.save()
            warning = TaxCalculationService.coverage_warning(shift.date)
            if warning:
                messages.warning(request, warning)
            next_page = request.GET.get("next") or request.POST.get("next")
            if next_page == "workplace" and shift.workplace_id:
                from django.urls import reverse
                url = reverse("workplaces:workplace-detail", args=[shift.workplace.slug])
                day_param = shift.date.isoformat()
                return redirect(f"{url}?day={day_param}")
            return redirect("core:dashboard")
        return render(
            request,
            "shifts/shift_form.html",
            {"form": form, "shift": shift},
        )


class ShiftDeleteView(View):
    def post(self, request, pk):
        shift = get_object_or_404(Shift, pk=pk)
        wp_slug = shift.workplace.slug if shift.workplace_id else None
        shift.delete()
        next_page = request.GET.get("next") or request.POST.get("next")
        if next_page == "workplace" and wp_slug:
            return redirect("workplaces:workplace-detail", slug=wp_slug)
        return redirect("core:dashboard")


class DailyOverviewView(View):
    """Show all shifts for a given date, grouped by workplace."""

    def get(self, request, year, month, day):
        try:
            target_date = date(year, month, day)
        except ValueError:  # e.g. /daily/2026/2/31/ — not a date
            raise Http404("No such date.")
        summaries = ShiftSummaryService.daily_summary(target_date)
        prev_date = target_date - timedelta(days=1)
        next_date = target_date + timedelta(days=1)

        return render(
            request,
            "shifts/daily_overview.html",
            {
                "date": target_date,
                "summaries": summaries,
                "prev_date": prev_date,
                "next_date": next_date,
            },
        )


class MonthlyOverviewView(View):
    """Show monthly aggregates for all workplaces."""

    def get(self, request, year, month):
        if not 1 <= month <= 12:
            raise Http404("No such month.")
        summaries = ShiftSummaryService.monthly_summary(year, month)
        prev_year, prev_month, next_year, next_month = prev_next_month(year, month)

        return render(
            request,
            "shifts/monthly_overview.html",
            {
                "year": year,
                "month": month,
                "summaries": summaries,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
            },
        )
