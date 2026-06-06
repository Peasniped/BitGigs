from datetime import date
from decimal import Decimal
import json

from django.shortcuts import render
from django.views import View

from core.models import UserSettings
from core.utils import avatar_for_name
from workplaces.models import Workplace
from workplaces.services import workplaces_active_today, hidden_workplace_count
from .services import AnalyticsService


# Palette used to colour each workplace bar in the distribution chart.
_DIST_COLORS = [
    "#6366f1", "#22c55e", "#f97316", "#ec4899",
    "#14b8a6", "#eab308", "#8b5cf6", "#ef4444",
    "#06b6d4", "#3b82f6", "#84cc16", "#f43f5e",
]


def _parse_int(raw, default):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_iso_date(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _resolve_workplace_filter(request, queryset):
    """
    Workplace selection logic:
      * No `wp_set` marker in querystring (clean URL/first load) → all selected
      * `wp_set=1` present and zero `workplace` values → empty selection
      * `?workplace=all`                                   → all selected
      * Otherwise → only the listed slugs are selected
    """
    has_marker = request.GET.get("wp_set") == "1"
    selected_slugs = request.GET.getlist("workplace")

    if not has_marker:
        return queryset, set(queryset.values_list("slug", flat=True)), True

    if "all" in selected_slugs:
        return queryset, set(queryset.values_list("slug", flat=True)), True

    if not selected_slugs:
        return queryset.none(), set(), False

    filtered = queryset.filter(slug__in=selected_slugs)
    return filtered, set(selected_slugs), False


def _avatar_payload(wp: Workplace) -> dict:
    initials, fallback_color = avatar_for_name(wp.name)
    return {
        "initials": initials,
        "color": wp.color or fallback_color,
        "icon": wp.icon,
        "custom_icon_url": wp.custom_icon.url if wp.custom_icon else "",
        "accent_color": wp.accent_color,
    }


def _resolve_period(request, today: date):
    """
    Return (start, end, mode, year) where mode is 'year' or 'range'.
    """
    mode = request.GET.get("period_mode") or "year"
    if mode == "range":
        start = _parse_iso_date(request.GET.get("start"))
        end = _parse_iso_date(request.GET.get("end"))
        if not start or not end:
            # Fall back to current calendar year if missing
            mode = "year"
        elif end < start:
            start, end = end, start
        if mode == "range":
            return start, end, "range", start.year

    year = _parse_int(request.GET.get("year"), today.year)
    return date(year, 1, 1), date(year, 12, 31), "year", year


class AnalyticsView(View):
    """Income projection page."""

    template_name = "analytics/analytics.html"

    def get(self, request):
        today = date.today()
        settings = UserSettings.load()

        start, end, period_mode, year = _resolve_period(request, today)
        # Trailing window/method come exclusively from settings now
        trailing_months = settings.projection_trailing_months
        method = settings.projection_method

        from workplaces.services import WorkplaceService
        all_workplaces_qs = WorkplaceService.workplaces_active_in_period(start, end).order_by("name")
        selected_qs, selected_slugs, is_all = _resolve_workplace_filter(
            request, all_workplaces_qs
        )

        projection = AnalyticsService.project_period(
            selected_qs, start=start, end=end,
            trailing_months=trailing_months,
            method=method,
            today=today,
        )

        # Picker cards
        workplaces_for_picker = []
        for wp in all_workplaces_qs:
            workplaces_for_picker.append({
                "slug": wp.slug,
                "name": wp.name,
                "selected": wp.slug in selected_slugs,
                "avatar": _avatar_payload(wp),
            })

        # Year picker range
        year_options = list(range(today.year - 5, today.year + 4))

        # Combined trailing average across selected workplaces
        combined_avg_monthly = sum(
            (wp.trailing_avg_monthly_hours for wp in projection.workplaces),
            Decimal("0"),
        )
        combined_avg_weekly = sum(
            (wp.trailing_avg_weekly_hours for wp in projection.workplaces),
            Decimal("0"),
        )

        # Distribution chart datasets: each workplace contributes a stacked
        # bar segment per month. Palette is stable across the page.
        distribution_datasets = []
        for idx, wp_proj in enumerate(projection.workplaces):
            color = wp_proj.workplace.accent_color or _DIST_COLORS[idx % len(_DIST_COLORS)]
            distribution_datasets.append({
                "label": wp_proj.workplace.name,
                "color": color,
                "gross": [str(row.gross) for row in wp_proj.months],
                "net": [str(row.net) for row in wp_proj.months],
                "projected": [row.is_projected for row in wp_proj.months],
            })

        # Workplace context for collapsible cards
        workplaces_view = []
        for wp_proj in projection.workplaces:
            ts_today = wp_proj.workplace.active_termset_on(today)
            workplaces_view.append({
                "wp_proj": wp_proj,
                "avatar": _avatar_payload(wp_proj.workplace),
                "employment_type": ts_today.employment_type if ts_today else "",
            })

        return render(request, self.template_name, {
            "projection": projection,
            "year": year,
            "period_mode": period_mode,
            "period_start": start,
            "period_end": end,
            "hidden_workplace_count": hidden_workplace_count(all_workplaces_qs.count()),
            "trailing_months": trailing_months,
            "method": method,
            "workplaces_for_picker": workplaces_for_picker,
            "is_all_selected": is_all,
            "year_options": year_options,
            "combined_avg_monthly": combined_avg_monthly,
            "combined_avg_weekly": combined_avg_weekly,
            "today": today,
            "distribution_datasets": distribution_datasets,
            "workplaces_view": workplaces_view,
            "settings_obj": settings,
            "next_url": request.get_full_path(),
            # JSON-safe variants for json_script tags
            "month_labels_json": list(projection.monthly_labels),
            "monthly_totals_gross_json": [str(v) for v in projection.monthly_totals_gross],
            "monthly_totals_net_json": [str(v) for v in projection.monthly_totals_net],
        })


class RateHistoryView(View):
    """Page showing historical (and projected) hourly/monthly rates."""

    template_name = "analytics/rate_history.html"

    def get(self, request):
        today = date.today()

        # Period resolved first so we can filter by it
        raw_mode = request.GET.get("period_mode")
        if raw_mode == "all" or raw_mode is None:
            period_mode = "all"
            start = None
            end = None
            year = today.year
        else:
            start, end, period_mode, year = _resolve_period(request, today)

        from workplaces.services import WorkplaceService
        if start and end:
            all_workplaces_qs = WorkplaceService.workplaces_active_in_period(start, end).order_by("name")
        else:
            all_workplaces_qs = workplaces_active_today().order_by("name")
        selected_qs, selected_slugs, is_all = _resolve_workplace_filter(
            request, all_workplaces_qs
        )

        year_options = list(range(today.year - 5, today.year + 4))
        start_iso = start.isoformat() if start else None
        end_iso = end.isoformat() if end else None

        workplace_rows = []
        for wp in selected_qs:
            history = AnalyticsService.rate_history(wp)
            # Build chart points: stepped line of net_hourly + total_hourly
            # over time. The last entry extends to today + 12 months to show
            # the "current → forward" projection band.
            chart_points = []
            for h in history:
                chart_points.append({
                    "date": h["effective_from"].isoformat(),
                    "net_hourly": str(h["net_hourly"] or 0),
                    "total_hourly": str(h["total_hourly"] or 0),
                    "gross_monthly": str(h["gross_monthly"] or 0),
                    "net_monthly": str(h["net_monthly"] or 0),
                })
            if chart_points:
                # Add a forward-projection terminator point ~12 months out
                forward = date(today.year + 1, today.month, 1)
                last = history[-1]
                chart_points.append({
                    "date": forward.isoformat(),
                    "net_hourly": str(last["net_hourly"] or 0),
                    "total_hourly": str(last["total_hourly"] or 0),
                    "gross_monthly": str(last["gross_monthly"] or 0),
                    "net_monthly": str(last["net_monthly"] or 0),
                    "projected": True,
                })

            # Apply the period filter to the chart points (skipped for 'all').
            # Keep the latest point that's strictly before `start_iso` and
            # snap its date forward to start so the stepped line still shows
            # the rate active at the start of the visible window.
            if chart_points and start_iso and end_iso:
                pre = None
                in_range = []
                for p in chart_points:
                    if p["date"] < start_iso:
                        pre = p
                    elif p["date"] <= end_iso:
                        in_range.append(p)
                if pre is not None:
                    snap = dict(pre)
                    snap["date"] = start_iso
                    in_range.insert(0, snap)
                # Clamp a trailing projection point that overshoots the end
                # so the stepped line ends visibly at the period end.
                if in_range and in_range[-1]["date"] < end_iso:
                    last_in = dict(in_range[-1])
                    last_in["date"] = end_iso
                    last_in["projected"] = True
                    in_range.append(last_in)
                chart_points = in_range

            ts_today = wp.active_termset_on(today)
            workplace_rows.append({
                "workplace": wp,
                "avatar": _avatar_payload(wp),
                "history": history,
                "chart_points": chart_points,
                "chart_points_json": json.dumps(chart_points),
                "today_iso": today.isoformat(),
                "employment_type": ts_today.employment_type if ts_today else "",
                "employment_type_display": ts_today.get_employment_type_display() if ts_today else "",
            })

        workplaces_for_picker = []
        for wp in all_workplaces_qs:
            workplaces_for_picker.append({
                "slug": wp.slug,
                "name": wp.name,
                "selected": wp.slug in selected_slugs,
                "avatar": _avatar_payload(wp),
            })

        return render(request, self.template_name, {
            "workplace_rows": workplace_rows,
            "workplaces_for_picker": workplaces_for_picker,
            "hidden_workplace_count": hidden_workplace_count(all_workplaces_qs.count()),
            "is_all_selected": is_all,
            "today": today,
            "period_mode": period_mode,
            "period_start": start,
            "period_end": end,
            "year": year,
            "year_options": year_options,
        })
