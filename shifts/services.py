"""
Services for summarising shifts.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .models import Shift


TWO_PLACES = Decimal("0.01")


@dataclass
class DailySummary:
    date: date
    workplace_name: str
    workplace_id: int
    total_hours: Decimal
    shift_count: int
    shifts: list


@dataclass
class MonthlySummary:
    year: int
    month: int
    workplace_name: str
    workplace_id: int
    total_hours: Decimal
    working_days: int
    on_site_hours: Decimal
    remote_hours: Decimal
    sick_hours: Decimal
    vacation_hours: Decimal
    paid_absence_hours: Decimal


class ShiftSummaryService:
    """Aggregate shift data for daily and monthly views."""

    @staticmethod
    def daily_summary(target_date: date, workplace_id: int | None = None) -> list[DailySummary]:
        """Return per-workplace summaries for a specific date."""
        qs = Shift.objects.filter(date=target_date).select_related("workplace")
        if workplace_id:
            qs = qs.filter(workplace_id=workplace_id)

        by_workplace = defaultdict(list)
        for shift in qs:
            by_workplace[shift.workplace_id].append(shift)

        summaries = []
        for wp_id, shifts in by_workplace.items():
            total = sum(s.net_hours for s in shifts)
            summaries.append(
                DailySummary(
                    date=target_date,
                    workplace_name=shifts[0].workplace.name,
                    workplace_id=wp_id,
                    total_hours=total.quantize(TWO_PLACES),
                    shift_count=len(shifts),
                    shifts=shifts,
                )
            )
        return summaries

    @staticmethod
    def monthly_summary(year: int, month: int, workplace_id: int | None = None) -> list[MonthlySummary]:
        """Return per-workplace summaries for a whole month."""
        qs = Shift.objects.filter(
            date__year=year, date__month=month
        ).select_related("workplace")
        if workplace_id:
            qs = qs.filter(workplace_id=workplace_id)

        by_workplace = defaultdict(list)
        for shift in qs:
            by_workplace[shift.workplace_id].append(shift)

        summaries = []
        for wp_id, shifts in by_workplace.items():
            type_hours = defaultdict(Decimal)
            dates_seen = set()
            for s in shifts:
                type_hours[s.shift_type] += s.net_hours
                dates_seen.add(s.date)

            total = sum(type_hours.values(), Decimal("0"))
            summaries.append(
                MonthlySummary(
                    year=year,
                    month=month,
                    workplace_name=shifts[0].workplace.name,
                    workplace_id=wp_id,
                    total_hours=total.quantize(TWO_PLACES),
                    working_days=len(dates_seen),
                    on_site_hours=type_hours.get(Shift.ShiftType.ON_SITE, Decimal("0")).quantize(TWO_PLACES),
                    remote_hours=type_hours.get(Shift.ShiftType.REMOTE, Decimal("0")).quantize(TWO_PLACES),
                    sick_hours=type_hours.get(Shift.ShiftType.SICK_LEAVE, Decimal("0")).quantize(TWO_PLACES),
                    vacation_hours=type_hours.get(Shift.ShiftType.VACATION, Decimal("0")).quantize(TWO_PLACES),
                    paid_absence_hours=type_hours.get(Shift.ShiftType.PAID_ABSENCE, Decimal("0")).quantize(TWO_PLACES),
                )
            )
        return summaries

    @staticmethod
    def period_summary(start_date: date, end_date: date, workplace_id: int) -> MonthlySummary:
        """Summarize shifts within an arbitrary date range for one workplace."""
        qs = Shift.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
            workplace_id=workplace_id,
        ).select_related("workplace")

        shifts = list(qs)
        type_hours = defaultdict(Decimal)
        dates_seen = set()
        wp_name = ""
        for s in shifts:
            type_hours[s.shift_type] += s.net_hours
            dates_seen.add(s.date)
            wp_name = s.workplace.name

        total = sum(type_hours.values(), Decimal("0"))
        return MonthlySummary(
            year=start_date.year,
            month=start_date.month,
            workplace_name=wp_name,
            workplace_id=workplace_id,
            total_hours=total.quantize(TWO_PLACES),
            working_days=len(dates_seen),
            on_site_hours=type_hours.get(Shift.ShiftType.ON_SITE, Decimal("0")).quantize(TWO_PLACES),
            remote_hours=type_hours.get(Shift.ShiftType.REMOTE, Decimal("0")).quantize(TWO_PLACES),
            sick_hours=type_hours.get(Shift.ShiftType.SICK_LEAVE, Decimal("0")).quantize(TWO_PLACES),
            vacation_hours=type_hours.get(Shift.ShiftType.VACATION, Decimal("0")).quantize(TWO_PLACES),
            paid_absence_hours=type_hours.get(Shift.ShiftType.PAID_ABSENCE, Decimal("0")).quantize(TWO_PLACES),
        )
