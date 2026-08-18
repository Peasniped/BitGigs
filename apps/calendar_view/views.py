import json
from datetime import date, time
from decimal import Decimal

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.utils import timezone

from core.services import TaxCalculationService
from workplaces.models import Workplace
from workplaces.services import workplaces_active_in_period, hidden_workplace_count
from shifts.models import PlannedShift, Shift
from core.utils import (
    avatar_for_name, month_bounds, parse_int_param, parse_iso_date_param,
    parse_iso_time_param, prev_next_month,
)
from .services import CalendarService, approve_planned_shifts


def _valid_shift_type(value):
    """Guard for shift_type strings arriving via the JSON APIs — objects are
    saved without full_clean() here, so choice validation must happen by hand."""
    return value in Shift.ShiftType.values


class MonthCalendarView(View):
    """Standard month calendar view, optionally filtered by workplace."""

    def get(self, request):
        year = parse_int_param(request.GET.get("year"), timezone.localdate().year)
        month = parse_int_param(request.GET.get("month"), timezone.localdate().month)
        workplace_id = parse_int_param(request.GET.get("workplace"))

        grid = CalendarService.month_calendar(year, month, workplace_id)
        grid.annotate_overlaps()

        # Navigation
        prev_year, prev_month, next_year, next_month = prev_next_month(year, month)

        workplaces = workplaces_active_in_period(*month_bounds(year, month))

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
                "hidden_workplace_count": hidden_workplace_count(workplaces.count()),
            },
        )


