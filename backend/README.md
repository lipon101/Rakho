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
mid-migrate, or the database was seeded without `django_migrations` rows)
crashes a plain `migrate` with `relation "..." already exists`.
`stepwise_migrate` applies each pending migration on its own; one that fails
only because the schema already contains its objects is recorded as applied
(`--fake`) and everything else is applied for real. Before recording anything
it verifies the live schema actually holds the migration's post-state (tables,
columns, index/constraint names, removed columns absent). Data migrations
(`RunPython`/`RunSQL`) are never faked — with one audited exception: Django's
own `contenttypes.0002`, whose only data operation is a no-op forward pass.
Anything unverifiable fails the build loudly instead of being masked.

Debug locally by replaying the failure state:

```bash
python manage.py stepwise_migrate --dry-run   # show the recovery plan
python manage.py migrate                      # self-healing in practice
```
