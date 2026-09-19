"""Stepwise migration runner for production deploys.

Why: a partially-initialized managed Postgres (a previous deploy crashed
mid-migrate, or the database was seeded without django_migrations rows) makes a
plain `migrate` crash with `relation "..." already exists`. Faking an entire
app's history is not a general fix — it can mask a genuinely missing table.
The correct recovery is per-migration: each pending migration is attempted on
its own; one that fails only because the schema already contains its objects
is recorded as applied (--fake) and everything else is applied for real.

Safety rules:
- A migration is only recorded as applied when EVERY operation in it is
  fake-eligible AND the live schema verifies the migration's post-state
  actually holds. A fresh MigrationExecutor per attempt re-reads applied
  state from the database (no stale caches, no replayed predecessors).
- Verifiable ops: CreateModel/AddField (table/column present), AddIndex/
  AddConstraint/RenameIndex (name present), RenameField (new column present),
  AlterField/AlterModelOptions (table present), RemoveField (column ABSENT —
  absence proves it already ran), AlterUniqueTogether/AlterIndexTogether (a
  matching unique/index constraint exists).
- RunPython/RunSQL are never faked, with one audited exception: Django's
  contenttypes.0002 fills the `name` column and drops it in the same
  migration, so its net data effect is nil — once that column is verifiably
  absent the migration has demonstrably run. Data migrations in *our* apps
  would crash the build loudly instead of being masked.
- A step budget guards against infinite loops; anything unrecoverable fails
  the build with a clear error.

Migrations are authored and reviewed in the repo; we never run makemigrations
on the server, so production state is reproducible from version control.
"""
import logging

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, migrations as dj_migrations
from django.db import utils as db_utils
from django.core.management.sql import emit_post_migrate_signal
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

logger = logging.getLogger(__name__)

# Operations whose post-state can be verified against the live schema.
_SCHEMA_OPS = (
    dj_migrations.CreateModel,
    dj_migrations.AddField,
    dj_migrations.AddIndex,
    dj_migrations.AddConstraint,
    dj_migrations.RenameField,
    dj_migrations.RenameIndex,
    dj_migrations.AlterField,
    dj_migrations.AlterModelOptions,
    dj_migrations.RemoveField,
    dj_migrations.AlterUniqueTogether,
    dj_migrations.AlterIndexTogether,
)

# Django's contenttypes.0002 fills the `name` column and removes it in the
# same migration: zero net data effect. Its RemoveField verification proves
# the post-state, so recording it as applied is safe on an initialized DB.
_KNOWN_NOOP_DATA_MIGRATIONS = {("contenttypes", "0002_remove_content_type_name")}