class PayrollPeriodCalendarView(View):
    """Calendar view aligned to a payroll period for a specific workplace."""

    def get(self, request):
        year = parse_int_param(request.GET.get("year"), timezone.localdate().year)
        month = parse_int_param(request.GET.get("month"), timezone.localdate().month)
        workplace_id = parse_int_param(request.GET.get("workplace"), 0)

        if not workplace_id:
            # If no workplace selected, show workplace picker
            workplaces = workplaces_active_in_period(*month_bounds(year, month))
            return render(
                request,
                "calendar_view/payroll_period_select.html",
                {"workplaces": workplaces, "year": year, "month": month},
            )

        grid = CalendarService.payroll_period_calendar(workplace_id, year, month)
        grid.annotate_overlaps()

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
        from calendar_sync.models import (
            CalendarInviteSettings, CalendarSubscription, ShiftInvite,
        )
        from calendar_sync import services as calendar_sync_services
        from core.models import EmailSettings
        from decimal import Decimal

        today = timezone.localdate()
        year = parse_int_param(request.GET.get("year"), today.year)
        month = parse_int_param(request.GET.get("month"), today.month)

        grid = CalendarService.planning_calendar(year, month)
        has_overlaps = grid.annotate_overlaps()

        workplaces = list(
            workplaces_active_in_period(*month_bounds(year, month))
            .prefetch_related("contracts")
        )

        # Direction 2: flag each shift chip whose invite is active, and decide
        # whether to offer the "Send invites" button at all.
        grid_shifts = [
            s for week in grid.weeks for day in week.days for s in day.sorted_shifts
        ]
        wanted = {s.invite_uid for s in grid_shifts if getattr(s, "invite_uid", None)}
        # uid → the active invite, so staleness costs no extra query per chip.
        active_invites = {
            inv.invite_uid: inv
            for inv in ShiftInvite.objects.filter(
                invite_uid__in=wanted, status=ShiftInvite.STATUS_ACTIVE
            )
        } if wanted else {}
        from calendar_sync import invites as _invites

        # Offer the button only when a send could actually reach somebody. Armed
        # contracts alone aren't enough: with their work address off and the
        # personal copy off, invites are switched on at nobody, and the button
        # could only ever report "nothing to send". Mail is checked for the
        # **calendar role**, matching what `eligible()` requires — the generic
        # flag let the button appear while every shift was ineligible.
        can_send_invites = (
            CalendarInviteSettings.load().enabled
            and EmailSettings.load().is_configured_for(EmailSettings.ROLE_CALENDAR)
            and _invites.any_sendable_contract()
        )

        invite_settings = CalendarInviteSettings.load()
        for s in grid_shifts:
            invite = active_invites.get(getattr(s, "invite_uid", None))
            s.has_active_invite = invite is not None
            # Chip marker: the invite is out for a version of this shift that no
            # longer matches it (see invites.event_fingerprint).
            s.invite_stale = invite is not None and _invites.is_stale(
                s, invite=invite, settings=invite_settings
            )
            # The harder marker: the send was rejected, so this shift's invite is
            # not merely out of date — it never reached anyone.
            s.invite_failed = invite is not None and invite.send_failed

        # Data-driven "Send invites" button: how many planned shifts the button
        # would actually act on. Zero → it reads "All invites sent" (disabled)
        # instead of offering a send that would do nothing.
        #
        # Asks SendInvitesView's own planner rather than re-deriving the scope
        # here — counting the *grid* (padded to whole weeks and to the union of
        # every workplace's period) is what left the button reading "Send invites"
        # after everything in scope had gone out.
        invite_pending_count = (
            sum(g.total for g in _invites.month_sweep(year, month))
            if can_send_invites else 0
        )

        # Navigation
        prev_year, prev_month, next_year, next_month = prev_next_month(year, month)

        # Build workplace data with avatars, default shifts, payroll periods, monthly hours
        workplace_data = []
        for wp in workplaces:
            initials, color = avatar_for_name(wp.name)
            terms, period_start, period_end = PayrollPeriodService.resolve_period_bounds(
                wp, year, month
            )

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

            # Active date ranges (per term set) for client-side drop bounds in
            # the grid. Uses each term set's active window so gaps between term
            # sets are excluded — a gap day is not a valid drop target.
            contract_intervals = [
                {
                    "start": start.isoformat(),
                    "end": end.isoformat() if end else "",
                }
                for c in wp.contracts.prefetch_related("term_sets")
                for start, end in c.active_intervals()
            ]

            workplace_data.append({
                "id": wp.pk,
                "name": wp.name,
                "icon": wp.icon,
                "custom_icon_url": wp.custom_icon.url if wp.custom_icon else "",
                "color": wp.color or color,
                "accent_color": wp.accent_color or "",
                "initials": initials,
                "contract_intervals": contract_intervals,
                "default_start": wp.default_shift_start_time.strftime("%H:%M") if wp.default_shift_start_time else "",
                "default_end": wp.default_shift_end_time.strftime("%H:%M") if wp.default_shift_end_time else "",
                "default_break": wp.default_shift_break_minutes,
                "default_type": wp.default_shift_type,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "planned_hours": str(planned_hours),
                "approved_hours": str(approved_hours),
                "total_hours": str(planned_hours + approved_hours),
                "hour_goal_type": terms.hour_goal_type if terms else "",
                "hour_goal_min": str(terms.hour_goal_min) if terms and terms.hour_goal_min else "",
                "hour_goal_max": str(terms.hour_goal_max) if terms and terms.hour_goal_max else "",
            })

        import calendar as _cal

        # Month names for JS warning messages (rendered via json_script)
        month_names = {str(i): _cal.month_name[i] for i in range(1, 13)}

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
                "hidden_workplace_count": hidden_workplace_count(len(workplaces)),
                "workplace_json": workplace_data,
                "month_names_json": month_names,
                "today": today,
                "has_overlaps": has_overlaps,
                # Direction 1 overlay: offer the "Show my calendar(s)" toggle
                # whenever at least one subscription *exists* (even if all are
                # currently disabled — the per-calendar sliders let you turn one
                # back on right here). The enabled count drives the singular/plural
                # wording of the button and legend.
                "calendar_subscription_count": CalendarSubscription.objects.enabled().count(),
                "has_calendar_subscriptions": CalendarSubscription.objects.exists(),
                # Per-calendar sliders that uncollapse under the button: id / label
                # / colour / enabled for every subscription, toggled permanently via
                # calendar_sync:subscription-toggle.
                "calendar_subscriptions": [
                    {"id": s.pk, "label": s.label, "color": s.color, "enabled": s.enabled}
                    for s in CalendarSubscription.objects.all()
                ],
                # Fingerprint of the overlay's colour/enabled state: the client
                # discards its session-cached chips and re-fetches when it changes,
                # so a calendar colour edit shows without a manual re-pull.
                "busy_config_token": calendar_sync_services.busy_config_token(),
                # Direction 2: offer the "Send invites" button when invites are on;
                # its label/state is driven by how many shown shifts still need one.
                "can_send_invites": can_send_invites,
                "invite_pending_count": invite_pending_count,
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
        break_minutes = parse_int_param(data.get("break_minutes"), 0)
        shift_type = data.get("shift_type", "on_site")
        notes = data.get("notes", "")

        if not all([workplace_id, shift_date, start_time_str, end_time_str]):
            return JsonResponse({"ok": False, "error": "Missing required fields."}, status=400)
        if not _valid_shift_type(shift_type):
            return JsonResponse({"ok": False, "error": "Unknown shift type."}, status=400)

        workplace = get_object_or_404(Workplace, pk=workplace_id)
        parsed_date = parse_iso_date_param(shift_date)
        start_time = parse_iso_time_param(start_time_str)
        end_time = parse_iso_time_param(end_time_str)
        if parsed_date is None or start_time is None or end_time is None:
            return JsonResponse({"ok": False, "error": "Invalid date or time."}, status=400)

        if start_time >= end_time:
            return JsonResponse({"ok": False, "error": "End time must be after start time."}, status=400)

        if workplace.active_contract_on(parsed_date) is None:
            return JsonResponse({
                "ok": False,
                "error": f"{workplace.name} has no active contract on {parsed_date}. "
                         "Add or adjust a contract to cover this date.",
            }, status=400)

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
    """Read, update, or delete a planned shift."""

    def get(self, request, pk):
        """Return a planned shift's data (used when copying — no validation)."""
        shift = get_object_or_404(PlannedShift, pk=pk, status=PlannedShift.Status.PLANNED)
        return JsonResponse({"ok": True, "shift": _shift_to_dict(shift)})

    def post(self, request, pk):
        """Update a planned shift."""
        shift = get_object_or_404(PlannedShift, pk=pk, status=PlannedShift.Status.PLANNED)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        if "date" in data:
            shift.date = parse_iso_date_param(data["date"])
        if "start_time" in data:
            shift.start_time = parse_iso_time_param(data["start_time"])
        if "end_time" in data:
            shift.end_time = parse_iso_time_param(data["end_time"])
        if "break_minutes" in data:
            shift.break_minutes = parse_int_param(data["break_minutes"], 0)
        if "shift_type" in data:
            if not _valid_shift_type(data["shift_type"]):
                return JsonResponse({"ok": False, "error": "Unknown shift type."}, status=400)
            shift.shift_type = data["shift_type"]
        if "notes" in data:
            shift.notes = data["notes"]
        if "arrival_confirmed" in data:
            shift.arrival_confirmed = bool(data["arrival_confirmed"])

        if shift.date is None or shift.start_time is None or shift.end_time is None:
            return JsonResponse({"ok": False, "error": "Invalid date or time."}, status=400)

        if shift.start_time >= shift.end_time:
            return JsonResponse({"ok": False, "error": "End time must be after start time."}, status=400)

        if shift.workplace.active_contract_on(shift.date) is None:
            return JsonResponse({
                "ok": False,
                "error": f"{shift.workplace.name} has no active contract on {shift.date}. "
                         "Add or adjust a contract to cover this date.",
            }, status=400)

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
    """Delete all planned shifts — either for a workplace/period or for a single date."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        # Date-only deletion: remove all planned shifts across all workplaces on one day
        if data.get("date") and not data.get("workplace_id"):
            try:
                target_date = date.fromisoformat(data["date"])
            except ValueError:
                return JsonResponse({"ok": False, "error": "Invalid date."}, status=400)
            shifts = PlannedShift.objects.filter(
                date=target_date,
                status=PlannedShift.Status.PLANNED,
            )
            count = shifts.count()
            shifts.delete()
            return JsonResponse({"ok": True, "deleted": count})

        # Workplace/period deletion (original behaviour)
        workplace_id = parse_int_param(data.get("workplace_id"))
        period_start = parse_iso_date_param(data.get("period_start"))
        period_end = parse_iso_date_param(data.get("period_end"))

        if workplace_id is None or period_start is None or period_end is None:
            return JsonResponse({"ok": False, "error": "Missing or invalid fields."}, status=400)

        shifts = PlannedShift.objects.filter(
            workplace_id=workplace_id,
            status=PlannedShift.Status.PLANNED,
            date__gte=period_start,
            date__lte=period_end,
        )
        count = shifts.count()
        shifts.delete()
        return JsonResponse({"ok": True, "deleted": count})


class DefaultShiftAPIView(View):
    """Return / store the workplace's default shift config (planning convenience)."""

    def get(self, request, pk):
        wp = get_object_or_404(Workplace, pk=pk)
        return JsonResponse({
            "default_start": wp.default_shift_start_time.strftime("%H:%M") if wp.default_shift_start_time else "",
            "default_end": wp.default_shift_end_time.strftime("%H:%M") if wp.default_shift_end_time else "",
            "default_break": wp.default_shift_break_minutes,
            "default_type": wp.default_shift_type,
        })

    def post(self, request, pk):
        wp = get_object_or_404(Workplace, pk=pk)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        start = data.get("start_time", "")
        end = data.get("end_time", "")
        if (start and parse_iso_time_param(start) is None) or (end and parse_iso_time_param(end) is None):
            return JsonResponse({"ok": False, "error": "Invalid time."}, status=400)
        shift_type = data.get("shift_type", "on_site") or "on_site"
        if not _valid_shift_type(shift_type):
            return JsonResponse({"ok": False, "error": "Unknown shift type."}, status=400)
        wp.default_shift_start_time = parse_iso_time_param(start) if start else None
        wp.default_shift_end_time = parse_iso_time_param(end) if end else None
        wp.default_shift_break_minutes = parse_int_param(data.get("break_minutes"), 0) or 0
        wp.default_shift_type = shift_type
        wp.save(update_fields=["default_shift_start_time", "default_shift_end_time", "default_shift_break_minutes", "default_shift_type"])
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

        exclude = parse_int_param(exclude_pk)
        exclude_session_pk = request.GET.get("exclude_session")
        exclude_session = parse_int_param(exclude_session_pk)
        overlaps = _check_overlaps(d, s, e, exclude_shift_pk=exclude, exclude_session_pk=exclude_session)
        return JsonResponse({"overlaps": overlaps})


