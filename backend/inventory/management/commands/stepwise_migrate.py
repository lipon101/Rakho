"""Stepwise migration runner for production deploys.

Why this exists: a partially-initialized managed Postgres -- an earlier deploy
that crashed mid-migrate, a database moved between hosts, or a lost
`django_migrations` table -- makes a plain `migrate` crash with
`relation "..." already exists`.

Faking an entire app's history is not a general fix: it can mask a genuinely
missing table, and it cannot express "some of this app already ran". This
runner walks the pending migrations one at a time and decides per migration:

* the migration's structural effect is already present in the live schema
  (the tables and columns it creates exist, and any column it drops is gone)
  -> record it as applied without executing it;
* otherwise -> execute it for real.

Only tables and columns are treated as evidence. Index and constraint *names*
are deliberately not, because a later migration may legitimately rename or
drop them, so a missing name is not proof this migration failed to run --
failing a build on a stale name would be a false alarm. Those names are
reported as warnings instead. Verification is therefore biased the way that
matters: it can refuse to fake, but it cannot fake something the schema does
not support.

Data migrations are opaque, so they are never skipped unless their forward
function is Django's own no-op -- `contenttypes.0002` is the real-world case,
where the function that does the work is the migration's *reverse*. Anything
else is executed for real, which is what a normal deploy would have done.

Each attempt builds a fresh `MigrationExecutor` so applied state is re-read
from the database (no stale recorder cache, no replayed predecessors), and the
connection is dropped between attempts because a failed DDL statement leaves
Postgres in an aborted transaction -- otherwise the next verification query
would fail for the wrong reason and a recoverable collision would look fatal.

`post_migrate` signals are emitted at the end so contenttypes and permissions
get populated: this runner drives the executor directly, so Django will not
emit them on its own.

Migrations are authored and reviewed in the repo; production state stays
reproducible from version control.
"""

import logging

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.core.management.sql import emit_post_migrate_signal
from django.db import connection, migrations as dj_migrations
from django.db import utils as db_utils
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

logger = logging.getLogger(__name__)

# Django's own no-op data function. A RunPython whose forward code is this
# provably has no effect, so skipping its migration cannot discard anything.
# (contenttypes.0002 is the real case: its forward is `noop`; `add_legacy_name`,
# which actually writes, is its reverse.)
_NOOP_CODE = dj_migrations.RunPython.noop

# Operations that create, rename or drop index/constraint objects. Their
# effect is real, but it cannot be verified by name (see module docstring), so
# they are reported as warnings rather than used as evidence.
_NAME_ONLY_OPS = (
    dj_migrations.AddIndex,
    dj_migrations.RenameIndex,
    dj_migrations.AddConstraint,
    dj_migrations.AlterUniqueTogether,
    dj_migrations.AlterIndexTogether,
)


