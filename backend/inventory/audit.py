"""The audit trail: who changed what, when, and from where.

Written through one function rather than by hand at each call site, because an
audit entry that is *usually* written is worse than none at all --- it invites
the assumption that the record is complete. ``record()`` fills the actor, the
tenant, the branch, the client address and the request id from the request, so
a caller supplies only the action and what changed.

Two rules the module enforces rather than documents:

* An entry is never written without an organisation when it is possible to
  determine one. A trail that cannot be filtered by tenant is not usable by the
  tenant.
* A failure to write must never fail the request that caused it. Losing an
  audit row is bad; losing a sale because the audit table was locked is worse.
  The failure is logged instead.
"""

import logging

from django.db import transaction

from .models import AuditLog

logger = logging.getLogger("inventory.audit")

#: Fields never worth recording, either because they are noise on every row or
#: because they hold a credential. A purchase token or a password hash in an
#: audit diff would be a leak with a long retention policy.
_IGNORED_FIELDS = frozenset(
    {
        "id",
        "pk",
        "created_at",
        "updated_at",
        "password",
        "raw_response",
        "purchase_token",
        "key_hash",
        "token_hash",
    }
)


def _stringify(value):
    """A JSON-safe rendering of a field value.

    ``str()`` on a foreign key is the related object's name, which is what a
    reader wants; on anything else it is the value. Dates keep their ISO form
    so a diff stays machine-readable.
    """
    if value is None:
        return None
    if hasattr(value, "pk"):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def diff(instance, before):
    """Field-level before/after for ``instance`` against a snapshot dict.

    Returns only the fields that actually changed, so an audit row for a
    two-field edit is two lines rather than forty. An empty result is a real
    answer --- it means the save changed nothing --- and is reported as such.
    """
    changes = {}
    for field in instance._meta.concrete_fields:
        name = field.name
        if name in _IGNORED_FIELDS:
            continue
        old = before.get(name)
        new = getattr(instance, name, None)
        if old == new:
            continue
        changes[name] = {"from": _stringify(old), "to": _stringify(new)}
    return changes


def snapshot(instance):
    """Capture the fields ``diff()`` needs, before an edit is applied."""
    return {field.name: getattr(instance, field.name, None) for field in instance._meta.concrete_fields}


def _client_ip(request):
    """The caller's address, trusting the proxy header only when configured.

    Render terminates TLS at its proxy and forwards the origin in
    ``X-Forwarded-For``. Taking the first hop is correct there and wrong
    anywhere else --- a client can set that header itself --- so the forwarded
    value is only read when the deployment has declared a proxy.
    """
    from django.conf import settings

    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record(
    request,
    action,
    *,
    organization=None,
    pharmacy=None,
    target=None,
    changes=None,
    note=None,
):
    """Append one audit entry. Never raises.

    ``target`` may be a model instance (its type and id are recorded) or a
    ``(type_name, id_value)`` pair for something that no longer exists.
    """
    try:
        context = None
        if request is not None:
            # Imported here rather than at module scope: ``org_context`` imports
            # this module's siblings, and a cycle would make the app fail to
            # load rather than fail to audit.
            from .org_context import resolve_org_context

            context = resolve_org_context(request)

        if organization is None and context is not None:
            organization = context.organization
        if pharmacy is None and context is not None:
            pharmacy = context.pharmacy

        actor = None
        actor_email = ""
        if context is not None:
            actor = context.user
            actor_email = context.actor_email
        elif request is not None and getattr(request.user, "is_authenticated", False):
            actor = request.user
            actor_email = getattr(request.user, "email", "") or getattr(request.user, "username", "")

        target_type = ""
        target_id = ""
        if isinstance(target, tuple) and len(target) == 2:
            target_type, target_id = str(target[0]), str(target[1])
        elif target is not None:
            target_type = target.__class__.__name__
            target_id = str(getattr(target, "pk", ""))

        entry = {
            "organization": organization,
            "pharmacy": pharmacy,
            "actor": actor,
            "actor_email": actor_email,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "changes": changes or {},
            "ip_address": _client_ip(request) if request is not None else None,
            "user_agent": (request.META.get("HTTP_USER_AGENT", "")[:300] if request is not None else ""),
            "request_id": (getattr(request, "request_id", "") if request is not None else ""),
        }
        if note is not None:
            entry["changes"] = {**entry["changes"], "_note": note}

        # An audit write joins the caller's transaction when there is one, so a
        # rollback removes the record of an action that did not happen. That is
        # the correct direction of failure: an entry describing rolled-back work
        # would make the trail misleading rather than merely incomplete.
        return AuditLog.objects.create(**entry)
    except Exception:  # noqa: BLE001 - auditing must never break the request
        logger.exception("audit write failed action=%s", action)
        return None


def record_async_safe(*args, **kwargs):
    """``record()`` for a caller already inside an atomic block.

    Same behaviour, except that a failure is contained with a savepoint so a
    broken audit write cannot poison an otherwise healthy transaction --- which
    is the one way an audit helper can take down a checkout.
    """
    try:
        with transaction.atomic():
            return record(*args, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("audit write failed inside a transaction")
        return None
