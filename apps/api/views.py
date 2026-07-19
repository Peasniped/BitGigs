"""API endpoint views (key-authenticated JSON) and the session-gated
management views behind Settings → API. Heavy lifting stays in services.py.
"""
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View

from core.utils import parse_int_param, parse_iso_date_param
from django.utils import timezone

from . import registry, services
from .auth import ApiEndpointView, error_response
from .models import SCOPE_ALL, ApiKey

# One-time reveal: the freshly issued key rides the session across the
# redirect to the settings tab, is shown once, and is gone.
SESSION_NEW_KEY = "api_new_key"


# ─────────────────────────────────────────────────────────────────────────────
# /api/v1/ endpoints
# ─────────────────────────────────────────────────────────────────────────────

class PingView(ApiEndpointView):
    """Key check: any valid key may call this (endpoint_id stays None)."""

    def get(self, request):
        key = request.api_key
        return JsonResponse({
            "ok": True,
            "key": key.name,
            "scopes": key.scopes,
            "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        })


class IncomeView(ApiEndpointView):
    endpoint_id = "income"

    def get(self, request):
        try:
            start, end = services.resolve_income_period(
                year=parse_int_param(request.GET.get("year")),
                month=parse_int_param(request.GET.get("month")),
                start=request.GET.get("start"),
                end=request.GET.get("end"),
            )
        except services.PeriodError as exc:
            return error_response(400, "bad_request", str(exc))
        return JsonResponse(services.income_payload(start, end))


# ─────────────────────────────────────────────────────────────────────────────
# Key management (normal session-authenticated pages behind the login gate)
# ─────────────────────────────────────────────────────────────────────────────

def _back_to_tab():
    return redirect(f"{reverse('core:settings')}?tab=api")


class ApiKeyCreateView(View):
    def post(self, request):
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Give the key a name so you can recognise it later.")
            return _back_to_tab()

        expires_at = None
        raw_expiry = (request.POST.get("expires_at") or "").strip()
        if raw_expiry:
            expires_at = parse_iso_date_param(raw_expiry)
            if expires_at is None:
                messages.error(request, "The expiration date could not be read.")
                return _back_to_tab()
            if expires_at < timezone.localdate():
                messages.error(request, "The expiration date is already in the past.")
                return _back_to_tab()

        if request.POST.get("scope_mode") == "all":
            scopes = [SCOPE_ALL]
        else:
            scopes = [
                s for s in request.POST.getlist("scopes")
                if s in registry.valid_scope_ids()
            ]
            if not scopes:
                messages.error(request, "Pick at least one endpoint the key may access.")
                return _back_to_tab()

        key, raw_key = ApiKey.issue(name=name, scopes=scopes, expires_at=expires_at)
        request.session[SESSION_NEW_KEY] = {"pk": key.pk, "key": raw_key}
        return _back_to_tab()


class ApiKeyRevokeView(View):
    def post(self, request, pk):
        try:
            key = ApiKey.objects.get(pk=pk)
        except ApiKey.DoesNotExist:
            return _back_to_tab()
        key.revoke()
        messages.success(request, f"API key “{key.name}” revoked. It no longer works.")
        return _back_to_tab()


class ApiKeyDeleteView(View):
    """Remove a key row entirely. Only inactive (revoked/expired) keys can be
    deleted — an active key must be revoked first, so a slip of the mouse can't
    silently remove a credential that still works."""

    def post(self, request, pk):
        try:
            key = ApiKey.objects.get(pk=pk)
        except ApiKey.DoesNotExist:
            return _back_to_tab()
        if key.is_active:
            messages.error(request, "Revoke the key first, then delete it.")
            return _back_to_tab()
        key.delete()
        messages.success(request, f"API key “{key.name}” deleted.")
        return _back_to_tab()


def api_settings_context(request):
    """Context for the Settings → API tab (called by core's UserSettingsView,
    same shape as its email_context helper)."""
    base_url = f"{request.scheme}://{request.get_host()}"
    new_key = request.session.pop(SESSION_NEW_KEY, None)
    keys = list(ApiKey.objects.all())
    if new_key:
        for key in keys:
            if key.pk == new_key["pk"]:
                key.just_created = True
    return {
        "api_keys": keys,
        "api_new_key": new_key,
        "api_endpoints": [
            {
                "endpoint": ep,
                "sample": registry.sample_python(ep, base_url),
            }
            for ep in registry.ENDPOINTS
        ],
        "api_scope_choices": registry.scoped_endpoints(),
    }
