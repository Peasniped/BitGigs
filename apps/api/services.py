"""API services — parameter resolution and JSON payload assembly.

The income endpoint deliberately computes nothing itself: it calls the same
``AnalyticsService.project_period`` the Analytics page uses, with the same
settings, so the API and the UI can never disagree about a month's numbers.
"""
import calendar
import re
from datetime import date
from decimal import Decimal

from core.models import UserSettings
from analytics.services import AnalyticsService, MonthRow


TWO_PLACES = Decimal("0.01")

# 10 years of months is more than any legitimate range and less than a
# request that would grind the server.
MAX_MONTHS = 120

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


class PeriodError(ValueError):
    pass


def _parse_month(value: str, param: str) -> tuple[int, int]:
    match = _MONTH_RE.match(value or "")
    if not match:
        raise PeriodError(f"'{param}' must be a month formatted YYYY-MM, e.g. 2026-01.")
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise PeriodError(f"'{param}' has month {month:02d} — months run 01–12.")
    return year, month


def resolve_income_period(year, month, start, end) -> tuple[date, date]:
    """Resolve the query parameters to a (start, end) date span.

    Accepted forms: ``year=2026`` (whole year), ``year=2026&month=7`` (one
    month), ``start=2026-01&end=2026-06`` (range). No parameters = the current
    year.
    """
    if start or end:
        if year or month:
            raise PeriodError("Use either year/month or start/end, not both.")
        if not (start and end):
            raise PeriodError("A range needs both 'start' and 'end' (YYYY-MM).")
        sy, sm = _parse_month(start, "start")
        ey, em = _parse_month(end, "end")
        if (ey, em) < (sy, sm):
            raise PeriodError("'end' is before 'start'.")
        n_months = (ey - sy) * 12 + (em - sm) + 1
        if n_months > MAX_MONTHS:
            raise PeriodError(f"The range spans {n_months} months — the maximum is {MAX_MONTHS}.")
        return date(sy, sm, 1), date(ey, em, calendar.monthrange(ey, em)[1])

    if month is not None and year is None:
        raise PeriodError("'month' needs a 'year' as well.")

    from django.utils import timezone
    year = year if year is not None else timezone.localdate().year
    if not 2000 <= year <= 2100:
        raise PeriodError(f"'{year}' is not a plausible year.")
    if month is not None:
        if not 1 <= month <= 12:
            raise PeriodError(f"'month' is {month} — months run 1–12.")
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    return date(year, 1, 1), date(year, 12, 31)


def _money(value: Decimal) -> str:
    # Decimals go out as strings ("12345.67") — JSON floats would re-introduce
    # exactly the rounding the codebase bans floats to avoid.
    return str(value.quantize(TWO_PLACES))


def _month_state(row: MonthRow) -> str:
    if not row.contract_active:
        return "inactive"
    if row.is_planned:
        return "planned"
    if row.is_projected:
        return "projected"
    return "actual"


def income_payload(start: date, end: date) -> dict:
    settings = UserSettings.load()

    from workplaces.services import WorkplaceService
    workplaces = WorkplaceService.workplaces_active_in_period(start, end).order_by("name")

    projection = AnalyticsService.project_period(
        workplaces, start=start, end=end,
        trailing_months=settings.projection_trailing_months,
        method=settings.projection_method,
        use_planned=settings.use_planned_shifts,
    )

    month_keys = [
        f"{row.year:04d}-{row.month:02d}"
        for row in (projection.workplaces[0].months if projection.workplaces else [])
    ]
    if not month_keys:
        # No active workplaces — still report the months, all zero.
        month_keys = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            month_keys.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        projection.monthly_totals_gross = [Decimal("0")] * len(month_keys)
        projection.monthly_totals_net = [Decimal("0")] * len(month_keys)

    return {
        "ok": True,
        "start": month_keys[0],
        "end": month_keys[-1],
        "currency": "DKK",
        "months": [
            {
                "month": key,
                "gross": _money(projection.monthly_totals_gross[idx]),
                "net": _money(projection.monthly_totals_net[idx]),
            }
            for idx, key in enumerate(month_keys)
        ],
        "totals": {
            "gross": _money(projection.year_gross),
            "net": _money(projection.year_net),
        },
        "workplaces": [
            {
                "name": wp.workplace.name,
                "slug": wp.workplace.slug,
                "total_gross": _money(wp.year_gross),
                "total_net": _money(wp.year_net),
                "months": [
                    {
                        "month": f"{row.year:04d}-{row.month:02d}",
                        "gross": _money(row.gross),
                        "net": _money(row.net),
                        "hours": str(row.hours),
                        "state": _month_state(row),
                    }
                    for row in wp.months
                ],
            }
            for wp in projection.workplaces
        ],
    }