class ApproveShiftsView(View):
    """List and approve planned shifts for a workplace."""

    def get(self, request, workplace_id):
        workplace = get_object_or_404(Workplace, pk=workplace_id)
        today = timezone.localdate()

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

            approved_count, uncovered_dates = approve_planned_shifts(
                shift_ids, edits=edits, workplace=workplace
            )

            if uncovered_dates:
                messages.warning(request, TaxCalculationService.coverage_warning(min(uncovered_dates)))

            return JsonResponse({"ok": True, "approved_count": approved_count})

        # Traditional form POST (fallback)
        shift_ids = request.POST.getlist("shift_ids")

        approved_count, uncovered_dates = approve_planned_shifts(
            shift_ids, workplace=workplace
        )

        messages.success(request, f"{approved_count} shift(s) approved.")
        if uncovered_dates:
            messages.warning(request, TaxCalculationService.coverage_warning(min(uncovered_dates)))
        from django.shortcuts import redirect
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

        approved_count, uncovered_dates = approve_planned_shifts(shift_ids, edits=edits)

        if uncovered_dates:
            messages.warning(request, TaxCalculationService.coverage_warning(min(uncovered_dates)))

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
    """Serialize a PlannedShift or Shift to a JSON-safe dict (both share
    ShiftTimeMixin, so the fields are identical)."""
    return {
        "id": shift.pk,
        "workplace_id": shift.workplace_id,
        "workplace_name": shift.workplace.name,
        "workplace_color": shift.workplace.avatar_color,
        "workplace_initials": shift.workplace.avatar_initials,
        "workplace_icon": shift.workplace.icon,
        "workplace_accent_color": shift.workplace.accent_color or "",
        "workplace_custom_icon_url": shift.workplace.custom_icon.url if shift.workplace.custom_icon else "",
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
        # Direction 2: drives the edit modal's Send / Re-send invite control
        # (shown only for planned shifts). Cheap per-shift resolution.
        **_shift_invite_flags(shift),
    }


