"""
Calendar service — generates grid data for month and payroll-period views.

The calendar always renders full weeks, even if the period starts/ends mid-week.
Supports Monday or Sunday as the configurable week start.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.models import UserSettings
from core.services import TaxCalculationService
from core.utils import parse_int_param, parse_iso_time_param
from shifts.models import Shift, PlannedShift


@dataclass
class CalendarDay:
    date: date
    is_in_period: bool  # Whether the day falls within the target period
    is_today: bool
    approved_shifts: list = field(default_factory=list)
    planned_shifts: list = field(default_factory=list)
    total_hours: Decimal = Decimal("0")

    @property
    def is_weekend(self):
        return self.date.weekday() >= 5

    @property
    def sorted_shifts(self):
        """Approved + planned shifts merged and ordered by start time.

        Each item is tagged with ``is_planned`` so the planning template can
        render both kinds from a single time-ordered container. References the
        same objects ``annotate_overlaps`` mutates, so ``.overlapping`` is kept.
        """
        for s in self.approved_shifts:
            s.is_planned = False
        for p in self.planned_shifts:
            p.is_planned = True
        return sorted(
            list(self.approved_shifts) + list(self.planned_shifts),
            key=lambda x: x.start_time,
        )


@dataclass
class CalendarWeek:
    days: list[CalendarDay] = field(default_factory=list)
    week_number: int = 0  # ISO 8601 week number for this row


@dataclass
class CalendarGrid:
    title: str
    period_start: date
    period_end: date
    weeks: list[CalendarWeek] = field(default_factory=list)
    day_headers: list[str] = field(default_factory=list)
    has_overlaps: bool = False

    def annotate_overlaps(self) -> bool:
        """Mark overlapping shift instances with .overlapping = True and set has_overlaps."""
        for week in self.weeks:
            for day in week.days:
                all_shifts = list(day.approved_shifts) + list(day.planned_shifts)
                overlapping_oids = set()
                for i, s1 in enumerate(all_shifts):
                    for s2 in all_shifts[i + 1:]:
                        if s1.start_time < s2.end_time and s2.start_time < s1.end_time:
                            overlapping_oids.add(id(s1))
                            overlapping_oids.add(id(s2))
                for s in all_shifts:
                    s.overlapping = id(s) in overlapping_oids
                if overlapping_oids:
                    self.has_overlaps = True
        return self.has_overlaps


class CalendarService:
    """Build calendar grids for rendering."""

    WEEKDAY_NAMES_MON = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    WEEKDAY_NAMES_SUN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    @staticmethod
    def get_week_start() -> int:
        """Return the configured week start day (0=Monday, 6=Sunday)."""
        settings = UserSettings.load()
        return settings.week_start

    @classmethod
    def _get_day_headers(cls, week_start: int) -> list[str]:
        if week_start == 6:
            return cls.WEEKDAY_NAMES_SUN
        return cls.WEEKDAY_NAMES_MON

    @staticmethod
    def _align_to_week_start(d: date, week_start: int) -> date:
        """Move a date backwards to the most recent week-start day."""
        if week_start == 0:  # Monday
            offset = d.weekday()
        else:  # Sunday (week_start == 6)
            offset = (d.weekday() + 1) % 7
        return d - timedelta(days=offset)

    @classmethod
    def _build_grid(
        cls,
        period_start: date,
        period_end: date,
        title: str,
        workplace_id: int | None = None,
        include_planned: bool = True,
    ) -> CalendarGrid:
        week_start = cls.get_week_start()
        day_headers = cls._get_day_headers(week_start)

        # Expand to full weeks
        grid_start = cls._align_to_week_start(period_start, week_start)
        grid_end = grid_start + timedelta(days=6)
        while grid_end < period_end:
            grid_end += timedelta(days=7)

        # Fetch shifts in the grid range
        qs = Shift.objects.filter(
            date__gte=grid_start, date__lte=grid_end
        ).select_related("workplace")
        if workplace_id:
            qs = qs.filter(workplace_id=workplace_id)

        shifts_by_date = defaultdict(list)
        for s in qs:
            shifts_by_date[s.date].append(s)

        # Fetch planned shifts (only those still in PLANNED status)
        planned_by_date = defaultdict(list)
        if include_planned:
            pqs = PlannedShift.objects.filter(
                date__gte=grid_start, date__lte=grid_end,
                status=PlannedShift.Status.PLANNED,
            ).select_related("workplace")
            if workplace_id:
                pqs = pqs.filter(workplace_id=workplace_id)
            for p in pqs:
                planned_by_date[p.date].append(p)

        today = timezone.localdate()
        weeks = []
        current = grid_start
        while current <= grid_end:
            week = CalendarWeek()
            for _ in range(7):
                day_shifts = shifts_by_date.get(current, [])
                day_planned = planned_by_date.get(current, [])
                total = sum((s.net_hours for s in day_shifts), Decimal("0"))
                total += sum((p.net_hours for p in day_planned), Decimal("0"))
                week.days.append(
                    CalendarDay(
                        date=current,
                        is_in_period=(period_start <= current <= period_end),
                        is_today=(current == today),
                        approved_shifts=day_shifts,
                        planned_shifts=day_planned,
                        total_hours=total,
                    )
                )
                current += timedelta(days=1)
            # ISO 8601 week number: defined by the Thursday of the week. Every
            # 7-day aligned row contains exactly one Thursday, so this is correct
            # regardless of the configured week start and across year boundaries.
            thursday = next(d for d in week.days if d.date.weekday() == 3)
            week.week_number = thursday.date.isocalendar()[1]
            weeks.append(week)

        return CalendarGrid(
            title=title,
            period_start=period_start,
            period_end=period_end,
            weeks=weeks,
            day_headers=day_headers,
        )

    @classmethod
    def month_calendar(
        cls,
        year: int,
        month: int,
        workplace_id: int | None = None,
    ) -> CalendarGrid:
        """Standard month calendar view."""
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        month_name = calendar.month_name[month]
        title = f"{month_name} {year}"

        return cls._build_grid(first_day, last_day, title, workplace_id)

    @classmethod
    def payroll_period_calendar(
        cls,
        workplace_id: int,
        year: int,
        month: int,
    ) -> CalendarGrid:
        """
        Calendar for a payroll period (which may span two months).
        Always renders full weeks.
        """
        from workplaces.models import Workplace
        from payroll.services import PayrollPeriodService

        workplace = Workplace.objects.get(pk=workplace_id)
        _terms, start_date, end_date = PayrollPeriodService.resolve_period_bounds(
            workplace, year, month
        )
        month_name = calendar.month_name[month]
        title = f"{month_name} ({start_date} to {end_date})"

        return cls._build_grid(start_date, end_date, title, workplace_id)

    @classmethod
    def planning_calendar(
        cls,
        year: int,
        month: int,
    ) -> CalendarGrid:
        """
        Planning calendar that shows the union of all active workplace payroll
        periods for the selected month.  This ensures that every date belonging
        to *any* workplace's period is visible.
        """
        from workplaces.services import workplaces_active_in_period
        from payroll.services import PayrollPeriodService

        # Start with the calendar month as the baseline range
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])
        workplaces = workplaces_active_in_period(first_day, last_day)
        range_start = first_day
        range_end = last_day

        # Expand to cover every workplace's payroll period for this month
        for wp in workplaces:
            terms = wp.active_termset_on(first_day)
            if terms is not None:
                ps, pe = PayrollPeriodService.get_period_dates(terms, year, month)
            else:
                ps, pe = first_day, last_day
            if ps < range_start:
                range_start = ps
            if pe > range_end:
                range_end = pe

        month_name = calendar.month_name[month]
        title = f"{month_name} {year}"

        return cls._build_grid(range_start, range_end, title)


@transaction.atomic
def approve_planned_shifts(shift_ids, edits=None, workplace=None):
    """Approve planned shifts, optionally applying inline edits.

    ``edits`` maps a string shift id to a dict that may contain ``start_time``,
    ``end_time``, ``break_minutes`` and/or ``shift_type``. When ``workplace`` is
    given, only that workplace's shifts are eligible. Returns
    ``(approved_count, uncovered_dates)``.
    """
    edits = edits or {}
    lookup = {"status": PlannedShift.Status.PLANNED}
    if workplace is not None:
        lookup["workplace"] = workplace

    approved_count = 0
    uncovered_dates = []
    for sid in shift_ids:
        try:
            shift = PlannedShift.objects.get(pk=int(sid), **lookup)
        except (PlannedShift.DoesNotExist, TypeError, ValueError):
            continue
        edit = edits.get(str(sid))
        if edit:
            # Unparseable/unknown values keep the stored ones — the inline edit
            # UI can only produce valid input, so anything else is noise.
            if "start_time" in edit:
                shift.start_time = parse_iso_time_param(edit["start_time"]) or shift.start_time
            if "end_time" in edit:
                shift.end_time = parse_iso_time_param(edit["end_time"]) or shift.end_time
            if "break_minutes" in edit:
                shift.break_minutes = parse_int_param(edit["break_minutes"], shift.break_minutes)
            if "shift_type" in edit and edit["shift_type"] in Shift.ShiftType.values:
                shift.shift_type = edit["shift_type"]
            shift.save()
        shift.approve()
        if TaxCalculationService.coverage_warning(shift.date):
            uncovered_dates.append(shift.date)
        approved_count += 1
    return approved_count, uncovered_dates
