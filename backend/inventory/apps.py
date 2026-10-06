from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory"

    def ready(self):
        """Wire the cross-cutting hooks that must exist in every process.

        Two things happen here, and both were missing in a way that cannot be
        seen from the code that depends on them:

        * **Celery signals.** The Prometheus task counters are published by
          signal handlers, so a process that never connects them reports zero
          tasks. Connecting them from ``ready`` means the web worker, the Celery
          worker and the test runner all publish them.
        * **The metrics token.** ``inventory.metrics`` reads its configuration
          from the environment at import; mirroring it onto Django's settings
          here lets a view read ``settings.METRICS_TOKEN`` without reaching into
          the module's globals.

        Wrapped defensively: a monitoring hook that cannot be installed must not
        stop the application from starting.
        """
        try:
            from . import metrics

            metrics.publish_to_settings()
        except Exception:  # noqa: BLE001 - monitoring setup must never block boot
            pass

        try:
            from .celery_signals import connect_signals

            connect_signals()
        except Exception:  # noqa: BLE001
            pass
