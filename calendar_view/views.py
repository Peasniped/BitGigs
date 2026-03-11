from datetime import date

from django.shortcuts import render
from django.views import View

from workplaces.models import Workplace
from .services import CalendarService


class MonthCalendarView(View):
    """Standard month calendar view, optionally filtered by workplace."""

    def get(self, request):
        year = int(request.GET.get("year", date.today().year))
        month = int(request.GET.get("month", date.today().month))
        workplace_id = request.GET.get("workplace")
        workplace_id = int(workplace_id) if workplace_id else None

        grid = CalendarService.month_calendar(year, month, workplace_id)

        # Navigation
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        workplaces = Workplace.objects.filter(is_active=True)

        return render(
            request,
            "calendar_view/month.html",
            {
                "grid": grid,
                "year": year,
                "month": month,
                "workplace_id": workplace_id,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
                "workplaces": workplaces,
            },
        )


class PayrollPeriodCalendarView(View):
    """Calendar view aligned to a payroll period for a specific workplace."""

    def get(self, request):
        year = int(request.GET.get("year", date.today().year))
        month = int(request.GET.get("month", date.today().month))
        workplace_id = int(request.GET.get("workplace", 0))

        if not workplace_id:
            # If no workplace selected, show workplace picker
            workplaces = Workplace.objects.filter(is_active=True)
            return render(
                request,
                "calendar_view/payroll_period_select.html",
                {"workplaces": workplaces, "year": year, "month": month},
            )

        grid = CalendarService.payroll_period_calendar(workplace_id, year, month)

        # Navigation
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        return render(
            request,
            "calendar_view/payroll_period.html",
            {
                "grid": grid,
                "year": year,
                "month": month,
                "workplace_id": workplace_id,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
            },
        )
