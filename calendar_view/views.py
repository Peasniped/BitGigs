import json
from datetime import date, time
from decimal import Decimal

from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views import View

from workplaces.models import Workplace
from workplaces.services import workplaces_active_today
from shifts.models import PlannedShift, Shift
from core.utils import avatar_for_name, prev_next_month
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
        prev_year, prev_month, next_year, next_month = prev_next_month(year, month)

        workplaces = workplaces_active_today()

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
            workplaces = workplaces_active_today()
            return render(
                request,
                "calendar_view/payroll_period_select.html",
                {"workplaces": workplaces, "year": year, "month": month},
            )

        grid = CalendarService.payroll_period_calendar(workplace_id, year, month)

        # Navigation
        prev_year, prev_month, next_year, next_month = prev_next_month(year, month)

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


class PlanningCalendarView(View):
    """Full-page planning calendar: drag workplaces onto days to plan shifts."""

    def get(self, request):
        from payroll.services import PayrollPeriodService
        from decimal import Decimal

        today = date.today()
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))

        grid = CalendarService.planning_calendar(year, month)

        # Navigation
        prev_year, prev_month, next_year, next_month = prev_next_month(year, month)

        workplaces = workplaces_active_today()

        import calendar as _cal_mod

        # Build workplace data with avatars, default shifts, payroll periods, monthly hours
        workplace_data = []
        for wp in workplaces:
            initials, color = avatar_for_name(wp.name)
            mid = date(year, month, 15)
            terms = wp.active_termset_on(mid)

            if terms is not None:
                period_start, period_end = PayrollPeriodService.get_period_dates(terms, year, month)
            else:
                last_day = _cal_mod.monthrange(year, month)[1]
                period_start = date(year, month, 1)
                period_end = date(year, month, last_day)

            # Calculate planned hours this month
            planned_hours = sum(
                (p.net_hours for p in PlannedShift.objects.filter(
                    workplace=wp,
                    date__gte=period_start,
                    date__lte=period_end,
                    status=PlannedShift.Status.PLANNED,
                )),
                Decimal("0"),
            )
            approved_hours = sum(
                (s.net_hours for s in Shift.objects.filter(
                    workplace=wp,
                    date__gte=period_start,
                    date__lte=period_end,
                )),
                Decimal("0"),
            )

            workplace_data.append({
                "id": wp.pk,
                "name": wp.name,
                "icon": wp.icon,
                "custom_icon_url": wp.custom_icon.url if wp.custom_icon else "",
                "color": wp.color or color,
                "accent_color": wp.accent_color or "",
                "initials": initials,
                "default_start": terms.default_shift_start_time.strftime("%H:%M") if terms and terms.default_shift_start_time else "",
                "default_end": terms.default_shift_end_time.strftime("%H:%M") if terms and terms.default_shift_end_time else "",
                "default_break": terms.default_shift_break_minutes if terms else 0,
                "default_type": terms.default_shift_type if terms else "on_site",
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "planned_hours": str(planned_hours),
                "approved_hours": str(approved_hours),
                "total_hours": str(planned_hours + approved_hours),
                "hour_goal_type": terms.hour_goal_type if terms else "",
                "hour_goal_min": str(terms.hour_goal_min) if terms and terms.hour_goal_min else "",
                "hour_goal_max": str(terms.hour_goal_max) if terms and terms.hour_goal_max else "",
            })

        import json as _json
        import calendar as _cal

        # Month names for JS warning messages
        month_names_json = _json.dumps({str(i): _cal.month_name[i] for i in range(1, 13)})

        return render(
            request,
            "calendar_view/planning.html",
            {
                "grid": grid,
                "year": year,
                "month": month,
                "prev_year": prev_year,
                "prev_month": prev_month,
                "next_year": next_year,
                "next_month": next_month,
                "workplaces": workplaces,
                "workplace_json": _json.dumps(workplace_data),
                "month_names_json": month_names_json,
                "today": today,
            },
        )


