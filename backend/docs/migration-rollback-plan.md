# Rakho — migration & rollback plan

A migration is the only change to Rakho that can lose customer data, so the
rules that govern them are stricter than the ones that govern code. This
document states the rules, the procedure, and what to do when a migration has
already gone wrong.

Last reviewed: 2026-10-06.

---

## The one rule

**Every migration must be backward compatible with the previous release for one
full deploy cycle.**

That single rule is what makes rolling back the application safe: the previous
release can still serve traffic against the migrated schema, so a bad deploy is
reverted by pushing the old commit, with no database work at all. Everything
below is a consequence of it.

Practically, that means:

* **Adding** a column is safe (nullable, or with a default).
* **Adding** a table or an index is safe.
* **Dropping** a column is *not* safe in the same release. Deploy in three steps:
  (1) stop writing to it, (2) deploy, (3) drop it in a later release once no
  running code reads it.
* **Renaming** a column is never safe in one step. It is an add, a backfill, a
  switch, and a later drop — four releases.
* **Changing a column's type** follows the same shape as a rename: add the new
  column, backfill, switch reads, drop later.
* **Adding a NOT NULL column without a default** fails on a table with rows, and
  will take the deploy down with it.

## Before every migration

```bash
# 1. A backup from the last hour. Non-negotiable.
python manage.py backup_db --label pre-<ticket>

# 2. See exactly what will run, and confirm it is additive.
python manage.py sqlmigrate inventory <migration> | less

# 3. Confirm no model drift has crept in.
python manage.py makemigrations --check --dry-run     # must print "No changes detected"
```

Check the three questions against the output of step 2:

1. Does it **drop** anything? If yes, it is a later release.
2. Does it **lock** a large table (adding a NOT NULL default on a big table, or an
   index without `CONCURRENTLY`)? If yes, schedule it, do not ship it in the
   middle of a working day.
3. Does it **backfill** in the same migration? Move the backfill into a separate
   data migration so a failure in it can be retried without re-running the
   schema change.

## During

Run migrations **before** the new code serves:

```bash
python manage.py migrate --noinput
```

Never run `migrate` from more than one instance at once. The migration table
makes a second runner wait, but the wait turns into a deploy timeout on a slow
migration, and a timed-out deploy that retries is how the same migration gets
launched twice.

## Rolling back the application (the fast path — use this)

```bash
git checkout <previous-sha>          # the SHA recorded before the deploy
# redeploy, then restart the web process and the worker
```

No database change. This is the correct first response to any bad deploy,
including one caused by a migration, because the schema was left compatible.

## Rolling back a migration (the slow path)

Only when the migration itself is the fault — for example, it dropped a column
that was still needed, or a backfill wrote wrong values.

```bash
python manage.py showmigrations inventory        # find the target migration
python manage.py migrate inventory <target>
```

Then verify, in this order:

1. `python manage.py migrate --plan` shows nothing unexpected queued.
2. The application's own suite runs green against the restored schema:
   `python manage.py test inventory`.
3. **Row counts and spot values match the backup.** `restore_drill` does exactly
   this comparison against a backup; use it rather than trusting that `migrate`
   printed no errors.

If the reverse migration does **not** exist (Django cannot auto-reverse a dropped
column), the only path is a restore:

```bash
python manage.py restore_drill --from <backup> --into scratch_db --verify   # rehearse first
```

Rehearse into a scratch database. A restore rehearsed directly into production
is not a plan; it is a second incident.

## The Phase 5 exception (Row-Level Security)

The RLS migration is the one that behaves unlike the others, and it is worth
stating separately: it **adds policies without changing any data**, so it is
additive and reversible in the usual way. The risk is not in the migration but
in the role move that follows it — if the application is switched to the
non-owner `rakho_app` role before the policies are complete, queries return
**zero rows** rather than erroring. See the RLS production runbook for the
ordered procedure and its rollback.

## What "verified" means

A migration is verified when all four hold:

- [ ] `makemigrations --check` reports no drift.
- [ ] The full suite passes against the migrated schema (387 tests).
- [ ] Row counts for every tenant-scoped table match the pre-migration counts.
- [ ] One end-to-end smoke test on the live host: sign in, list medicines, record
      a sale — the only check that exercises FEFO allocation.

Anything less, and the migration is untested.
