"""
Services for summarising work sessions.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .models import WorkSession


TWO_PLACES = Decimal("0.01")


@dataclass
class DailySummary:
    date: date
    workplace_name: str
    workplace_id: int
    total_hours: Decimal
    session_count: int
    sessions: list


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


class SessionSummaryService:
    """Aggregate work session data for daily and monthly views."""

    @staticmethod
    def daily_summary(target_date: date, workplace_id: int | None = None) -> list[DailySummary]:
        """Return per-workplace summaries for a specific date."""
        qs = WorkSession.objects.filter(date=target_date).select_related("workplace")
        if workplace_id:
            qs = qs.filter(workplace_id=workplace_id)

        by_workplace = defaultdict(list)
        for session in qs:
            by_workplace[session.workplace_id].append(session)

        summaries = []
        for wp_id, sessions in by_workplace.items():
            total = sum(s.net_hours for s in sessions)
            summaries.append(
                DailySummary(
                    date=target_date,
                    workplace_name=sessions[0].workplace.name,
                    workplace_id=wp_id,
                    total_hours=total.quantize(TWO_PLACES),
                    session_count=len(sessions),
                    sessions=sessions,
                )
            )
        return summaries

    @staticmethod
    def monthly_summary(year: int, month: int, workplace_id: int | None = None) -> list[MonthlySummary]:
        """Return per-workplace summaries for a whole month."""
        qs = WorkSession.objects.filter(
            date__year=year, date__month=month
        ).select_related("workplace")
        if workplace_id:
            qs = qs.filter(workplace_id=workplace_id)

        by_workplace = defaultdict(list)
        for session in qs:
            by_workplace[session.workplace_id].append(session)

        summaries = []
        for wp_id, sessions in by_workplace.items():
            type_hours = defaultdict(Decimal)
            dates_seen = set()
            for s in sessions:
                type_hours[s.session_type] += s.net_hours
                dates_seen.add(s.date)

            total = sum(type_hours.values(), Decimal("0"))
            summaries.append(
                MonthlySummary(
                    year=year,
                    month=month,
                    workplace_name=sessions[0].workplace.name,
                    workplace_id=wp_id,
                    total_hours=total.quantize(TWO_PLACES),
                    working_days=len(dates_seen),
                    on_site_hours=type_hours.get(WorkSession.SessionType.ON_SITE, Decimal("0")).quantize(TWO_PLACES),
                    remote_hours=type_hours.get(WorkSession.SessionType.REMOTE, Decimal("0")).quantize(TWO_PLACES),
                    sick_hours=type_hours.get(WorkSession.SessionType.SICK_LEAVE, Decimal("0")).quantize(TWO_PLACES),
                    vacation_hours=type_hours.get(WorkSession.SessionType.VACATION, Decimal("0")).quantize(TWO_PLACES),
                    paid_absence_hours=type_hours.get(WorkSession.SessionType.PAID_ABSENCE, Decimal("0")).quantize(TWO_PLACES),
                )
            )
        return summaries

    @staticmethod
    def period_summary(start_date: date, end_date: date, workplace_id: int) -> MonthlySummary:
        """Summarize sessions within an arbitrary date range for one workplace."""
        qs = WorkSession.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
            workplace_id=workplace_id,
        ).select_related("workplace")

        sessions = list(qs)
        type_hours = defaultdict(Decimal)
        dates_seen = set()
        wp_name = ""
        for s in sessions:
            type_hours[s.session_type] += s.net_hours
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
            on_site_hours=type_hours.get(WorkSession.SessionType.ON_SITE, Decimal("0")).quantize(TWO_PLACES),
            remote_hours=type_hours.get(WorkSession.SessionType.REMOTE, Decimal("0")).quantize(TWO_PLACES),
            sick_hours=type_hours.get(WorkSession.SessionType.SICK_LEAVE, Decimal("0")).quantize(TWO_PLACES),
            vacation_hours=type_hours.get(WorkSession.SessionType.VACATION, Decimal("0")).quantize(TWO_PLACES),
            paid_absence_hours=type_hours.get(WorkSession.SessionType.PAID_ABSENCE, Decimal("0")).quantize(TWO_PLACES),
        )
