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
import time
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


class DefaultLanguageMiddleware:
    """Give the human-facing UI a Bengali default without touching the API.

    Rakho is a Bangladesh-first product, so a shopkeeper who opens the landing
    page, the checkout page or the legal pages should see Bengali without
    having to find a language switch first. Two boundaries keep that default
    from doing harm:

    * **Never /api/.** The JSON API's messages are a contract the Android app
      branches on, and its English wording is covered by tests. Rewriting the
      request language there would silently change error prose for every
      client that never asked for it.
    * **Never over a stated preference.** An explicit ``?lang=`` in the query
      string, a language cookie, or an ``Accept-Language`` header that names a
      language Rakho actually ships always wins. The default applies only when
      the caller has expressed nothing at all.

    ``?lang=`` is handled by setting Django's own language cookie, which is
    what makes a switch link persist for the visitor's next request instead of
    lasting exactly one page view.
    """

    #: Path prefixes that must keep their original language.
    API_PREFIXES = ("/api/", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.utils import translation

        if not request.path.startswith(self.API_PREFIXES):
            available = {code for code, _ in settings.LANGUAGES}
            # An explicit ?lang= is both a preference and a lasting choice, so
            # it is remembered in a cookie rather than applied to one response.
            requested = request.GET.get("lang")
            if requested in available:
                request._rakho_set_language_cookie = requested
            elif not self._caller_stated_a_language(request, available):
                translation.activate(getattr(settings, "SITE_DEFAULT_LANGUAGE", "bn"))
                request.LANGUAGE_CODE = translation.get_language()

        response = self.get_response(request)

        chosen = getattr(request, "_rakho_set_language_cookie", None)
        if chosen:
            response.set_cookie(
                settings.LANGUAGE_COOKIE_NAME,
                chosen,
                max_age=settings.LANGUAGE_COOKIE_AGE,
                samesite="Lax",
            )
        return response

    @staticmethod
    def _caller_stated_a_language(request, available):
        """True when the visitor already asked for a language Rakho ships.

        Django's ``LocaleMiddleware`` runs above this one and has already read
        both the cookie and the header, so checking its resolved language is
        enough --- but it resolves to ``LANGUAGE_CODE`` (English) when nothing
        was stated, which is indistinguishable from an explicit request for
        English. The cookie and header are therefore inspected directly.
        """
        from django.conf import settings
        from django.utils import translation

        cookie = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
        if cookie and translation.check_for_language(cookie):
            return True
        header = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
        for chunk in header.split(","):
            tag = chunk.split(";")[0].strip().lower()
            if tag and tag.replace("-", "_").split("_")[0] in available:
                return True
        return False


class MetricsMiddleware:
    """Record every request into the Prometheus registry (Phase 6).

    Placed here rather than in a decorator on each view for the reason metrics
    are usually wrong: a view that forgets to instrument itself goes missing
    from the dashboard, and a missing series reads as "no traffic" rather than
    as "not measured". One middleware cannot forget.

    The label is the *route template* (``org-invoice-detail``), never
    ``request.path``. A raw path carries a uuid, so labelling by it would create
    one time series per invoice and grow without bound --- the standard way a
    metrics endpoint takes down the monitoring it was added to provide.

    A failure inside the instrumentation is swallowed. Metrics are a
    side-channel: they must never be the reason a customer's sale fails, so the
    recording is wrapped and the response is returned regardless.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from inventory import metrics

        if not metrics.metrics_available():
            return self.get_response(request)

        metrics.track_inflight(1)
        started = time.monotonic()
        try:
            response = self.get_response(request)
        finally:
            metrics.track_inflight(-1)

        try:
            duration = time.monotonic() - started
            match = getattr(request, "resolver_match", None)
            route = getattr(match, "view_name", None) or "unmatched"
            metrics.record_request(request.method, route, response.status_code, duration)
        except Exception:  # noqa: BLE001 - never let instrumentation break a response
            pass
        return response
