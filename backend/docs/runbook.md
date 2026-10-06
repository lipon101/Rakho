# Rakho — operations runbook

What to do when something is wrong, and what to look at first. Written to be
usable at 2am by someone who did not build the thing.

Last reviewed: 2026-10-06.

---

## The one screen

Django admin → **System health** (`/admin/system-health/`). It answers the three
questions that cover most incidents, on one page:

* Is the database, cache and broker reachable? (via `/api/v1/ready/`)
* How deep is the queue? (via `rakho_celery_queue_depth`)
* What is failing, and how often? (via `rakho_http_requests_total` by status)

If that page is unusable, the endpoints behind it still work — see below.

## Signals, and what each one means

| Symptom | Most likely cause | First move |
|---|---|---|
| `/health/` fails | The process is down | Restart. It is liveness only and touches no dependency. |
| `/health/` fine, `/ready/` fails | A dependency is down | Read `checks` in the response — it names the failing one. |
| All lists/reads return **empty** with no error | Almost always RLS: the session lost its tenant binding | See the RLS runbook's rollback. Empty is the signature; an error is not. |
| `rakho_celery_queue_depth` only rises | No worker consuming | Check the worker service is running, then its logs. |
| Task failure rate above 5% | A dependency the task uses, or a code bug after deploy | Read the latest failures in Sentry; correlate by `X-Request-Id`. |
| p95 above budget but error rate normal | Load, or an N+1 that grew with the catalogue | Start with `/inventory/dashboard/` and `/inventory/alerts/` (see `load-test-results.md`). |
| 5xx spike right after a deploy | The deploy | Roll back the application commit; do not debug in production. |
| 403 on many requests | A throttle, or CORS | A `429` is a throttle; a `403` on the browser console is usually CORS. |

## Reading the metrics

```bash
curl -fsS "$BASE/api/v1/metrics/?token=$METRICS_TOKEN"
```

Four series matter:

| Series | What to look for |
|---|---|
| `rakho_http_requests_total{route,status}` | The `5xx` rows. Nothing else on this page tells you the service is broken as directly. |
| `rakho_http_request_duration_seconds` | `histogram_quantile(0.95, ...)` by route. Compare against the DoD: reads 300ms, writes 800ms. |
| `rakho_celery_tasks_total{task,outcome}` | The `failure` and `retry` rows. A rising **retry** rate precedes a rising failure rate. |
| `rakho_celery_queue_depth` | Should hover near zero. A monotonic climb is a dead consumer, not a busy one. |

Two labels are deliberately absent, and their absence is a design decision rather
than an omission: **no tenant id** (one series per organisation would grow with
the customer base and take the monitoring down on a good day — per-tenant usage
comes from `/api/v1/org/usage/`, which reads the database) and **no raw path**
(a uuid in a label is the same unbounded problem through the front door).

## The log line

Every line is one JSON object, and every line for one request carries the same
`request_id`, which is also returned in the `X-Request-Id` header. That makes the
first diagnostic step mechanical:

```bash
# 1. Reproduce, and keep the request id from the response header
curl -si https://<host>/api/v1/inventory/dashboard/ | grep -i x-request-id

# 2. Find everything that happened for that one request
journalctl -u rakho-api --since '10 min ago' | grep '<the-id>'
```

If a customer reports a problem without an id, filter by their branch and the
time window instead; `route` and `status` are on every line.

## Background jobs

Beat schedule (all times Asia/Dhaka):

| Job | When | What breaks if it does not run |
|---|---|---|
| `queue_expiry_digests` | 07:00 daily | Customers stop getting expiry warnings — noticed a day later, in their inbox. Highest-impact silent failure. |
| `send_pending_invitations` | hourly | Invitations never arrive; staff cannot join. |
| `reconcile_billing` | 02:00 daily | Manual bKash/Nagad payments stop being matched to subscriptions. |
| `draft_monthly_invoices` | 1st, 03:00 | Invoices are not prepared. **Drafts only** — nothing is sent without a human. |
| `prune_export_files` | 04:00 daily | Exports accumulate in storage. |

Run one by hand:

```bash
python manage.py shell -c "from inventory.tasks import queue_expiry_digests; queue_expiry_digests.delay()"
```

## Queue is backed up

1. Is a worker alive? `celery -A config inspect ping` from the worker service.
2. Is one task type eating the worker? Check `rakho_celery_tasks_total` by task.
3. A single long export will not starve the digests — the worker runs `-O fair`
   with `--concurrency 2` for exactly that reason. If it is still happening, the
   queue is genuinely overloaded, not unfairly scheduled.

## Restoring from backup

Rehearse first — always:

```bash
python manage.py restore_drill --from backups/<file>.dump --into rakho_drill
```

Only then, for a real loss, restore into the live database with the same commands
the drill uses. The drill prints `VERIFIED` with matching row counts, or the exact
tables that differ. **Do not restore into production on the strength of a drill
that has never been run** — that is the situation the drill exists to prevent.

## Escalation

| Situation | Who |
|---|---|
| One tenant affected | Support, then engineering with the `X-Request-Id`. |
| All tenants, reads only | Engineering, immediately — check RLS first. |
| Data loss suspected | Stop writes (roll back the app), then engineering + the backup owner. |
| Suspected breach | Do not rotate credentials blindly: preserve logs, then follow the incident process. |

## What is deliberately NOT monitored

* **Absolute latency of the catalogue search.** It scans the national dataset
  without a tenant filter; it is the slowest endpoint by design and the DoD holds
  it to the write budget (800ms), not the read budget.
* **Per-tenant traffic.** See the label note above.
* **Disk on the free tier.** The platform reports it; Rakho does not poll it.