def _shift_invite_flags(shift):
    """``has_active_invite`` / ``invite_eligible`` / ``invite_stale`` for the
    edit-shift modal's invite control. Resolved per shift (planning is not a hot
    path).

    ``invite_stale`` is what drives the re-send prompt after a save: the shift
    changed in a way the already-sent invite doesn't reflect. ``invite_failed``
    is the harder state — the send was *rejected*, so nobody holds anything.
    """
    from calendar_sync import invites
    from calendar_sync.models import CalendarInviteSettings, ShiftInvite

    uid = getattr(shift, "invite_uid", None)
    invite = ShiftInvite.objects.filter(
        invite_uid=uid, status=ShiftInvite.STATUS_ACTIVE
    ).first() if uid else None
    return {
        "has_active_invite": invite is not None,
        "invite_eligible": invites.eligible(shift),
        # Past shifts are out of scope — the modal hides the control even if a
        # stale active invite lingers (see planning.js setupInviteBlock).
        "invite_past": invites._is_past(shift),
        "invite_stale": (
            invites.is_stale(shift, invite=invite) if invite is not None else False
        ),
        "invite_failed": invite is not None and invite.send_failed,
        "invite_error": invite.send_error if invite is not None else "",
        # A failed *first* send means nobody holds anything — the retry is a
        # first send, not an update, and the wording follows.
        "invite_delivered": invite is not None and invite.ever_delivered,
        # Named in the re-send prompt, so it says who is about to be mailed.
        "invite_recipients": invites.recipients_for(shift) if invite is not None else [],
        # Whether the owner wants asking at all (Settings → Calendar). The prompt
        # is client-side, so the answer has to travel with the shift; off means
        # the edit lands silently and the out-of-date marker carries it instead.
        "invite_ask": CalendarInviteSettings.load().ask_before_resend,
    }


