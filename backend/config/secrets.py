"""Resolve deploy secrets from the encrypted store, falling back to the environment.

Why this exists
---------------
``scripts/secret_store.py`` can keep a secret encrypted on disk, but a store is
only useful if the application actually reads from it. This module is that
bridge: settings call :func:`resolve_secret` instead of ``os.environ.get``, and
get the value from the encrypted store when one is present, or from the
environment variable when it is not.

The fallback is the whole point of the design
---------------------------------------------
An existing deployment that has not migrated yet must keep working, so a missing
store is not an error --- it is simply "not set up here", and the environment
variable is used exactly as before. That keeps this an *additional* layer rather
than a replacement, which is what makes it safe to add to a running system.

A store that exists but will not open is different, and is treated differently
-----------------------------------------------------------------------------
A wrong passphrase or a tampered file is a real problem, not an absence. Falling
through to the environment variable would hide it --- the app would start, look
healthy, and quietly use a different secret than the operator believes. So the
failure is logged loudly and the environment variable is still used, because
refusing to boot over a secret-store problem would turn a configuration mistake
into an outage. The operator sees the warning; the service stays up.

Nothing here ever prints a value
--------------------------------
Only the *source* of a secret is ever logged ("encrypted store" or "environment
variable"), never the secret itself. A log line is the most likely place for a
credential to escape, because it is the one path nobody reviews.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

#: ``scripts/`` is not a package, so it is added to the path to import the store.
#: Imported defensively: the settings module must keep working with only the
#: standard library, because a deployment that fails to boot because a helper
#: could not be imported is a deployment that fails for the wrong reason.
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

try:
    import secret_store
except ImportError:  # pragma: no cover - only if the file is missing
    secret_store = None  # type: ignore[assignment]


def resolve_secret(name: str, env_var: str, default: str = "") -> str:
    """Return a secret, preferring the encrypted store over the environment.

    Order: the encrypted store (when one exists and opens), then the environment
    variable, then ``default``. The store wins because it is the path that keeps
    the value off the disk in plaintext and out of the process environment ---
    the environment is visible to anything that can read ``/proc``, and is
    inherited by every child process.

    ``name`` is the canonical store name (e.g. ``secret_store.SECRET_DATABASE_URL``);
    ``env_var`` is the variable that carries the same value in an environment
    that has not migrated to the store yet.
    """
    if secret_store is not None:
        try:
            store_path = secret_store.default_store_path()
            if store_path.exists():
                value = secret_store.load_secret_with_aliases(name, store_path=store_path)
                if value:
                    logger.info("Resolved %s from the encrypted store.", env_var)
                    return value
        except secret_store.SecretStoreError as exc:
            # Loud, but not fatal: a store that will not open is a problem to
            # fix, and the service must still start. The message is redacted on
            # the way out, because an error is the likeliest place to leak.
            logger.warning(
                "The encrypted secret store could not be read (%s); falling back to the %s environment variable. " "Fix the store or unset it so this warning stops.",
                secret_store.redact(str(exc)),
                env_var,
            )
        except Exception as exc:  # noqa: BLE001 - a settings import must never crash the app
            logger.warning("Unexpected error reading the encrypted secret store (%s); using %s from the environment.", type(exc).__name__, env_var)

    value = os.environ.get(env_var, "").strip()
    if value:
        logger.debug("Resolved %s from the environment variable.", env_var)
        return value
    return default
