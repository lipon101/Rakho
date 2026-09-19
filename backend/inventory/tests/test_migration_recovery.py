"""Regression tests for the production migration recovery path.

The deploy crash these cover is Postgres-specific and cannot be reproduced on
SQLite: given a database whose schema is complete but whose `django_migrations`
rows are gone, Postgres fails the DDL with `relation "..." already exists`,
whereas SQLite emulates `ALTER TABLE` by rebuilding the table and the
migrations simply succeed. The recovery path is therefore never entered under
SQLite, which is exactly how a broken recovery once reached production.

So these tests drive the recovery *decision* directly -- `_can_recover` is the
code that decides whether a collided migration may be recorded as applied
without executing it -- and assert it over the whole real migration graph.

Uses `TestCase` (not `TransactionTestCase`): these tests delete rows from
`django_migrations`, and that mutation must be rolled back after each test or
every later test would run against a database with no migration history.
"""
from django.db import connection, migrations as dj_migrations
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.db.utils import ProgrammingError
from django.test import TestCase

from inventory.management.commands.stepwise_migrate import (
    Command,
    _NAME_ONLY_OPS,
)

# Operations that cannot collide with pre-existing DDL, so a migration made up
# only of these is executed for real rather than recovered. `RunPython` is
# included because a data migration body is opaque; a migration containing one
# is never auto-recovered, so it is not expected to be recoverable here.
_NON_COLLIDING_OPS = (
    dj_migrations.RunPython,
    dj_migrations.RunSQL,
    dj_migrations.AlterModelOptions,
) + _NAME_ONLY_OPS


class MigrationRecoveryTests(TestCase):
    def setUp(self):
        super().setUp()
        # Recreate the production state: schema fully applied, history gone.
        MigrationRecorder(connection).migration_qs.all().delete()
        executor = MigrationExecutor(connection)
        self.loader = executor.loader
        self.pending = [
            migration for migration, _backwards in executor.migration_plan(
                self.loader.graph.leaf_nodes(), clean_start=False
            )
        ]
        self.command = Command()
        self.command.verbosity = 0

    def _migration(self, app_label, name):
        return self.loader.graph.nodes[(app_label, name)]

    @staticmethod
    def _collision(app_label, name):
        # The shape of the error Postgres raises for a table that is already
        # there; the exact object does not matter to the decision.
        return ProgrammingError(
            f'relation "{app_label}_{name}" already exists'
        )

    def test_history_was_actually_wiped(self):
        """Guards the fixture: the whole point is that nothing is recorded."""
        self.assertEqual(len(self.pending), 24)
        self.assertFalse(MigrationRecorder(connection).migration_qs.exists())

    def test_every_structural_migration_can_be_recovered(self):
        """A schema-complete / history-empty database must recover cleanly.

        This is the regression that matters: if any migration that can collide
        with existing DDL is not recoverable, a production deploy dies on it.
        """
        not_recoverable = []
        for migration in self.pending:
            is_structural = any(
                not isinstance(op, _NON_COLLIDING_OPS)
                for op in migration.operations
            )
            if not is_structural:
                continue
            if not self.command._can_recover(
                migration, self._collision(migration.app_label, migration.name)
            ):
                not_recoverable.append(
                    f"{migration.app_label}.{migration.name}"
                )
        self.assertEqual(
            not_recoverable, [],
            "these migrations cannot be recovered on a schema-complete "
            "database, so a deploy would fail on them",
        )

    def test_removed_column_is_resolved_from_migration_history(self):
        """`contenttypes.0002` drops a column that is already gone in prod.

        `RemoveField` carries no `field=` in a migration file and the field has
        already left the current models, so the column name can only come from
        the historical project state. Resolving it is what makes this migration
        recoverable instead of fatal.
        """
        migration = self._migration(
            "contenttypes", "0002_remove_content_type_name"
        )
        remove_field = next(
            op for op in migration.operations
            if isinstance(op, dj_migrations.RemoveField)
        )
        field = self.command._historical_field(
            self.loader, migration, remove_field.model_name, remove_field.name
        )
        self.assertIsNotNone(
            field, "the removed column must be resolvable from history"
        )
        self.assertEqual(field.column, "name")
        self.assertTrue(self.command._can_recover(
            migration, self._collision("contenttypes", "0002")
        ))

    def test_opaque_data_migration_is_never_recorded_as_applied(self):
        """Only Django's own no-op forward may be skipped.

        `auth.0011` runs real Python, so if it ever collides the build must
        fail loudly rather than silently record it and lose the work.
        """
        opaque = self._migration("auth", "0011_update_proxy_permissions")
        self.assertFalse(self.command._can_recover(
            opaque, self._collision("auth", "0011")
        ))
        noop = self._migration(
            "contenttypes", "0002_remove_content_type_name"
        )
        self.assertTrue(
            any(isinstance(op, dj_migrations.RunPython) and
                op.code is dj_migrations.RunPython.noop
                for op in noop.operations),
            "contenttypes.0002 is expected to have a no-op forward",
        )

    def test_unrelated_database_error_is_not_recovered(self):
        """A genuine failure must never be mistaken for a recoverable one."""
        migration = self._migration("inventory", "0001_initial")
        for message in (
            'syntax error at or near "FROM"',
            "permission denied for table pharmacy",
            "current transaction is aborted",
        ):
            with self.subTest(message=message):
                self.assertFalse(
                    self.command._can_recover(migration, ProgrammingError(message))
                )