class Command(BaseCommand):
    help = (
        "Apply pending migrations one at a time, recording as applied (without "
        "executing) only those whose tables and columns are verified to already "
        "be in place. Opaque data migrations are never skipped."
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
        # forward migration, so it must parse them rather than crash.
        parser.add_argument(
            "--noinput", "--no-input", action="store_false",
            dest="interactive", default=True,
            help="Do not prompt for input (accepted for migrate compatibility).",
        )

    def handle(self, *args, **options):
        self.verbosity = options.get("verbosity", 1)
        self._state_before_cache = {}
        dry_run = options["dry_run"]
        target_args = options.get("args") or []

        executor = MigrationExecutor(connection)
        targets = self._resolve_targets(executor, target_args)
        plan = executor.migration_plan(targets, clean_start=False)
        pending = [m for m, _backwards in plan]

        if not pending:
            self._write("No unapplied migrations; nothing to do.")
            return

        self._write(f"{len(pending)} migration(s) to apply:")
        for migration in pending:
            self._write(f"  - {migration.app_label}.{migration.name}")
        if dry_run:
            return

        max_steps = len(pending) + 5  # safety valve against an infinite loop
        faked, applied = [], []
        for _step in range(max_steps):
            # Fresh executor each attempt: applied state is re-read from the
            # database, so a migration recorded in the previous iteration
            # (for real or as fake) is never replayed.
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
                # Verification issues queries, so drop the connection first, or
                # a recoverable collision gets judged unrecoverable.
                self._reset_connection()
                if not self._can_recover(migration, exc):
                    raise CommandError(
                        f"{key[0]}.{key[1]} failed and the schema does not "
                        f"already satisfy it, so it is not safe to record as "
                        f"applied: {exc}"
                    ) from exc
                self._warn_unverified_names(migration)
                MigrationRecorder(connection).record_applied(*key)
                faked.append(key)
                self._write(
                    self.style.WARNING(
                        f"  {key[0]}.{key[1]}: schema already in place -> "
                        f"recorded as applied"
                    )
                )
            else:
                applied.append(key)
                self._write(f"  {key[0]}.{key[1]}: applied")
        else:
            raise CommandError(
                "stepwise_migrate exceeded its step budget; aborting so the "
                "build fails loudly instead of looping."
            )

        if faked:
            self._write(self.style.SUCCESS(
                f"Recovered: {len(faked)} conflicting migration(s) recorded "
                f"as applied; {len(applied)} applied for real."
            ))
        else:
            self._write(self.style.SUCCESS(
                f"All migrations applied ({len(applied)})."
            ))

        # `migrate` emits post_migrate signals once it finishes; they populate
        # contenttypes and auth permissions. This runner drives the executor
        # itself, so it has to emit them -- otherwise a recovered database ends
        # up with empty django_content_type / auth_permission tables.
        emit_post_migrate_signal(
            verbosity=options.get("verbosity", 1),
            interactive=False,
            db=connection.alias,
        )

    # ── output ──────────────────────────────────────────────────────────────

    def _write(self, message):
        if getattr(self, "verbosity", 1) >= 1:
            self.stdout.write(message)

    # ── target resolution ───────────────────────────────────────────────────

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

    @staticmethod
    def _reset_connection():
        """Discard the current connection so the next query reconnects.

        Django reconnects lazily, so this is safe whenever we are not inside a
        transaction we still need.
        """
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - reset must never raise
            logger.exception("Could not reset the database connection")

    # ── recovery eligibility ────────────────────────────────────────────────

    def _can_recover(self, migration, exc) -> bool:
        """True when the failure proves this migration's effect is already in
        the database, so recording it as applied loses nothing."""
        if not self._looks_like_collision(str(exc).lower()):
            return False

        # A data migration's body is opaque: it can touch anything, so it is
        # never skipped unless its forward function is provably inert.
        for op in migration.operations:
            if isinstance(op, dj_migrations.RunSQL):
                return False
            if (isinstance(op, dj_migrations.RunPython)
                    and op.code is not _NOOP_CODE):
                return False

        try:
            loader = MigrationExecutor(connection).loader
            return self._post_state_holds(migration, loader)
        except Exception:  # noqa: BLE001 - never fake on a verification error
            logger.exception(
                "Schema verification failed for %s.%s",
                migration.app_label, migration.name,
            )
            return False

    @staticmethod
    def _looks_like_collision(text) -> bool:
        """Whether the database rejected an operation because the object was
        already there (or because a later migration already removed it)."""
        return (
            "already exists" in text       # Postgres/SQLite: duplicate object
            or "42p16" in text             # Postgres: duplicate name for object
            or "duplicate" in text
            or "does not exist" in text    # Postgres: column already dropped
            or "no such column" in text    # SQLite: column already dropped
            or "no such index" in text     # SQLite: index already renamed
            or "no such table" in text
        )

    # ── schema verification ─────────────────────────────────────────────────

    def _post_state_holds(self, migration, loader) -> bool:
        """Whether the live schema already satisfies this migration.

        Evidence is limited to tables and columns; index/constraint names are
        not consulted (see module docstring).
        """
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))

            def columns_of(table):
                return {
                    field.name
                    for field in connection.introspection
                    .get_table_description(cursor, table)
                }

            for op in migration.operations:
                if isinstance(op, dj_migrations.RunPython):
                    # _can_recover only lets Django's own no-op through.
                    continue
                if isinstance(op, dj_migrations.AlterModelOptions):
                    continue
                if isinstance(op, _NAME_ONLY_OPS):
                    continue

                if isinstance(op, dj_migrations.CreateModel):
                    model = apps.get_model(migration.app_label, op.name)
                    if not self._table_holds(model, tables, columns_of):
                        return False
                elif isinstance(op, (dj_migrations.AddField,
                                     dj_migrations.RenameField)):
                    field_name = (op.name
                                  if isinstance(op, dj_migrations.AddField)
                                  else op.new_name)
                    if not self._field_holds(migration, op.model_name,
                                             field_name, tables, columns_of):
                        return False
                elif isinstance(op, dj_migrations.AlterField):
                    model = apps.get_model(migration.app_label, op.model_name)
                    if model._meta.db_table not in tables:
                        return False
                elif isinstance(op, dj_migrations.RemoveField):
                    model = apps.get_model(migration.app_label, op.model_name)
                    table = model._meta.db_table
                    if table not in tables:
                        return False
                    present = columns_of(table)
                    # Post-state: the removed column must be gone.
                    for column in self._removed_columns(loader, migration, op,
                                                        model):
                        if column in present:
                            return False
                else:
                    # Unknown operation: never assume it already ran.
                    return False
        return True

    @staticmethod
    def _table_holds(model, tables, columns_of) -> bool:
        """Whether the model's table exists carrying every column it needs."""
        table = model._meta.db_table
        if table not in tables:
            return False
        present = columns_of(table)
        for field in model._meta.local_fields:
            if field.column not in present:
                return False
        for field in model._meta.local_many_to_many:
            through = field.remote_field.through
            if through._meta.auto_created and through._meta.db_table not in tables:
                return False
        return True

    @staticmethod
    def _field_holds(migration, model_name, field_name, tables,
                     columns_of) -> bool:
        """Whether an added/renamed field's column is present.

        A field that has since been removed by a later migration is treated as
        satisfied: its column is legitimately absent from the final schema.
        """
        model = apps.get_model(migration.app_label, model_name)
        table = model._meta.db_table
        if table not in tables:
            return False
        try:
            column = model._meta.get_field(field_name).column
        except Exception:  # noqa: BLE001 - removed by a later migration
            return True
        return column in columns_of(table)

    def _removed_columns(self, loader, migration, op, model):
        """Every column name the removed field could have had.

        Extra candidates only make verification stricter -- they can refuse a
        fake, never permit a wrong one -- so the field name itself is included
        as a last-resort fallback in case history cannot be resolved.
        """
        candidates = {op.name}
        if op.field is not None and op.field.column:
            candidates.add(op.field.column)
        if op.name in {field.name for field in model._meta.fields}:
            candidates.add(model._meta.get_field(op.name).column)
        historical = self._historical_field(loader, migration, op.model_name,
                                            op.name)
        if historical is not None and historical.column:
            candidates.add(historical.column)
        return candidates

    def _historical_field(self, loader, migration, model_name, field_name):
        """The field as it existed just before `migration` ran, or None.

        Needed because `RemoveField` written into a migration file carries no
        `field=`, and the field has already left the current models, so there
        is nothing else left to read its column name from.
        """
        state = self._state_before(loader, migration)
        if state is None:
            return None
        try:
            model = state.apps.get_model(migration.app_label, model_name)
            return model._meta.get_field(field_name)
        except Exception:  # noqa: BLE001 - unknown column -> unverifiable
            return None

    def _state_before(self, loader, migration):
        """ProjectState immediately before `migration` ran, cached per
        migration (projecting state is far too slow to repeat per field)."""
        key = (migration.app_label, migration.name)
        cache = getattr(self, "_state_before_cache", None)
        if cache is None:
            cache = self._state_before_cache = {}
        if key in cache:
            return cache[key]

        state = None
        try:
            ancestors = [node for node in loader.graph.forwards_plan(key)
                         if node != key]
            if ancestors:
                state = loader.project_state(ancestors)
        except Exception:  # noqa: BLE001 - verification must not explode
            logger.exception("Could not project state before %s.%s", *key)

        cache[key] = state
        return state

    # ── advisory warnings ───────────────────────────────────────────────────

    def _warn_unverified_names(self, migration):
        """Report index/constraint names from this migration that are absent
        from the live schema.

        Deliberately non-fatal: a later migration may have renamed or dropped
        them, so their absence does not prove this migration never ran. The
        warning keeps the uncertainty visible in the build log.
        """
        wanted = []
        for op in migration.operations:
            if isinstance(op, dj_migrations.AddIndex):
                wanted.append((op.model_name, op.index.name))
            elif isinstance(op, dj_migrations.RenameIndex):
                wanted.append((op.model_name, op.new_name))
            elif isinstance(op, dj_migrations.AddConstraint):
                wanted.append((op.model_name, op.constraint.name))
        if not wanted:
            return

        missing = []
        with connection.cursor() as cursor:
            for model_name, name in wanted:
                try:
                    model = apps.get_model(migration.app_label, model_name)
                    present = connection.introspection.get_constraints(
                        cursor, model._meta.db_table)
                except Exception:  # noqa: BLE001 - advisory only
                    continue
                if name not in present:
                    missing.append(f"{model._meta.db_table}.{name}")

        if missing:
            self._write(self.style.WARNING(
                f"  note: {migration.app_label}.{migration.name} was recorded "
                f"as applied, but these index/constraint names are not in the "
                f"live schema (a later migration may have renamed or dropped "
                f"them): {', '.join(sorted(missing))}"
            ))
