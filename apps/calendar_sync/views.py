"""Calendar sync views.

Phase 1 exposes one JSON endpoint, ``busy``, that the planning overlay polls for
the visible month. It stays thin — the fetch/parse/cache/aggregate work lives in
``services`` — and always answers with JSON, never a redirect or a 500, so a
broken feed degrades to an empty overlay.
"""
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views import View

from core.utils import parse_int_param, parse_iso_date_param

from . import services

# Upper bound on the busy window a client can ask for, so a crafted request
# can't force a huge RRULE expansion. The planning grid spans at most a couple
# of payroll periods (~7 weeks); this leaves generous headroom.
MAX_WINDOW_DAYS = 120


class BusyView(View):
    """``GET`` → JSON busy blocks for the planning overlay.

    Preferred call is ``?start=YYYY-MM-DD&end=YYYY-MM-DD`` — the exact span of
    days the planning grid is showing, which (with offset payroll periods) can
    reach well beyond the selected month. Falls back to ``?year=&month=`` (the
    padded month window) when a range isn't given.

    Own (``bitgigs-``) UIDs are filtered in ``parse_calendar`` so a shift we
    emitted as an invite never reads back as a collision with itself. ``refresh=1``
    busts the per-subscription cache (the overlay's manual refresh).
    """

    def get(self, request):
        refresh = request.GET.get("refresh") == "1"

        start = parse_iso_date_param(request.GET.get("start"))
        end = parse_iso_date_param(request.GET.get("end"))
        if start and end:
            if end < start:
                return JsonResponse({"error": "end is before start."}, status=400)
            # Clamp an over-wide range rather than reject it.
            end = min(end, start + timedelta(days=MAX_WINDOW_DAYS))
            window_start, window_end = start, end
        else:
            today = timezone.localdate()
            year = parse_int_param(request.GET.get("year"), today.year)
            month = parse_int_param(request.GET.get("month"), today.month)
            if not (1 <= month <= 12):
                return JsonResponse({"error": "Invalid month."}, status=400)
            window_start, window_end = services.month_window(year, month)

        blocks = services.busy_blocks(window_start, window_end, refresh=refresh)
        return JsonResponse({"busy": blocks})
