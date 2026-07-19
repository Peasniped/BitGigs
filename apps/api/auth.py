"""Bearer-key authentication for the ``/api/v1/`` endpoints.

The whole site sits behind ``LoginRequiredMiddleware``; API views opt out of
the session gate and are guarded here instead — a valid, unexpired, unrevoked
``ApiKey`` in the ``Authorization: Bearer bg_…`` header, holding the scope the
endpoint requires. Every failure is a JSON error whose ``error`` code names the
actual problem (missing vs invalid vs expired vs revoked vs out-of-scope), so a
client author never has to guess which of five things a bare 401 meant.
"""
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View

from .models import ApiKey


class ApiAuthError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.code = code


def authenticate_request(request, endpoint_id: str | None) -> ApiKey:
    """The active ``ApiKey`` authorising this request, or ``ApiAuthError``.

    ``endpoint_id`` is the scope the endpoint requires; ``None`` means any
    valid key will do (utility endpoints like ping).
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiAuthError(
            401, "missing_key",
            "Provide an API key in the Authorization header: 'Bearer bg_…'. "
            "Keys are created in Settings → API.",
        )
    key = ApiKey.find(header.removeprefix("Bearer ").strip())
    if key is None:
        raise ApiAuthError(401, "invalid_key", "This API key is not recognised.")
    if key.is_revoked:
        raise ApiAuthError(401, "revoked_key", "This API key has been revoked.")
    if key.is_expired:
        raise ApiAuthError(
            401, "expired_key",
            f"This API key expired on {key.expires_at.isoformat()}.",
        )
    if endpoint_id is not None and not key.allows(endpoint_id):
        raise ApiAuthError(
            403, "insufficient_scope",
            f"This API key does not have access to the '{endpoint_id}' endpoint.",
        )
    key.stamp_used()
    return key


def error_response(status: int, code: str, detail: str) -> JsonResponse:
    return JsonResponse({"ok": False, "error": code, "detail": detail}, status=status)


@method_decorator(login_not_required, name="dispatch")
class ApiEndpointView(View):
    """Base class for key-authenticated endpoints.

    Subclasses set ``endpoint_id`` (their scope, or None for unscoped) and
    implement ``get``. **Only this class may define dispatch()** — the
    ``login_not_required`` marker is attached to the dispatch *method*, so an
    overriding subclass would silently drop it and LoginRequiredMiddleware
    would start answering with login redirects (same caveat as
    ``_AccountStepView`` in core).
    """

    endpoint_id: str | None = None

    def dispatch(self, request, *args, **kwargs):
        try:
            request.api_key = authenticate_request(request, self.endpoint_id)
        except ApiAuthError as exc:
            response = error_response(exc.status, exc.code, str(exc))
        else:
            response = super().dispatch(request, *args, **kwargs)
        # Machine clients get the truth, not a cached copy of someone else's.
        response.headers["Cache-Control"] = "no-store"
        return response
