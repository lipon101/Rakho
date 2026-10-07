import os

from django.core.wsgi import get_wsgi_application

# WSGI is only ever served from a real deployment, so the hardened settings
# are the correct default here. ``render.yaml`` also sets the module
# explicitly, so this is a backstop rather than the primary switch.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
application = get_wsgi_application()