class ApprovedShiftUpdateAPIView(View):
    """GET/POST/DELETE API for editing work sessions from the planning view."""

    def get(self, request, pk):
        session = get_object_or_404(Shift, pk=pk)
        return JsonResponse({"ok": True, "shift": _shift_to_dict(session)})

    def post(self, request, pk):
        session = get_object_or_404(Shift, pk=pk)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

        if "date" in data:
            session.date = parse_iso_date_param(data["date"])
        if "start_time" in data:
            session.start_time = parse_iso_time_param(data["start_time"])
        if "end_time" in data:
            session.end_time = parse_iso_time_param(data["end_time"])
        if "break_minutes" in data:
            session.break_minutes = parse_int_param(data["break_minutes"], 0)
        if "shift_type" in data:
            if not _valid_shift_type(data["shift_type"]):
                return JsonResponse({"ok": False, "error": "Unknown shift type."}, status=400)
            session.shift_type = data["shift_type"]
        if "notes" in data:
            session.notes = data["notes"]

        if session.date is None or session.start_time is None or session.end_time is None:
            return JsonResponse({"ok": False, "error": "Invalid date or time."}, status=400)

        if session.start_time >= session.end_time:
            return JsonResponse({"ok": False, "error": "End time must be after start time."}, status=400)

        if session.workplace.active_contract_on(session.date) is None:
            return JsonResponse({
                "ok": False,
                "error": f"{session.workplace.name} has no active contract on {session.date}. "
                         "Add or adjust a contract to cover this date.",
            }, status=400)

        overlaps = _check_overlaps(
            session.date, session.start_time, session.end_time,
            exclude_session_pk=session.pk,
        )
        session.save()

        return JsonResponse({
            "ok": True,
            "shift": _shift_to_dict(session),
            "overlaps": overlaps,
        })

    def delete(self, request, pk):
        session = get_object_or_404(Shift, pk=pk)
        session.delete()
        return JsonResponse({"ok": True})




