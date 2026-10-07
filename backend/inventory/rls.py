"""Row-Level Security: the database's own copy of the tenancy rule.

The application already scopes every query through ``OrgContext`` --- a view
that has a context cannot accidentally read another tenant's rows, because the
context is the only scope it is given. This module adds the second lock: the
same rule, expressed as a PostgreSQL policy, so that a query which *does* forget
to scope still returns nothing.

Why two locks rather than one
-----------------------------
Code-level scoping is the primary defence and it is always on. RLS is the
backstop for the case the code cannot cover: a future view, a raw SQL report, a
``.raw()`` call, a data-migration script, or a compromised application role.
The two are deliberately independent --- RLS does not read Django's ORM state,
and the ORM does not read the policy --- so a bug in one is not a bug in both.

How the tenant is communicated
------------------------------
PostgreSQL policies read a session variable, ``app.current_org``. The value is
set with ``SET LOCAL``, which scopes it to the surrounding transaction: it is
discarded at commit or rollback, so a pooled connection cannot carry one
request's tenant into the next. That is the whole reason ``SET LOCAL`` is used
instead of ``SET`` --- a session-level ``SET`` on a connection that Django keeps
alive for ten minutes (``CONN_MAX_AGE``) would leak the previous request's
organisation to whoever used the connection next.

Because ``SET LOCAL`` needs a transaction to be scoped to, the middleware below
opens one for the request when RLS is active. Without that, each statement would
be its own implicit transaction and the setting would vanish before the view ran.

Why the migration does not FORCE the policy
-------------------------------------------
``ENABLE ROW LEVEL SECURITY`` makes the policy apply to every role *except* the
table's owner. That is the safe default: a deployment whose application connects
as the database owner (the common case on a managed Postgres) keeps working
exactly as before, and RLS starts protecting the moment the application is moved
onto the dedicated non-owner role that ``setup_rls_role`` creates. ``FORCE ROW
LEVEL SECURITY`` --- which extends the policy to the owner as well --- is
available behind ``RLS_FORCE`` for an operator who has already moved the
application onto the non-owner role and wants the owner covered too.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import connection, transaction

logger = logging.getLogger("inventory.rls")

#: The session variable the policies read. Namespaced with ``app.`` because
#: PostgreSQL reserves the unprefixed names for its own settings.
ORG_SETTING = "app.current_org"


def rls_active() -> bool:
    """True when RLS should be enforced for this process.

    Three conditions, all required: the operator turned it on, the database is
    PostgreSQL (the policies are a PostgreSQL feature --- SQLite has no
    equivalent and the migration is a no-op there), and a connection exists.
    """
    if not getattr(settings, "RLS_ENABLED", False):
        return False
    try:
        return connection.vendor == "postgresql"
    except Exception:  # pragma: no cover - no connection configured yet
        return False


def set_org_context(org_id) -> None:
    """Bind the current transaction to one organisation.

    Must be called inside a transaction --- ``SET LOCAL`` outside one has no
    effect to scope. The middleware guarantees that for a request; a management
    command or a background task must open its own ``transaction.atomic()``.

    The value is passed as a bound parameter rather than interpolated, so an
    organisation id can never be a SQL-injection vector even though it is a
    UUID today.
    """
    if not rls_active():
        return
    if org_id is None:
        clear_org_context()
        return
    with connection.cursor() as cursor:
        # ``set_config(name, value, is_local)`` is the parameterisable form of
        # ``SET LOCAL``; the plain statement cannot take a bound parameter.
        cursor.execute("SELECT set_config(%s, %s, true)", [ORG_SETTING, str(org_id)])


def clear_org_context() -> None:
    """Unbind the transaction, so the policy denies every tenant row.

    Called when a request resolves to no organisation. Denying is the correct
    outcome: an unauthenticated or organisation-less caller has no business
    reading a tenant table, and the policy's ``= NULL`` comparison is never true.
    """
    if not rls_active():
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config(%s, '', true)", [ORG_SETTING])


class RLSContextMiddleware:
    """Open a transaction per request so ``SET LOCAL`` has somewhere to live.

    Only active when RLS is on. When it is off --- the default --- the
    middleware is a pass-through and the request lifecycle is byte-for-byte what
    it was before this module existed, which is what keeps the existing 339
    tests meaningful.

    The transaction wraps the whole request, including DRF's authentication,
    which is what makes the ordering work: the view resolves its organisation
    *inside* the transaction, sets the session variable, and every query it then
    runs is filtered by the policy.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not rls_active():
            return self.get_response(request)
        with transaction.atomic():
            return self.get_response(request)