class PlannedShiftAPIView(View):
    """JSON API for CRUD operations on planned shifts."""

    def post(self, request):
        """Create a new planned shift."""
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        workplace_id = data.get("workplace_id")
        shift_date = data.get("date")
        start_time_str = data.get("start_time")
        end_time_str = data.get("end_time")
        break_minutes = int(data.get("break_minutes", 0))
        shift_type = data.get("shift_type", "on_site")
        notes = data.get("notes", "")

        if not all([workplace_id, shift_date, start_time_str, end_time_str]):
            return JsonResponse({"ok": False, "error": "Missing required fields."}, status=400)

        workplace = get_object_or_404(Workplace, pk=workplace_id)
        parsed_date = date.fromisoformat(shift_date)
        start_time = time.fromisoformat(start_time_str)
        end_time = time.fromisoformat(end_time_str)

        if start_time >= end_time:
            return JsonResponse({"ok": False, "error": "End time must be after start time."}, status=400)

        # Check for overlaps with existing sessions and planned shifts
        overlaps = _check_overlaps(parsed_date, start_time, end_time)

        shift = PlannedShift.objects.create(
            workplace=workplace,
            date=parsed_date,
            start_time=start_time,
            end_time=end_time,
            break_minutes=break_minutes,
            shift_type=shift_type,
            notes=notes,
        )

        return JsonResponse({
            "ok": True,
            "shift": _shift_to_dict(shift),
            "overlaps": overlaps,
        })


class PlannedShiftUpdateAPIView(View):
    """Update or delete a planned shift."""

    def post(self, request, pk):
        """Update a planned shift."""
        shift = get_object_or_404(PlannedShift, pk=pk, status=PlannedShift.Status.PLANNED)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        if "date" in data:
            shift.date = date.fromisoformat(data["date"])
        if "start_time" in data:
            shift.start_time = time.fromisoformat(data["start_time"])
        if "end_time" in data:
            shift.end_time = time.fromisoformat(data["end_time"])
        if "break_minutes" in data:
            shift.break_minutes = int(data["break_minutes"])
        if "shift_type" in data:
            shift.shift_type = data["shift_type"]
        if "notes" in data:
            shift.notes = data["notes"]
        if "arrival_confirmed" in data:
            shift.arrival_confirmed = bool(data["arrival_confirmed"])

        if shift.start_time >= shift.end_time:
            return JsonResponse({"ok": False, "error": "End time must be after start time."}, status=400)

        overlaps = _check_overlaps(shift.date, shift.start_time, shift.end_time, exclude_shift_pk=shift.pk)
        shift.save()

        return JsonResponse({
            "ok": True,
            "shift": _shift_to_dict(shift),
            "overlaps": overlaps,
        })

    def delete(self, request, pk):
        """Delete a planned shift."""
        shift = get_object_or_404(PlannedShift, pk=pk, status=PlannedShift.Status.PLANNED)
        shift.delete()
        return JsonResponse({"ok": True})