class Command(BaseCommand):
    help = (
        "Apply pending migrations one at a time; record as applied (fake) "
        "only those whose schema is verified to already be in place. Data "
        "migrations are never faked."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "args", nargs="*", type=str,
            help="Optional app_label [migration_name] target (forward only).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the recovery plan without touching the database.",
        )
        # `manage.py migrate` accepts these (Django's migrate command declares
        # them itself; BaseCommand does not). This runner is a drop-in for
        # forward migration, so it must parse them too rather than crash.
        parser.add_argument(
            "--noinput", "--no-input", action="store_false",
            dest="interactive", default=True,
            help="Do not prompt for input (accepted for migrate compatibility).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        target_args = options.get("args") or []
        executor = MigrationExecutor(connection)
        targets = self._resolve_targets(executor, target_args)
        plan = executor.migration_plan(targets, clean_start=False)

        if not plan:
            self.stdout.write("No unapplied migrations; nothing to do.")
            return

        pending = [m for m, _backwards in plan]
        self.stdout.write(f"{len(pending)} migration(s) to apply:")
        for migration in pending:
            self.stdout.write(f"  - {migration.app_label}.{migration.name}")
        if dry_run:
            return

        max_steps = len(pending) + 5  # safety valve against infinite loops
        faked, applied = [], []
        for _step in range(max_steps):
            # Fresh executor every attempt: re-reads applied state from the
            # database so a migration recorded (for real or as fake) in the
            # previous iteration is never replayed.
            executor = MigrationExecutor(connection)
            current = executor.migration_plan(targets, clean_start=False)
            if not current:
                break
            migration = current[0][0]
            key = (migration.app_label, migration.name)
            try:
                executor.migrate([key])
            except (db_utils.ProgrammingError, db_utils.OperationalError) as exc:
                # A failed DDL statement can leave this connection inside an
                # aborted transaction (Postgres: "current transaction is
                # aborted, commands ignored until end of transaction block").
                # Verification below issues queries, so drop the connection
                # first — otherwise a recoverable collision would be judged
                # unrecoverable and fail the build for the wrong reason.
                self._reset_connection()
                if not self._can_recover(migration, exc):
                    raise CommandError(
                        f"{key[0]}.{key[1]} failed and is not safe to "
                        f"fake-recover: {exc}"
                    ) from exc
                MigrationRecorder(connection).record_applied(*key)
                faked.append(key)
                self.stdout.write(self.style.WARNING(
                    f"  {key[0]}.{key[1]}: schema already in place -> "
                    f"recorded as applied"
                ))
            else:
                applied.append(key)
                self.stdout.write(f"  {key[0]}.{key[1]}: applied")
        else:
            raise CommandError(
                "stepwise_migrate exceeded its step budget; aborting so the "
                "build fails loudly instead of looping."
            )

        if faked:
            self.stdout.write(self.style.SUCCESS(
                f"Recovered: {len(faked)} conflicting migration(s) recorded "
                f"as applied ({', '.join(f'{a}.{n}' for a, n in faked)}); "
                f"{len(applied)} applied for real."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"All migrations applied ({len(applied)})."
            ))

        # The `migrate` command emits post_migrate signals after applying
        # migrations; they populate contenttypes and auth permissions rows.
        # This runner drives the executor directly, so it must emit them
        # itself — a recovered DB would otherwise end up with empty
        # django_content_type / auth_permission tables.
        emit_post_migrate_signal(
            verbosity=options.get("verbosity", 1),
            interactive=False,
            db=connection.alias,
        )

    @staticmethod
    def _reset_connection():
        """Discard the current connection so the next query reconnects.

        Django reconnects lazily, so this is safe to call at any point where
        we are not inside a transaction we still need.
        """
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - reset must never raise
            logger.exception("Could not reset the database connection")

    # ── target resolution ──

    def _resolve_targets(self, executor, target_args):
        """Mimic `migrate`'s positional [app_label] [migration_name] targets
        (forward only; 'zero' is not supported by this recovery runner)."""
        if not target_args:
            return executor.loader.graph.leaf_nodes()
        app_label = target_args[0]
        if len(target_args) == 1:
            return [node for node in executor.loader.graph.leaf_nodes()
                    if node[0] == app_label]
        name = target_args[1]
        if name == "zero":
            raise CommandError(
                "stepwise_migrate does not support backwards targets ('zero')."
            )
        return [executor.loader.graph.nodes[(app_label, name)]]

    # ── recovery eligibility ──

    def _can_recover(self, migration, exc) -> bool:
        """A failure is recoverable when every operation is fake-eligible AND
        the live schema really is in the migration's post-state (so faking
        loses nothing)."""
        text = str(exc).lower()
        existing_object = (
            "already exists" in text
            # Postgres 42P16: index/constraint name already taken.
            or "42p16" in text
            or "duplicate" in text
            # sqlite: a historical model querying a column that a later
            # migration already removed (e.g. contenttypes.0002's RunPython).
            or "no such column" in text
            or "does not exist" in text
            # sqlite: RenameIndex whose source was already renamed (i.e. the
            # migration already ran) -> the source index is absent.
            or "no such index" in text
            or "no such table" in text
        )
        if not existing_object:
            return False

        has_data_op = any(isinstance(op, (dj_migrations.RunPython,
                                          dj_migrations.RunSQL))
                          for op in migration.operations)
        if has_data_op:
            if (migration.app_label, migration.name) not in _KNOWN_NOOP_DATA_MIGRATIONS:
                return False

        if not all(isinstance(op, (*_SCHEMA_OPS, dj_migrations.RunPython))
                   for op in migration.operations):
            return False
        try:
            return self._post_state_holds(migration)
        except Exception:  # noqa: BLE001 - never fake on a verification error
            logger.exception("Schema verification failed for %s.%s",
                             migration.app_label, migration.name)
            return False

    @staticmethod
    def _resolve_name(loader, app_label, name):
        """Follow later RenameIndex/RenameConstraint operations in the same
        app, so verifying a name from an older migration resolves to the name
        the live schema actually carries today."""
        renamed = True
        while renamed:
            renamed = False
            for (app, _migration_name), mig in loader.graph.nodes.items():
                if app != app_label:
                    continue
                for op in mig.operations:
                    if isinstance(op, dj_migrations.RenameIndex) and op.old_name == name:
                        name = op.new_name
                        renamed = True
                        break
                    if (rename_constraint := getattr(dj_migrations, "RenameConstraint", None)) \
                            and isinstance(op, rename_constraint) and op.old_name == name:
                        name = op.new_name
                        renamed = True
                        break
        return name

    def _post_state_holds(self, migration, loader=None) -> bool:
        """Verify against the live schema that every object this migration
        creates is present / every object it removes is absent."""
        if loader is None:
            loader = MigrationExecutor(connection).loader
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))

            def columns(table):
                return {f.name for f in
                        connection.introspection.get_table_description(cursor, table)}

            def constraints(table):
                return set(connection.introspection.get_constraints(cursor, table))

            for op in migration.operations:
                if isinstance(op, dj_migrations.AlterModelOptions):
                    continue
                if isinstance(op, dj_migrations.CreateModel):
                    model = apps.get_model(migration.app_label, op.name)
                    if model._meta.db_table not in tables:
                        return False
                elif isinstance(op, (dj_migrations.AddField,
                                     dj_migrations.RenameField)):
                    model = apps.get_model(migration.app_label, op.model_name)
                    table = model._meta.db_table
                    if table not in tables:
                        return False
                    name = (op.name if isinstance(op, dj_migrations.AddField)
                            else op.new_name)
                    field = model._meta.get_field(name)
                    if field.column not in columns(table):
                        return False
                elif isinstance(op, dj_migrations.RemoveField):
                    model = apps.get_model(migration.app_label, op.model_name)
                    table = model._meta.db_table
                    if table not in tables:
                        return False
                    if op.name in {f.name for f in model._meta.fields}:
                        # Current model state still has the field (it is
                        # removed by a later state migration); check the DB.
                        column = model._meta.get_field(op.name).column
                        if column in columns(table):
                            return False
                    else:
                        # Field already gone from models; post-state means the
                        # column must not be in the DB either.
                        historical = op.field
                        if historical.column in columns(table):
                            return False
                elif isinstance(op, (dj_migrations.AddIndex,
                                     dj_migrations.RenameIndex)):
                    model = apps.get_model(migration.app_label, op.model_name)
                    table = model._meta.db_table
                    if table not in tables:
                        return False
                    name = (op.index.name
                            if isinstance(op, dj_migrations.AddIndex)
                            else op.new_name)
                    name = self._resolve_name(loader, migration.app_label, name)
                    if name not in constraints(table):
                        return False
                elif isinstance(op, dj_migrations.AddConstraint):
                    model = apps.get_model(migration.app_label, op.model_name)
                    table = model._meta.db_table
                    if table not in tables:
                        return False
                    cname = self._resolve_name(loader, migration.app_label,
                                               op.constraint.name)
                    if cname not in constraints(table):
                        return False
                elif isinstance(op, dj_migrations.AlterField):
                    model = apps.get_model(migration.app_label, op.model_name)
                    if model._meta.db_table not in tables:
                        return False
                elif isinstance(op, (dj_migrations.AlterUniqueTogether,
                                     dj_migrations.AlterIndexTogether)):
                    model = apps.get_model(migration.app_label, op.name)
                    table = model._meta.db_table
                    if table not in tables:
                        return False
                    want_unique = isinstance(op, dj_migrations.AlterUniqueTogether)
                    field_sets = [list(t) for t in
                                  (op.unique_together if want_unique
                                   else op.index_together) if t]
                    if not field_sets:
                        continue  # cleared -> nothing to verify
                    all_constraints = connection.introspection.get_constraints(
                        cursor, table)
                    for fields in field_sets:
                        cols = [model._meta.get_field(f).column
                                for f in fields]
                        found = any(
                            (c.get("unique") if want_unique else True)
                            and list(c.get("columns") or []) == cols
                            for c in all_constraints.values()
                        )
                        if not found:
                            return False
                else:  # unknown op type -> do not fake
                    return False
        return True
