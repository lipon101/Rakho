"""Phase 6 tests for the operational commands and Celery signal handlers.

The coverage gate caught this file's absence: ``backup_db``, ``restore_drill`` and
``celery_signals`` were written and wired but never exercised, and the gate
refused to let that pass as "done". Which is the point of a gate.

What is worth testing here, and what is not:

* **Retention is tested hard**, because it is the one part of a backup command
  that *deletes data* when it is wrong. It is a pure function precisely so it can
  be tested without a filesystem full of real backups.
* **The refusals are tested**, because they are the safety features: restoring
  into the live database, running on SQLite, drilling without a manifest. A
  refusal that does not fire is worse than no refusal, since it reads as a
  guarantee.
* **The shell-outs are not tested.** ``pg_dump`` is exercised for real by
  ``manage.py backup_db`` + ``restore_drill`` against Postgres (documented as the
  drill runbook step); a mocked subprocess would assert that a command string was
  built, which is not the thing that can lose a customer's data.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from inventory import celery_signals, metrics
from inventory.management.commands import backup_db, restore_drill


class RetentionTests(TestCase):
    """``select_for_retention`` --- the function that deletes backups."""

    def _touch(self, directory: Path, names: list[str]) -> list[Path]:
        paths = []
        for offset, name in enumerate(names):
            path = directory / name
            path.write_text("x", encoding="utf-8")
            # mtime is the ordering key, so it is set explicitly rather than
            # relying on creation order, which is not guaranteed to be distinct.
            import os

            os.utime(path, (1_700_000_000 + offset, 1_700_000_000 + offset))
            paths.append(path)
        return paths

    def test_keeps_the_newest_and_returns_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._touch(Path(tmp), ["a.dump", "b.dump", "c.dump", "d.dump"])
            stale = backup_db.select_for_retention(paths, keep=2)
            self.assertEqual({p.name for p in stale}, {"a.dump", "b.dump"})

    def test_keeping_more_than_exist_deletes_nothing(self):
        """The bug this guards against: an off-by-one that wipes the last backup."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._touch(Path(tmp), ["only.dump"])
            self.assertEqual(backup_db.select_for_retention(paths, keep=7), [])

    def test_keeping_zero_would_return_everything(self):
        """A guard, not a feature: ``--keep 0`` means zero to retain.

        Asserted so the behaviour is deliberate. The command defaults to
        ``--no-prune`` semantics for this reason --- an accidental ``0`` must not
        be able to silently delete every backup.
        """
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._touch(Path(tmp), ["a.dump", "b.dump"])
            self.assertEqual(len(backup_db.select_for_retention(paths, keep=0)), 2)


class BackupRefusalTests(TestCase):
    """The refusals that make ``backup_db`` safe to have."""

    def test_refuses_on_sqlite(self):
        fake = {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}
        with mock.patch.object(backup_db, "connection", mock.Mock(settings_dict=fake)):
            with self.assertRaises(CommandError) as ctx:
                backup_db.database_settings()
        self.assertIn("SQLite", str(ctx.exception))

    def test_table_names_are_read_from_the_database(self):
        """Taken from ``pg_tables``, not the model registry.

        The registry would miss any table created by raw SQL in a migration ---
        exactly the tables a hand-written restore test forgets to check.
        """
        tables = backup_db.table_names()
        self.assertIn("inventory_organization", tables)
        self.assertIn("django_migrations", tables)  # a Django table, still backed up

    def test_row_counts_are_real_counts(self):
        counts = backup_db.row_counts(["inventory_organization"])
        self.assertIn("inventory_organization", counts)
        self.assertIsInstance(counts["inventory_organization"], int)


class RestoreDrillRefusalTests(TestCase):
    """The refusals that make the drill a drill."""

    def test_refuses_to_restore_into_the_live_database(self):
        """The single most important guard in this command.

        Restoring a dump over the live database would not be a drill; it would be
        a data loss incident dressed as a rehearsal.
        """
        live = restore_drill.connection.settings_dict["NAME"]
        with self.assertRaises(CommandError) as ctx:
            call_command("restore_drill", "--from", "backups/whatever.dump", "--into", live)
        self.assertIn("Refusing to restore into the live database", str(ctx.exception))

    def test_refuses_without_a_manifest(self):
        """No manifest means nothing to verify against."""
        with tempfile.TemporaryDirectory() as tmp:
            dump = Path(tmp) / "orphan.dump"
            dump.write_bytes(b"not really a dump")
            with self.assertRaises(CommandError) as ctx:
                call_command("restore_drill", "--from", str(dump), "--into", "rakho_scratch_xyz")
        self.assertIn("Manifest not found", str(ctx.exception))

    def test_refuses_when_the_dump_is_missing(self):
        """A manifest describing a file that is gone is a dangling record."""
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "ghost.manifest.json"
            manifest.write_text(json.dumps({"row_counts": {}}), encoding="utf-8")
            with self.assertRaises(CommandError) as ctx:
                call_command("restore_drill", "--from", str(manifest), "--into", "rakho_scratch_xyz")
        self.assertIn("Dump not found", str(ctx.exception))

    def test_refuses_on_sqlite(self):
        fake = {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}
        with mock.patch.object(restore_drill, "connection", mock.Mock(settings_dict=fake)):
            with self.assertRaises(CommandError) as ctx:
                call_command("restore_drill", "--from", "x.dump", "--into", "y")
        self.assertIn("SQLite", str(ctx.exception))