class BulkDeleteShiftsView(View):
    """Delete all planned shifts for a workplace within a payroll period."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        workplace_id = data.get("workplace_id")
        period_start = data.get("period_start")
        period_end = data.get("period_end")

        if not all([workplace_id, period_start, period_end]):
            return JsonResponse({"ok": False, "error": "Missing required fields."}, status=400)

        shifts = PlannedShift.objects.filter(
            workplace_id=int(workplace_id),
            status=PlannedShift.Status.PLANNED,
            date__gte=date.fromisoformat(period_start),
            date__lte=date.fromisoformat(period_end),
        )
        count = shifts.count()
        shifts.delete()
        return JsonResponse({"ok": True, "deleted": count})


class DefaultShiftAPIView(View):
    """Return default shift config from the active ContractTermSet."""

    def get(self, request, pk):
        wp = get_object_or_404(Workplace, pk=pk)
        terms = wp.active_termset_on(date.today())
        if terms is None:
            return JsonResponse({"default_start": "", "default_end": "", "default_break": 0, "default_type": "on_site"})
        return JsonResponse({
            "default_start": terms.default_shift_start_time.strftime("%H:%M") if terms.default_shift_start_time else "",
            "default_end": terms.default_shift_end_time.strftime("%H:%M") if terms.default_shift_end_time else "",
            "default_break": terms.default_shift_break_minutes,
            "default_type": terms.default_shift_type,
        })

    def post(self, request, pk):
        wp = get_object_or_404(Workplace, pk=pk)
        terms = wp.active_termset_on(date.today())
        if terms is None:
            return JsonResponse({"ok": False, "error": "No active contract."}, status=400)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        start = data.get("start_time", "")
        end = data.get("end_time", "")
        terms.default_shift_start_time = time.fromisoformat(start) if start else None
        terms.default_shift_end_time = time.fromisoformat(end) if end else None
        terms.default_shift_break_minutes = int(data.get("break_minutes", 0) or 0)
        terms.default_shift_type = data.get("shift_type", "on_site") or "on_site"
        terms.save(update_fields=["default_shift_start_time", "default_shift_end_time", "default_shift_break_minutes", "default_shift_type"])
        return JsonResponse({"ok": True})


class CheckOverlapsAPIView(View):
    """GET endpoint for live overlap checking from the shift modal."""

    def get(self, request):
        date_str = request.GET.get("date")
        start_str = request.GET.get("start")
        end_str = request.GET.get("end")
        exclude_pk = request.GET.get("exclude")

        if not all([date_str, start_str, end_str]):
            return JsonResponse({"overlaps": []})

        try:
            d = date.fromisoformat(date_str)
            s = time.fromisoformat(start_str)
            e = time.fromisoformat(end_str)
        except ValueError:
            return JsonResponse({"overlaps": []})

        exclude = int(exclude_pk) if exclude_pk else None
        exclude_session_pk = request.GET.get("exclude_session")
        exclude_session = int(exclude_session_pk) if exclude_session_pk else None
        overlaps = _check_overlaps(d, s, e, exclude_shift_pk=exclude, exclude_session_pk=exclude_session)
        return JsonResponse({"overlaps": overlaps})


class ApproveShiftsView(View):
    """List and approve planned shifts for a workplace."""

    def get(self, request, workplace_id):
        workplace = get_object_or_404(Workplace, pk=workplace_id)
        today = date.today()

        # Show planned shifts up to and including today (past + today)
        shifts = PlannedShift.objects.filter(
            workplace=workplace,
            status=PlannedShift.Status.PLANNED,
            date__lte=today,
        ).order_by("date", "start_time")

        initials, color = avatar_for_name(workplace.name)

        return render(
            request,
            "calendar_view/approve_shifts.html",
            {
                "workplace": workplace,
                "shifts": shifts,
                "avatar_initials": initials,
                "avatar_color": color,
            },
        )

    def post(self, request, workplace_id):
        """Approve selected shifts (convert to Shifts). Supports both form POST and JSON."""
        workplace = get_object_or_404(Workplace, pk=workplace_id)

        # JSON request from modal
        if request.content_type == "application/json":
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

            shift_ids = data.get("shift_ids", [])
            edits = {str(e["id"]): e for e in data.get("edits", [])}

            approved_count = 0
            for sid in shift_ids:
                try:
                    shift = PlannedShift.objects.get(
                        pk=int(sid),
                        workplace=workplace,
                        status=PlannedShift.Status.PLANNED,
                    )
                    # Apply inline edits if provided
                    edit = edits.get(str(sid))
                    if edit:
                        if "start_time" in edit:
                            shift.start_time = time.fromisoformat(edit["start_time"])
                        if "end_time" in edit:
                            shift.end_time = time.fromisoformat(edit["end_time"])
                        if "shift_type" in edit:
                            shift.shift_type = edit["shift_type"]
                        shift.save()
                    shift.approve()
                    approved_count += 1
                except PlannedShift.DoesNotExist:
                    continue

            return JsonResponse({"ok": True, "approved_count": approved_count})

        # Traditional form POST (fallback)
        shift_ids = request.POST.getlist("shift_ids")

        approved_count = 0
        for sid in shift_ids:
            try:
                shift = PlannedShift.objects.get(
                    pk=int(sid),
                    workplace=workplace,
                    status=PlannedShift.Status.PLANNED,
                )
                shift.approve()
                approved_count += 1
            except PlannedShift.DoesNotExist:
                continue

        from django.contrib import messages
        messages.success(request, f"{approved_count} shift(s) approved and converted to work sessions.")
        from django.shortcuts import redirect
        from workplaces.models import Workplace
        workplace = get_object_or_404(Workplace, pk=workplace_id)
        return redirect("workplaces:workplace-detail", slug=workplace.slug)


class BulkApproveShiftsView(View):
    """Approve planned shifts across all workplaces (JSON API for dashboard)."""

    def post(self, request):
        if request.content_type != "application/json":
            return JsonResponse({"ok": False, "error": "JSON required."}, status=400)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        shift_ids = data.get("shift_ids", [])
        edits = {str(e["id"]): e for e in data.get("edits", [])}

        approved_count = 0
        for sid in shift_ids:
            try:
                shift = PlannedShift.objects.get(
                    pk=int(sid),
                    status=PlannedShift.Status.PLANNED,
                )
                edit = edits.get(str(sid))
                if edit:
                    if "start_time" in edit:
                        shift.start_time = time.fromisoformat(edit["start_time"])
                    if "end_time" in edit:
                        shift.end_time = time.fromisoformat(edit["end_time"])
                    if "shift_type" in edit:
                        shift.shift_type = edit["shift_type"]
                    shift.save()
                shift.approve()
                approved_count += 1
            except PlannedShift.DoesNotExist:
                continue

        return JsonResponse({"ok": True, "approved_count": approved_count})


def _check_overlaps(shift_date, start_time, end_time, exclude_shift_pk=None, exclude_session_pk=None):
    """Check if a planned shift overlaps with existing sessions or other planned shifts."""
    overlaps = []

    # Check against work sessions
    sessions = Shift.objects.filter(date=shift_date)
    if exclude_session_pk:
        sessions = sessions.exclude(pk=exclude_session_pk)
    for s in sessions:
        if start_time < s.end_time and end_time > s.start_time:
            overlaps.append({
                "type": "session",
                "workplace": s.workplace.name,
                "start": s.start_time.strftime("%H:%M"),
                "end": s.end_time.strftime("%H:%M"),
            })

    # Check against other planned shifts
    planned = PlannedShift.objects.filter(
        date=shift_date,
        status=PlannedShift.Status.PLANNED,
    )
    if exclude_shift_pk:
        planned = planned.exclude(pk=exclude_shift_pk)
    for p in planned:
        if start_time < p.end_time and end_time > p.start_time:
            overlaps.append({
                "type": "planned",
                "workplace": p.workplace.name,
                "start": p.start_time.strftime("%H:%M"),
                "end": p.end_time.strftime("%H:%M"),
            })

    return overlaps


def _shift_to_dict(shift):
    """Serialize a PlannedShift to a JSON-safe dict."""
    return {
        "id": shift.pk,
        "workplace_id": shift.workplace_id,
        "workplace_name": shift.workplace.name,
        "date": shift.date.isoformat(),
        "start_time": shift.start_time.strftime("%H:%M"),
        "end_time": shift.end_time.strftime("%H:%M"),
        "break_minutes": shift.break_minutes,
        "shift_type": shift.shift_type,
        "shift_type_display": shift.get_shift_type_display(),
        "notes": shift.notes,
        "net_hours": str(shift.net_hours.quantize(Decimal("0.01"))),
        "gross_minutes": shift.gross_minutes,
        "net_minutes": shift.net_minutes,
    }


def _approved_shift_to_dict(session):
    """Serialize a Shift to a JSON-safe dict."""
    return {
        "id": session.pk,
        "workplace_id": session.workplace_id,
        "workplace_name": session.workplace.name,
        "date": session.date.isoformat(),
        "start_time": session.start_time.strftime("%H:%M"),
        "end_time": session.end_time.strftime("%H:%M"),
        "break_minutes": session.break_minutes,
        "shift_type": session.shift_type,
        "shift_type_display": session.get_shift_type_display(),
        "notes": session.notes,
        "net_hours": str(session.net_hours.quantize(Decimal("0.01"))),
        "gross_minutes": session.gross_minutes,
        "net_minutes": session.net_minutes,
    }


class ApprovedShiftUpdateAPIView(View):
    """GET/POST/DELETE API for editing work sessions from the planning view."""

    def get(self, request, pk):
        session = get_object_or_404(Shift, pk=pk)
        return JsonResponse({"ok": True, "shift": _approved_shift_to_dict(session)})

    def post(self, request, pk):
        session = get_object_or_404(Shift, pk=pk)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        if "date" in data:
            session.date = date.fromisoformat(data["date"])
        if "start_time" in data:
            session.start_time = time.fromisoformat(data["start_time"])
        if "end_time" in data:
            session.end_time = time.fromisoformat(data["end_time"])
        if "break_minutes" in data:
            session.break_minutes = int(data["break_minutes"])
        if "shift_type" in data:
            session.shift_type = data["shift_type"]
        if "notes" in data:
            session.notes = data["notes"]

        if session.start_time >= session.end_time:
            return JsonResponse({"ok": False, "error": "End time must be after start time."}, status=400)

        overlaps = _check_overlaps(
            session.date, session.start_time, session.end_time,
            exclude_session_pk=session.pk,
        )
        session.save()

        return JsonResponse({
            "ok": True,
            "shift": _approved_shift_to_dict(session),
            "overlaps": overlaps,
        })

    def delete(self, request, pk):
        session = get_object_or_404(Shift, pk=pk)
        session.delete()
        return JsonResponse({"ok": True})




