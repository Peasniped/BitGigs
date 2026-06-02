"""Workplace-related business logic."""
from datetime import date

from django.db.models import Q


class WorkplaceService:
    """Utilities for workplace queries."""

    @staticmethod
    def get_active_workplaces():
        from .models import Workplace
        return Workplace.objects.filter(is_active=True)

    @staticmethod
    def get_hourly_workplaces():
        from .models import Workplace
        return (
            Workplace.objects.filter(is_active=True)
            .filter(contracts__term_sets__employment_type="hourly")
            .distinct()
        )

    @staticmethod
    def get_salaried_workplaces():
        from .models import Workplace
        return (
            Workplace.objects.filter(is_active=True)
            .filter(contracts__term_sets__employment_type="salaried")
            .distinct()
        )

    @staticmethod
    def workplaces_active_in_period(start: date, end: date):
        """Workplaces with at least one contract overlapping [start, end]."""
        from .models import Workplace
        return (
            Workplace.objects.filter(is_active=True)
            .filter(contracts__start_date__lte=end)
            .filter(
                Q(contracts__end_date__isnull=True) | Q(contracts__end_date__gte=start)
            )
            .distinct()
        )
