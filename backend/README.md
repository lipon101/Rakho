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

## Public facts have one source each

The landing page (`inventory/landing.py`), the checkout page (`pay.py`) and the
owner console (`admin_dashboard.py`) all state numbers a customer can check, so
none of them may hold its own copy:

| Fact | Source |
| --- | --- |
| Pro price | `inventory/pricing.py` ← `PRO_PRICE_BDT` |
| Canonical origin (canonical link, OG URLs, schema `@id`s, robots, sitemap) | `SITE_URL` ← `RENDER_EXTERNAL_HOSTNAME` |
| Catalogue size on the landing page | `CatalogMedicine.objects.count()`, or no claim at all when empty |
| FAQ questions and answers | `landing.faq_items()`, rendered into both the visible accordion and `FAQPage` structured data |

`inventory/tests/test_brand_and_price_truth.py` changes the configured price
and origin and asserts every surface follows, so the page cannot advertise a
price the checkout does not charge.

## Paid features are decided on the server

The national medicine catalogue is what a subscription buys, so both routes
that expose it require a paid, unexpired plan (`services.has_paid_plan`):

- `GET /api/v1/catalog/medicines/` — search. This was `AllowAny`, so the entire
dataset was readable, and rebuildable into a competing app, without a key.
- `POST /api/v1/inventory/medicines/` carrying a `catalog_medicine` id — copies
  that row's brand/generic/strength onto the new medicine and returns them,
  which leaked the dataset one sequential id at a time even with search closed.

Both answer `402` with `error.code = "pro_required"` and an `upgrade_url`. Free
accounts keep manual entry and every other endpoint; a lapsed plan behaves like
free rather than erroring.

### Loading the catalogue into a database

```bash
python manage.py import_bangladesh_catalog --download        # ~21,700 records
python manage.py import_bangladesh_catalog --archive path/to/archive.zip
```

It upserts on `source_brand_id`, so re-running (or retrying a partial attempt)
is safe, and it finishes in seconds. Against a deployed database, either run it
as a one-off job in the host's dashboard or trigger the guarded endpoint:
`POST /api/v1/setup/catalog/` with an `X-Setup-Token` header. The console's
"catalogue is empty" item clears by itself once rows exist.

The console is a *window* onto this table, never a way in. There is no add or
change form for a catalogue medicine — a row typed by hand would have no
`source_brand_id` for the next import to match, so it would fork the copy every
install searches. The changelist instead carries one button, **Re-import from
dataset**, which runs the same upsert behind a POST so a crawler or prefetcher
cannot trigger a full re-import by following a link.

The ledgers a service writes (sale lines, sale allocations, stock movements,
Play verification events, per-IP abuse tallies) are read-only for the same
reason: the owner inspects the sales, and the code that records them is the only
thing that writes them.

## Brand images

The favicon, Apple touch icon and Open Graph share card are generated, not
hand-drawn, so they can be regenerated without a design tool:

```bash
python manage.py make_brand_images   # writes static/brand/*.png
```

Pure stdlib (no Pillow). Commit the regenerated files after running it. The
share card matters more than it looks: links spread through Messenger and
WhatsApp, and without `og:image` every one of them rendered as a bare grey
card.
