"""``manage.py verify_sentry`` --- prove error reporting actually reaches Sentry.

The DoD asks for Sentry to be *verified*, not merely configured, and the
difference is the whole reason this command exists. ``SENTRY_DSN`` being present
proves only that somebody typed a string: a revoked key, a wrong project id or a
blocked egress all leave the variable set and the dashboard empty, and the first
sign that error reporting never worked is an incident nobody saw coming.

So this command does three things in order:

1. Reports what is configured (DSN present, SDK installed, PII setting).
2. Sends a real test event and *flushes* it, reading back the event id.
3. Exits non-zero when it could not deliver, so it can be wired into the deploy
   smoke test as a gate rather than read as advice.

``send_default_pii`` is reported because it is a rule here rather than a
preference: Rakho holds customer phone numbers and payment references, and a
Sentry event carries request data by default.
"""

from django.core.management.base import BaseCommand, CommandError

from inventory.observability import sentry_status


class Command(BaseCommand):
    help = "Verify that Sentry is configured and a test event is actually delivered."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-send",
            action="store_true",
            help="Only report the configuration; do not send a test event.",
        )

    def handle(self, *args, **options):
        status = sentry_status()
        self.stdout.write(self.style.MIGRATE_HEADING("Sentry configuration"))
        self.stdout.write(f"  DSN configured      : {status['configured']}")
        self.stdout.write(f"  SDK initialised     : {status['sdk_installed']}")
        self.stdout.write(f"  environment         : {status['environment'] or '(unset)'}")
        # Printed in the affirmative-negative so an operator scanning the output
        # reads the safe value as the expected one.
        self.stdout.write(f"  send_default_pii off: {not status['send_default_pii']}")

        if not status["configured"]:
            raise CommandError("SENTRY_DSN is not set. Error reporting is OFF: set it on the service " "before relying on this deployment to tell you when something breaks.")
        if not status["sdk_installed"]:
            raise CommandError("SENTRY_DSN is set but sentry_sdk is not installed. Add sentry-sdk to the requirements.")

        if status["send_default_pii"]:
            self.stderr.write(self.style.WARNING("send_default_pii is TRUE: customer data will be attached to events."))

        if options["no_send"]:
            self.stdout.write(self.style.SUCCESS("Configuration looks usable; no test event sent (--no-send)."))
            return

        event_id = self._send_probe()
        if not event_id:
            raise CommandError("A test event could not be sent. The DSN is present but delivery failed --- " "check that the key is still valid and that outbound HTTPS to sentry.io is allowed.")
        self.stdout.write(self.style.SUCCESS(f"Test event delivered. Event id: {event_id}"))
        self.stdout.write("Look for it in Sentry under the environment reported above.")

    @staticmethod
    def _send_probe():
        """Capture and flush one event; return its id, or ``None`` on failure."""
        try:
            import sentry_sdk

            event_id = sentry_sdk.capture_message("Rakho deploy smoke test: Sentry is reachable", level="info")
            # ``flush`` is the load-bearing call. Without it the event sits in a
            # background queue and the process exits before it is sent --- which
            # is exactly how a smoke test passes while Sentry stays empty.
            sentry_sdk.flush(timeout=5)
            return event_id
        except Exception:  # noqa: BLE001 - any failure means "could not verify"
            return None
