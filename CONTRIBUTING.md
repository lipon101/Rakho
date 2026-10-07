# Contributing to Rakho

Thanks for helping. This is a commercial product with real pharmacies' data in
it, so the bar is "would I be comfortable if this shipped tonight" rather than
"does it work on my machine".

## Before you start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
```

Check the ground is solid before you change anything:

```bash
python manage.py test
ruff check . && black --check .
```

If those are not green on a clean `main`, say so in an issue rather than
starting on top of a red build — a failure you did not cause is much easier to
diagnose alone.

## The five gates

Every change must pass all five. CI enforces them, so a local run is only
saving you a round-trip:

| Gate | Command | What it catches |
| --- | --- | --- |
| Tests | `python manage.py test` | behaviour |
| Lint | `ruff check .` | unused imports, dead branches, bug-prone patterns |
| Format | `black --check .` | style; run `black .` to fix |
| Migrations | `python manage.py makemigrations --check --dry-run` | a model edit with no migration |
| Deploy | `python manage.py check --deploy` | a settings change that breaks production |

An untested change is not finished — but neither is a change with a test that
asserts nothing. A useful test names the behaviour it protects and fails for
one specific reason.

## Branching and commits

Trunk-based: branch from `main`, keep the branch short-lived, open a pull
request. Conventional commit messages, because the changelog is generated from
them:

```
feat(org): add seat-limit enforcement to invitation acceptance
fix(fefo): keep batch ordering stable when two batches share an expiry date
docs(readme): describe the readiness probe
chore(ci): pin ruff to 0.12.7
```

Scope is the app or the area, not the file: `org`, `fefo`, `billing`, `android`,
`ci`, `docs`.

## Where code goes

* **`inventory/models.py`** — a model earns its place here by being a fact the
  business cares about. Add an index if you will filter or order by a field;
  the sales table is the one that grows without bound.
* **`inventory/services.py`** — anything that changes more than one row belongs
  in a service, wrapped in `transaction.atomic()`. A view should read a request
  and call a service; it should not hold business rules. FEFO allocation is the
  reference example: it takes a row lock, walks batches by expiry, and either
  commits a consistent allocation or raises without changing anything.
* **`inventory/views.py`** — thin. Validate input with a serializer, call a
  service, shape the response. Never trust a client-supplied price, total or
  stock level; recompute it server-side. The Android client can be modified and
  is not a security boundary.
* **`inventory/tasks.py`** — Celery jobs. A task must be safe to run twice: a
  retry, an overlapping beat tick or a manual invocation all have to produce the
  same end state.
* **`config/settings/`** — `base` holds what is always true; `local` and
  `production` hold only what differs. If you need a new environment-dependent
  value, put it in the environment module and add it to `.env.example` with a
  comment saying why it exists.
* **`android/`** — domain logic goes in `core/` and must be unit-testable with
  no Android dependency. A screen's state lives in its view model; a composable
  renders state and emits events, nothing more.

## Multi-tenancy rules

These are not stylistic. Getting one wrong leaks one pharmacy's data into
another's:

1. **Never query a tenant-owned model without scoping it.** Use the org/pharmacy
   scope helpers rather than hand-writing a filter — a forgotten `filter()` is
   the single most likely way to leak data, and the helper is the one place that
   has a test proving it cannot be.
2. **Never take a tenant id from the request body.** It comes from the
   authenticated principal, always. A body-supplied id lets any caller read any
   tenant by guessing.
3. **Every new tenant-owned table gets a cross-tenant negative test** — a test
   that authenticates as tenant A, requests a row belonging to tenant B, and
   asserts a 404 (not a 403; the existence of the row is itself private).
4. **Money is an integer, in the smallest unit.** Floats and invoices do not mix.

## Secrets

No secret in the repository, ever — not in a test, not in a fixture, not in a
comment, not "temporarily". Configuration comes from the environment; a new
setting means a new line in `.env.example` with a placeholder value. If you
believe a secret has been committed, rotate it first and tell the maintainers
second: rotation is the only thing that actually revokes a leaked credential.

## When you open a pull request

The description should answer three questions: what changed, why now, and how you
know it is correct. If you made a trade-off, name it — a reviewer who knows why
you chose the simpler path will not spend a round asking for the other one.

If your change touches the FEFO allocator, the billing rules, the permission
classes or the settings guard, say so explicitly in the title. Those four need a
second pair of eyes regardless of size.
