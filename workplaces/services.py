"""Workplace-related business logic."""
from datetime import date

from django.db.models import Q


def workplaces_active_in_period(start: date, end: date):
    """Workplaces with at least one contract overlapping [start, end]."""
    from .models import Workplace
    return (
        Workplace.objects.filter(contracts__start_date__lte=end)
        .filter(Q(contracts__end_date__isnull=True) | Q(contracts__end_date__gte=start))
        .distinct()
    )


def workplaces_active_today():
    """Workplaces with at least one currently active contract (today)."""
    today = date.today()
    return workplaces_active_in_period(today, today)


def hidden_workplace_count(active_count: int) -> int:
    """How many workplaces are excluded by period filtering.

    Returns 0 unless *active_count* is 0, so the notice only appears when the
    period filter hid everything (per product requirement).
    """
    if active_count > 0:
        return 0
    from .models import Workplace
    return Workplace.objects.count()


class WorkplaceService:
    """Utilities for workplace queries."""

    @staticmethod
    def get_active_workplaces():
        return workplaces_active_today()

    @staticmethod
    def get_hourly_workplaces():
        return workplaces_active_today().filter(
            contracts__term_sets__employment_type="hourly"
        ).distinct()

    @staticmethod
    def get_salaried_workplaces():
        return workplaces_active_today().filter(
            contracts__term_sets__employment_type="salaried"
        ).distinct()

    @staticmethod
    def workplaces_active_in_period(start: date, end: date):
        """Workplaces with at least one contract overlapping [start, end]."""
        return workplaces_active_in_period(start, end)
