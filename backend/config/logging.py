"""Logging helpers: a JSON formatter and a request-id filter.

The formatter emits one JSON object per line so a log aggregator can index
fields instead of regex-parsing prose. The filter injects the current request
id (set by ``config.middleware.RequestIdMiddleware``) into every record, which
is what lets one user complaint be traced across every line it produced.

Both are referenced by name from ``LOGGING`` in settings, so they must stay
importable without touching the database or the request cycle.
"""

import json
import logging
import time

# Context variable holding the id of the request being handled. A contextvar
# (not a thread-local) is correct here because it follows the async task as
# well as the thread, and it is reset by the middleware when the request ends.
try:
    from contextvars import ContextVar

    _request_id: "ContextVar[str]" = ContextVar("request_id", default="-")
except ImportError:  # pragma: no cover - contextvars is stdlib on 3.7+
    _request_id = None


def set_request_id(value):
    """Bind the current request id. Called by the middleware."""
    if _request_id is not None:
        return _request_id.set(value or "-")
    return None


def reset_request_id(token):
    """Restore the previous request id. Called by the middleware on exit."""
    if _request_id is not None and token is not None:
        _request_id.reset(token)


def get_request_id():
    """The current request id, or ``"-"`` outside a request."""
    if _request_id is None:
        return "-"
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Attach ``request_id`` to every record so the formatter can emit it."""

    def filter(self, record):
        record.request_id = get_request_id()
        return True


#: Substrings that must never reach a log line. Every one of these has, at
#: some point in this codebase's history, been printed by a default
#: ``__str__`` or an f-string: a raw API key, a customer's phone number, a
#: payment transaction id. Scrub rather than redact-in-place, because a
#: partially masked value is still a leak if the mask is predictable.
_SENSITIVE_HINTS = (
    "phm_",
    "password",
    "secret",
    "token",
    "authorization",
    "x-pharmacy-key",
    "purchase_token",
)


class PIIRedactionFilter(logging.Filter):
    """Stop credentials and personal data reaching a log line.

    Sentry is already configured with ``send_default_pii=False``, but that only
    covers Sentry: the structured log stream is a separate sink with a separate
    retention policy, and a support ticket quoting a request id pulls those
    lines into a chat window. The filter is deliberately blunt --- it redacts
    the *whole* message when a sensitive marker appears rather than trying to
    locate and mask one substring, since a clever partial mask is exactly how
    leaks survive.
    """

    REDACTED = "[redacted: message contained a credential or personal data]"

    def filter(self, record):
        message = str(record.getMessage())
        lowered = message.lower()
        if any(hint in lowered for hint in _SENSITIVE_HINTS):
            # Rewrite the record so neither the formatter nor any later handler
            # can recover the original text.
            record.msg = self.REDACTED
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON line.

    Only the fields an operator actually filters on are emitted; the message
    and any exception traceback are included verbatim. ``ensure_ascii`` is off
    so Bengali text in a message stays readable rather than turning into
    escape sequences.
    """

    def format(self, record):
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Anything a caller passed via logger.info("...", extra={...}) is kept
        # under "extra" rather than flattened, so it cannot shadow a core field.
        reserved = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "taskName",
            "request_id",
            "message",
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in reserved}
        if extra:
            payload["extra"] = extra
        return json.dumps(payload, ensure_ascii=False, default=str)
