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

from core.models import UserSettings
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


@dataclass
class CalendarWeek:
    days: list[CalendarDay] = field(default_factory=list)


@dataclass
class CalendarGrid:
    title: str
    period_start: date
    period_end: date
    weeks: list[CalendarWeek] = field(default_factory=list)
    day_headers: list[str] = field(default_factory=list)


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

    @staticmethod
    def _align_to_week_end(d: date, week_start: int) -> date:
        """Move a date forward to the end of its week."""
        if week_start == 0:
            offset = 6 - d.weekday()
        else:
            offset = (6 - (d.weekday() + 1) % 7) % 7
            if offset == 0 and d.weekday() != 5:
                offset = 0
            offset = (5 - d.weekday()) % 7  # Saturday for Sunday-start
        # Simpler: just go to start of next week minus 1
        start = CalendarService._align_to_week_start(d, week_start)
        return start + timedelta(days=6)

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

        today = date.today()
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
        from datetime import date as _date
        from workplaces.models import Workplace
        from payroll.services import PayrollPeriodService

        workplace = Workplace.objects.get(pk=workplace_id)
        terms = workplace.active_termset_on(_date(year, month, 15))
        if terms is not None:
            start_date, end_date = PayrollPeriodService.get_period_dates(terms, year, month)
        else:
            last_day = calendar.monthrange(year, month)[1]
            start_date = _date(year, month, 1)
            end_date = _date(year, month, last_day)
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
        from workplaces.models import Workplace
        from payroll.services import PayrollPeriodService

        workplaces = Workplace.objects.filter(is_active=True)

        # Start with the calendar month as the baseline range
        first_day = date(year, month, 1)
        last_day = date(year, month, calendar.monthrange(year, month)[1])
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
