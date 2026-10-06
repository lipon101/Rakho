"""Settings package.

Which module is loaded is decided by ``DJANGO_SETTINGS_MODULE`` alone, so an
environment never has to be inferred from the values inside it:

* ``config.settings.local``      --- a developer's machine (DEBUG, SQLite, no TLS)
* ``config.settings.production`` --- Render / any real deployment (TLS, Redis, hardened)
* ``config.settings.base``       --- shared; never loaded directly

``manage.py`` and ``wsgi.py`` both name a module explicitly, so this file's body
normally does nothing at all. Python always executes a package's ``__init__``
before its submodules, so ``import config.settings.local`` runs this file first;
the guard below makes sure that import has no side effects.

The one case this file *does* handle is ``config.settings`` being named as the
settings module itself --- a cron entry, a one-off script, ``django-admin``, or a
Deploy Button that only ever set ``DJANGO_SETTINGS_MODULE=config.settings``. It
then stands in for an environment module, and the choice is made so the *safe*
mistake is the one a forgotten variable produces: production, because a hardened
configuration on a laptop fails in a second, while a permissive one on the
internet exposes every tenant.
"""

import os


def _select_surrounding_module():
    """The environment module ``config.settings`` should stand for."""
    if os.environ.get("RENDER") or os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
        return "production"
    return "local" if os.environ.get("DEBUG", "").lower() == "true" else "production"


# A submodule was named explicitly: leave this package's namespace empty so the
# submodule's own values are the only ones in play. Without this guard,
# importing ``config.settings.local`` would also execute ``config.settings``,
# which would import *production* and trip its hardening checks --- the exact
# failure that made ``manage.py test`` unrunnable when this package was first
# introduced.
_named = os.environ.get("DJANGO_SETTINGS_MODULE", "")
if _named in ("", "config.settings"):
    # Stand in for the environment module. A conditional star-import is used
    # rather than assembling the namespace by hand: star-importing at module
    # level is legal (it is only forbidden inside a function), and it makes
    # every setting a real module global, so ``config.settings.SOME_SETTING``
    # resolves exactly as it did when this was a single module --- including for
    # tools that read ``dir(config.settings)``.
    if _select_surrounding_module() == "production":
        from .production import *  # noqa: F401,F403
    else:
        from .local import *  # noqa: F401,F403
