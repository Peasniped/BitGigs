"""Workplace-related business logic."""


class WorkplaceService:
    """Utilities for workplace queries."""

    @staticmethod
    def get_active_workplaces():
        from .models import Workplace

        return Workplace.objects.filter(is_active=True)

    @staticmethod
    def get_hourly_workplaces():
        from .models import Workplace

        return Workplace.objects.filter(
            is_active=True, employment_type=Workplace.EmploymentType.HOURLY
        )

    @staticmethod
    def get_salaried_workplaces():
        from .models import Workplace

        return Workplace.objects.filter(
            is_active=True, employment_type=Workplace.EmploymentType.SALARIED
        )
