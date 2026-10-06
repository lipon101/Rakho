"""Request-scoped middleware.

``RequestIdMiddleware`` gives every request an id, echoes it back in the
``X-Request-Id`` response header, and binds it for the logging filter. A
support ticket that quotes the header value can then be traced to every log
line the request produced — which is the whole point of having ids at all.

The id is taken from an inbound ``X-Request-Id`` when a trusted caller (a
proxy, or the Android client) supplies one, and generated otherwise. It is
validated before use: an attacker-supplied value ends up in log lines, so it
is restricted to a short, safe character set rather than trusted verbatim.
"""

import re
import uuid

from config.logging import reset_request_id, set_request_id

# A request id is echoed into a response header and written into log lines, so
# it is constrained to characters that are safe in both. Anything else is
# discarded and a fresh id is generated instead.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

HEADER = "X-Request-Id"


def _clean(value):
    """Return ``value`` if it is a safe id, else ``None``."""
    if value and _SAFE_ID.match(value):
        return value
    return None


class RequestIdMiddleware:
    """Attach a request id to the request, the response and the log context."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = _clean(request.META.get("HTTP_X_REQUEST_ID")) or uuid.uuid4().hex
        request.request_id = request_id
        token = set_request_id(request_id)
        try:
            response = self.get_response(request)
        finally:
            # Reset even if the view raised, so the id never leaks into the
            # next request handled by the same worker.
            reset_request_id(token)
        response[HEADER] = request_id
        return response
