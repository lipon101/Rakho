"""Uniform JSON error envelope for every API failure.

Before this module, an error could arrive in three different shapes depending
on where it was raised: DRF's default ``{"detail": "..."}`` for a permission
refusal, a bare ``{"error": "..."}`` string from a view, and the structured
``{"error": {"code": ...}}`` the Pro-refusal path already used. A client had to
guess which one it was holding.

Now every *exception* the API raises is normalised to one envelope::

    {
      "error": {
        "code": "validation_error",     # stable, machine-readable
        "detail": "Validation failed.", # human-readable
        "fields": {"name": ["..."]}     # only for field-level failures
      },
      "status": 400
    }

``code`` is the contract the Android client branches on, so it never changes
for a given condition even if the prose does. The envelope is nested under
``error`` to match the shape the Pro-refusal path already shipped, so existing
clients that read ``response["error"]["code"]`` keep working untouched.

View-level error responses that return a plain ``{"error": "..."}`` string are
left exactly as they are: they are covered by their own tests and changing them
would break the contract those tests pin down. This handler closes the gap for
everything raised as an exception, which is where the inconsistency lived.
"""

import logging

from django.conf import settings
from rest_framework import status as http_status
from rest_framework.views import exception_handler

logger = logging.getLogger("inventory.api")

# Status code -> stable machine-readable code. A client can branch on these
# without ever parsing the human message.
_STATUS_CODES = {
    http_status.HTTP_400_BAD_REQUEST: "validation_error",
    http_status.HTTP_401_UNAUTHORIZED: "not_authenticated",
    http_status.HTTP_403_FORBIDDEN: "permission_denied",
    http_status.HTTP_404_NOT_FOUND: "not_found",
    http_status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    http_status.HTTP_406_NOT_ACCEPTABLE: "not_acceptable",
    http_status.HTTP_409_CONFLICT: "conflict",
    http_status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    http_status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
    http_status.HTTP_500_INTERNAL_SERVER_ERROR: "server_error",
    http_status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}

# DRF's own exception classes carry a default_code that is more specific than
# the status mapping (e.g. "throttled" vs "too_many_requests"). Prefer it when
# it is present and meaningful.
_GENERIC_DEFAULT_CODES = {"error", "invalid", "detail"}


def code_for_status(status_code):
    """The stable code for an HTTP status, with a safe fallback."""
    return _STATUS_CODES.get(status_code, "error")


def error_payload(code, detail, fields=None):
    """Build the inner ``error`` object.

    Kept as a function so views that want the structured shape (rather than the
    legacy string shape) can produce it without duplicating the layout.
    """
    payload = {"code": code, "detail": detail}
    if fields:
        payload["fields"] = fields
    return payload


def error_response(detail, status_code):
    """A view-level error in the legacy string shape.

    The API's exception paths return the structured envelope
    (``{"error": {"code": ...}}``), but these view-level refusals are pinned by
    their own tests to the older ``{"error": "<string>"}`` shape. Centralising
    the construction here means the shape is defined once, so a future change
    is a one-line edit rather than a hunt through the views.
    """
    from rest_framework.response import Response

    return Response({"error": detail}, status=status_code)


def _is_enveloped(data):
    """True when ``data`` is already ``{"error": {"code": ...}}``.

    The Pro-refusal path builds this shape by hand; re-wrapping it would nest
    the envelope inside itself.
    """
    return isinstance(data, dict) and isinstance(data.get("error"), dict) and "code" in data["error"]


def _normalise(data, status_code, default_code):
    """Turn any DRF error body into the standard envelope."""
    # Already structured (e.g. the Pro refusal) — leave it alone.
    if _is_enveloped(data):
        return data

    # A view returned {"error": "<string>"} through an exception path.
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return {"error": error_payload(default_code, data["error"])}

    # DRF's default single-message shape: {"detail": "..."}.
    if isinstance(data, dict) and set(data.keys()) == {"detail"}:
        detail = data["detail"]
        if not isinstance(detail, str):
            detail = str(detail)
        return {"error": error_payload(default_code, detail)}

    # A serializer's field errors: {"field": ["msg", ...], ...}.
    if isinstance(data, dict):
        return {
            "error": error_payload(
                default_code,
                "Validation failed.",
                fields=data,
            )
        }

    # A list (e.g. a non-field error list) or anything else.
    return {"error": error_payload(default_code, data)}


def api_exception_handler(exc, context):
    """DRF exception handler that guarantees the uniform envelope.

    Also catches the exceptions DRF itself does not handle (``response is
    None``): those used to escape to Django's HTML 500 page, which a JSON
    client cannot read. They are logged and returned as a JSON 500 instead —
    except under ``DEBUG``, where the traceback is more useful than the
    envelope.
    """
    response = exception_handler(exc, context)

    if response is None:
        # Not an APIException: a genuine bug. Log it with the view context so
        # Sentry has something actionable, then answer in JSON.
        view = context.get("view") if context else None
        logger.exception(
            "Unhandled exception in %s",
            view.__class__.__name__ if view else "unknown view",
            exc_info=exc,
        )
        if settings.DEBUG:
            # Let Django render the traceback; a developer wants the stack.
            return None
        return _json_500()

    status_code = response.status_code
    default_code = code_for_status(status_code)

    # Prefer DRF's specific default_code when it says more than the status.
    exc_code = getattr(exc, "default_code", None)
    if isinstance(exc_code, str) and exc_code not in _GENERIC_DEFAULT_CODES:
        default_code = exc_code

    # An exception may carry its own structured payload in ``default_detail``
    # (an error_payload dict) — the invitation endpoints hand-build exactly
    # that. DRF stringifies the dict into ``detail`` and _normalise then buries
    # it under ``fields``, which destroys the ``error.code`` the caller is
    # meant to branch on. Rebuild the envelope from the original dict rather
    # than the mangled string. Read, never mutated: ``default_detail`` is a
    # class attribute shared by every instance of the exception.
    structured = getattr(exc, "default_detail", None)
    if isinstance(structured, dict) and "code" in structured:
        response.data = {"error": structured}

    response.data = _normalise(response.data, status_code, default_code)
    # Every envelope carries the status inside the body too, so a client that
    # only reads the payload still knows what happened.
    if isinstance(response.data, dict) and "status" not in response.data:
        response.data["status"] = status_code
    return response


def _json_500():
    """A JSON 500 for exceptions DRF does not handle."""
    from rest_framework.response import Response

    return Response(
        {
            "error": error_payload(
                "server_error",
                "An unexpected error occurred. The incident has been logged.",
            ),
            "status": http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        },
        status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
