# Bangladesh Pharmacy API

Independent Django REST API for the Bangladesh pharmacy inventory/POS application. It keeps public medicine catalogue data separate from each pharmacy's operational stock.

## Production migrations (Render)

Deployed builds never run `makemigrations`; migrations are authored in the
repo and applied idempotently:

- `migrate_prod.py` (the `render.yaml` build command) tries a plain `migrate`
  first and falls back to `stepwise_migrate` on failure.
- `manage.py migrate` is rerouted to `stepwise_migrate` outside of tests, so
  even a stale dashboard build command self-heals. `--fake`, `--fake-initial`,
  `--plan` and `--prune` are passed through untouched.

### Why stepwise recovery exists

A partially-initialized managed Postgres (a previous deploy crashed
mid-migrate, the database moved hosts, or `django_migrations` was lost)
crashes a plain `migrate` with `relation "..." already exists`.
`stepwise_migrate` walks the pending migrations one at a time and, for each:

- **records it as applied without executing it** when its structural effect is
  already present in the live schema, or
- **executes it for real** otherwise.

Evidence is deliberately limited to **tables and columns**. Index and
constraint *names* are not used, because a later migration may legitimately
rename or drop them, so a missing name is not proof this migration never ran —
failing a build on a stale name would be a false alarm. Those names are
reported as warnings instead. Verification is therefore biased the way that
matters: it can refuse to fake, but it cannot fake something the schema does
not support.

Data migrations are never skipped unless their **forward function is Django's
own `noop`** — `contenttypes.0002` is the real case, where the function that
writes is the migration's *reverse*. This is detected from the operation
itself rather than from a list of migration names, so it stays correct when
Django rewrites its own migrations. Anything opaque is executed for real, and
an unrecognised operation or a genuine mismatch fails the build loudly instead
of being masked.

Before attempting anything, the runner drops the connection: a failed DDL
statement leaves Postgres in an aborted transaction, and without that reset the
verification queries would fail for the wrong reason and a recoverable
collision would look fatal.

Debug locally by replaying the failure state:

```bash
python manage.py stepwise_migrate --dry-run   # show the recovery plan
python manage.py migrate                      # self-healing in practice
python manage.py test inventory.tests.test_migration_recovery
```

**Caveat:** SQLite cannot reproduce this failure. It emulates `ALTER TABLE` by
rebuilding the table, so migrations succeed against an already-migrated schema
and the recovery path is never entered — which is how a broken recovery once
reached production. `inventory/tests/test_migration_recovery.py` therefore
drives the recovery *decision* directly across the whole migration graph.
