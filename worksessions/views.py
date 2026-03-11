from datetime import date, timedelta

from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.views import View

from .models import WorkSession
from .forms import WorkSessionForm
from .services import SessionSummaryService


class SessionCreateView(View):
    def get(self, request):
        initial = {}
        workplace_id = request.GET.get("workplace")
        if "date" in request.GET:
            initial["date"] = request.GET["date"]
        if workplace_id:
            initial["workplace"] = workplace_id
        form = WorkSessionForm(initial=initial)
        # If workplace is pre-selected, hide the field
        hide_workplace = bool(workplace_id)
        return render(
            request,
            "worksessions/session_form.html",
            {"form": form, "hide_workplace": hide_workplace, "workplace_id": workplace_id},
        )

    def post(self, request):
        form = WorkSessionForm(request.POST)
        workplace_id = request.POST.get("workplace") or request.GET.get("workplace")
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        if form.is_valid():
            session = form.save()
            if is_ajax:
                return JsonResponse({
                    "status": "ok",
                    "session": {
                        "pk": session.pk,
                        "start_time": session.start_time.strftime("%H:%M"),
                        "end_time": session.end_time.strftime("%H:%M"),
                        "net_hours": str(session.net_hours),
                        "session_type": session.get_session_type_display(),
                        "break_minutes": session.break_minutes,
                    },
                })
            # Redirect back to workplace detail if we have a workplace
            if session.workplace_id:
                from django.urls import reverse
                url = reverse("workplaces:workplace-detail", args=[session.workplace_id])
                day_param = session.date.isoformat()
                return redirect(f"{url}?day={day_param}")
            return redirect("core:dashboard")

        if is_ajax:
            return JsonResponse({"status": "error", "errors": form.errors}, status=400)
        return render(
            request,
            "worksessions/session_form.html",
            {"form": form, "hide_workplace": False, "workplace_id": workplace_id},
        )


class SessionUpdateView(View):
    def get(self, request, pk):
        session = get_object_or_404(WorkSession, pk=pk)
        form = WorkSessionForm(instance=session)
        return render(
            request,
            "worksessions/session_form.html",
            {"form": form, "session": session},
        )

    def post(self, request, pk):
        session = get_object_or_404(WorkSession, pk=pk)
        form = WorkSessionForm(request.POST, instance=session)
        if form.is_valid():
            form.save()
            next_page = request.GET.get("next") or request.POST.get("next")
            if next_page == "workplace" and session.workplace_id:
                from django.urls import reverse
                url = reverse("workplaces:workplace-detail", args=[session.workplace_id])
                day_param = session.date.isoformat()
                return redirect(f"{url}?day={day_param}")
            return redirect("core:dashboard")
        return render(
            request,
            "worksessions/session_form.html",
            {"form": form, "session": session},
        )


class SessionDeleteView(View):
    def post(self, request, pk):
        session = get_object_or_404(WorkSession, pk=pk)
        wp_id = session.workplace_id
        session.delete()
        next_page = request.GET.get("next") or request.POST.get("next")
        if next_page == "workplace" and wp_id:
            return redirect("workplaces:workplace-detail", pk=wp_id)
        return redirect("core:dashboard")


class DailyOverviewView(View):
    """Show all sessions for a given date, grouped by workplace."""

    def get(self, request, year, month, day):
        target_date = date(year, month, day)
        summaries = SessionSummaryService.daily_summary(target_date)
        prev_date = target_date - timedelta(days=1)
        next_date = target_date + timedelta(days=1)

        return render(
            request,
            "worksessions/daily_overview.html",
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
        summaries = SessionSummaryService.monthly_summary(year, month)

        # Prev/next month navigation
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
            "worksessions/monthly_overview.html",
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
