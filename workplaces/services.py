"""Workplace-related business logic."""
from datetime import date

from django.db.models import Q


def workplaces_active_today():
    """Workplaces with at least one currently active contract (today)."""
    from .models import Workplace
    today = date.today()
    return (
        Workplace.objects.filter(contracts__start_date__lte=today)
        .filter(Q(contracts__end_date__isnull=True) | Q(contracts__end_date__gte=today))
        .distinct()
    )


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
        from .models import Workplace
        return (
            Workplace.objects.filter(contracts__start_date__lte=end)
            .filter(Q(contracts__end_date__isnull=True) | Q(contracts__end_date__gte=start))
            .distinct()
        )