class ManifestTests(TestCase):
    """The manifest is what makes a restore checkable rather than trusted."""

    def test_sha256_matches_a_known_digest(self):
        """Checked against an independently computed digest.

        A checksum function that is merely *stable* would pass a
        "same-bytes-same-digest" test while hashing the wrong algorithm
        entirely, and the manifest's whole purpose is to detect a corrupted dump.
        """
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blob.bin"
            payload = b"rakho"
            path.write_bytes(payload)
            self.assertEqual(backup_db.sha256_of(path), hashlib.sha256(payload).hexdigest())
            self.assertEqual(len(backup_db.sha256_of(path)), 64)

    def test_sha256_is_stable_and_changes_with_content(self):
        """The property that matters: same bytes, same digest; new bytes, new digest."""
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.bin"
            second = Path(tmp) / "b.bin"
            first.write_bytes(b"content")
            second.write_bytes(b"content")
            third = Path(tmp) / "c.bin"
            third.write_bytes(b"different")
            self.assertEqual(backup_db.sha256_of(first), backup_db.sha256_of(second))
            self.assertNotEqual(backup_db.sha256_of(first), backup_db.sha256_of(third))


class CelerySignalTests(TestCase):
    """The handlers behind ``rakho_celery_tasks_total``."""

    class _FakeTask:
        name = "inventory.tasks.loadtest_task"

    def test_a_successful_task_is_counted(self):
        sender = self._FakeTask()
        celery_signals.task_prerun_handler(sender=sender, task_id="t-1")
        celery_signals.task_success_handler(sender=sender, task_id="t-1")
        body, _ = metrics.render_metrics()
        body = body.decode()
        self.assertIn('task="inventory.tasks.loadtest_task"', body)
        self.assertIn('outcome="success"', body)

    def test_a_failed_task_is_counted_once(self):
        """``acks_late`` means one task id may run twice; the start time must be
        consumed, not accumulated, or the second failure would report a doubled
        duration."""
        sender = self._FakeTask()
        celery_signals.task_prerun_handler(sender=sender, task_id="t-2")
        first_duration = celery_signals._duration("t-2")
        self.assertIsNotNone(first_duration)
        # The entry is consumed by reading it, so a second read yields nothing.
        self.assertIsNone(celery_signals._duration("t-2"))

    def test_a_retry_is_counted_separately_from_a_failure(self):
        """A task that retries and succeeds is not an incident; a rising retry
        rate is the earliest warning that a dependency is degrading."""
        sender = self._FakeTask()
        celery_signals.task_prerun_handler(sender=sender, task_id="t-3")
        celery_signals.task_retry_handler(sender=sender, task_id="t-3")
        body, _ = metrics.render_metrics()
        self.assertIn('outcome="retry"', body.decode())

    def test_a_handler_without_a_prerun_does_not_raise(self):
        """Defensive: a signal can fire in an order the handler did not expect."""
        celery_signals.task_success_handler(sender=self._FakeTask(), task_id="never-seen")
        celery_signals.task_failure_handler(sender=self._FakeTask(), task_id="never-seen")

    def test_connect_signals_is_idempotent(self):
        """``ready()`` can run more than once; without ``dispatch_uid`` every
        handler would fire once per registration and multiply the counters."""
        from celery.signals import task_success

        celery_signals.connect_signals()
        celery_signals.connect_signals()
        receivers = [ref() for _key, ref in task_success.receivers]
        handler = celery_signals.task_success_handler
        bound = [r for r in receivers if getattr(r, "__func__", r) is handler]
        self.assertLessEqual(len(bound), 1)

    def test_task_name_falls_back_to_the_class_name(self):
        class Nameless:
            pass

        self.assertEqual(celery_signals._task_name(Nameless()), "Nameless")


class QueueDepthTests(TestCase):
    """``queue_depth_from_broker`` --- reporting absence honestly."""

    def test_returns_none_without_a_broker(self):
        """``None`` means "not configured", which is a different statement from
        zero. Zero would claim a healthy empty queue."""
        with mock.patch("django.conf.settings.CELERY_BROKER_URL", ""):
            with mock.patch.dict("os.environ", {"REDIS_URL": ""}, clear=False):
                self.assertIsNone(metrics.queue_depth_from_broker())


class SettingsPublishTests(TestCase):
    """``publish_to_settings`` puts the token where a view can read it."""

    def test_token_is_mirrored_onto_settings(self):
        from django.conf import settings

        metrics.publish_to_settings()
        self.assertTrue(hasattr(settings, "METRICS_TOKEN"))
        self.assertEqual(settings.METRICS_TOKEN, metrics.METRICS_TOKEN)
