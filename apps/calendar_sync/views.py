"""Calendar sync views.

Phase 1 exposes one JSON endpoint, ``busy``, that the planning overlay polls for
the visible month. It stays thin — the fetch/parse/cache/aggregate work lives in
``services`` — and always answers with JSON, never a redirect or a 500, so a
broken feed degrades to an empty overlay.
"""
from django.http import JsonResponse
from django.utils import timezone
from django.views import View

from core.utils import parse_int_param

from . import services


class BusyView(View):
    """``GET ?year=&month=`` → JSON busy blocks for the planning overlay.

    Own (``bitgigs-``) UIDs are filtered in ``parse_calendar`` so a shift we
    emitted as an invite never reads back as a collision with itself. ``refresh=1``
    busts the per-subscription cache (the overlay's manual refresh).
    """

    def get(self, request):
        today = timezone.localdate()
        year = parse_int_param(request.GET.get("year"), today.year)
        month = parse_int_param(request.GET.get("month"), today.month)
        if not (1 <= month <= 12):
            return JsonResponse({"error": "Invalid month."}, status=400)

        refresh = request.GET.get("refresh") == "1"
        window_start, window_end = services.month_window(year, month)
        blocks = services.busy_blocks(window_start, window_end, refresh=refresh)
        return JsonResponse({"busy": blocks})
