#!/usr/bin/env python3
"""A read-only load test for a *deployed* Rakho host (Phase 6 follow-up).

Why a second locustfile exists
------------------------------
``locustfile.py`` is the real scenario, but it needs seeded tenant credentials
(``loadtest/seed.json``) because it drives authenticated, tenant-scoped
endpoints. That is correct for a disposable target and **wrong for a deployed
one**: the only way to get those credentials is to run ``seed.py`` against the
host, and ``seed.py`` creates real organisations with real API keys. Pointed at
staging that would quietly add ten fake pharmacies to the installation --- which
is exactly what the user asked not to do ("they do not want to hurt real
users").

So this file measures what a deployed host exposes **without credentials**: the
liveness and readiness probes, the API root, and the JSON 404 envelope. Those are
the endpoints a stranger, an uptime monitor, a load balancer and a cold-starting
free instance actually serve, so the numbers answer a real operational question
--- "what does this instance do under concurrent public traffic" --- at zero risk
to tenant data. It performs no writes and reads no tenant rows.

It is deliberately honest about what it cannot say: it does **not** measure
authenticated query latency. If you need that number, run ``locustfile.py``
against a disposable production-shaped target (see ``docs/load-test-results.md``).

    locust -f loadtest/public_locustfile.py --headless -u 25 -r 5 -t 60s \\
        --host https://rakho-api.onrender.com --csv=loadtest/public --only-summary
"""

from __future__ import annotations

import os
import threading

import requests
from locust import HttpUser, between, events, task

#: The read budget from the DoD. These endpoints are cheap by construction, so
#: applying the read budget is fair rather than lenient.
READ_P95_BUDGET_MS = 300
ERROR_RATE_BUDGET = 0.005

#: Recorded once, so the report can state which build was measured instead of
#: assuming. A stale deploy otherwise produces numbers attributed to code that
#: never ran.
_BUILD: dict = {}

#: Endpoints this build does not have. Kept separate from the failure counter on
#: purpose: a missing route is a *deployment* fact, not a latency fact, and
#: folding it into the error rate would make the latency numbers unreadable
#: while also under-reporting the gap. It is printed loudly instead.
_MISSING: dict[str, int] = {}

#: Guards the one-time build probe. All simulated users start within the same
#: second, so without this the probe fires dozens of times and --- more
#: importantly --- its result could be read before the first response lands.
_BUILD_LOCK = threading.Lock()


class PublicUser(HttpUser):
    """An anonymous caller: a monitor, a load balancer, or a curious stranger."""

    wait_time = between(0.5, 2.0)

    def on_start(self):
        """Learn which build is live, once per run.

        Deliberately **not** issued through ``self.client``: anything sent that
        way is recorded as a locust request, and on a build that predates
        ``/version/`` its 404 would be counted as a failure --- turning a
        *deployment gap* into a phantom error-rate breach. A plain ``requests``
        call keeps the latency and error statistics about the endpoints under
        test, which is the only thing they should describe.

        404 is the expected answer from a stale build, and it is recorded rather
        than raised: proving the host is old is part of the result.
        """
        global _BUILD
        if _BUILD:
            return
        with _BUILD_LOCK:
            if _BUILD:
                return
            base = self.host.rstrip("/")
            try:
                response = requests.get(f"{base}/api/v1/version/", timeout=30)
                _BUILD["status"] = response.status_code
                if response.status_code == 200:
                    _BUILD.update(response.json())
                else:
                    _BUILD["commit"] = "(unknown — /version/ not served by this build)"
                    _BUILD["branch"] = ""
            except (requests.RequestException, ValueError) as exc:
                _BUILD["status"] = 0
                _BUILD["commit"] = f"(build probe failed: {exc})"
                _BUILD["branch"] = ""

    @task(5)
    def liveness(self):
        """The probe Render's health check reads. Must never throttle."""
        with self.client.get("/api/v1/health/", name="/api/v1/health/", catch_response=True) as response:
            self._expect(response, 200)

    @task(4)
    def readiness(self):
        """The probe a load balancer reads. Touches the database, so it is the
        most expensive thing a stranger can ask for --- and therefore the one
        worth measuring."""
        with self.client.get("/api/v1/ready/", name="/api/v1/ready/", catch_response=True) as response:
            # 503 is a *correct* answer from a readiness probe whose dependencies
            # are down: counting it as a failure would blame the service for
            # telling the truth. A 404 means this build predates the endpoint,
            # which is recorded as a deployment gap rather than a latency
            # failure --- see _MISSING.
            if response.status_code in (200, 503):
                response.success()
            elif response.status_code == 404:
                _MISSING["/api/v1/ready/"] = 404
                response.success()
            else:
                response.failure(f"expected 200, 503 or 404, got {response.status_code}")

    @task(3)
    def api_root(self):
        """The API root: a small JSON document, no database access."""
        with self.client.get("/api/v1/", name="/api/v1/", catch_response=True) as response:
            self._expect(response, 200)

    @task(2)
    def keepalive(self):
        """The database-free keep-alive endpoint the D9 decision relies on.

        Measured explicitly because its whole purpose is to be cheap enough to
        call every ten minutes forever; if it were expensive, the keep-alive that
        keeps the free instance awake would itself be the load.
        """
        with self.client.get("/api/v1/ping/", name="/api/v1/ping/", catch_response=True) as response:
            self._expect(response, 204)

    @task(1)
    def unknown_path_is_json(self):
        """The error envelope: an unknown API path must answer JSON, not HTML.

        A JSON client parsing an HTML 404 is the failure this asserts against,
        and it is measured because the 404 handler sits in front of the rest of
        the URLconf and must stay cheap. A build that predates the envelope
        answers HTML, which is recorded as a deployment gap rather than charged
        to the error rate.
        """
        with self.client.get("/api/v1/definitely-not-here/", name="/api/v1/not-found", catch_response=True) as response:
            if response.status_code != 404:
                response.failure(f"expected 404, got {response.status_code}")
            elif response.text.lstrip().startswith("{"):
                # The envelope is present: a JSON client can parse this.
                response.success()
            else:
                _MISSING["JSON error envelope"] = 404
                # Explicitly accepted. Leaving the verdict unset here would make
                # locust auto-fail the 4xx and report a *deployment gap* as an
                # error-rate breach --- a false failure that would be read as
                # the build being slow rather than being old.
                response.success()

    @staticmethod
    def _expect(response, status_code):
        if response.status_code != status_code:
            response.failure(f"expected {status_code}, got {response.status_code}")


@events.quitting.add_listener
def _gate_and_report(environment, **kwargs):
    """Apply the DoD budgets, print the measured build, and fail on a breach."""
    stats = environment.stats.total
    if stats.num_requests == 0:
        environment.process_exit_code = 1
        return

    error_ratio = stats.num_failures / stats.num_requests
    p95 = stats.get_response_time_percentile(0.95) or 0
    median = stats.get_response_time_percentile(0.5) or 0

    print("")
    print("Build under test:")
    if _BUILD.get("status") == 200:
        print(f"  commit {_BUILD.get('commit') or 'unknown'} (branch {_BUILD.get('branch') or 'unknown'})")
    else:
        print(f"  /api/v1/version/ returned {_BUILD.get('status')} --- this host predates deploy verification")
    print("")
    print(f"Measured: median {median}ms, p95 {p95}ms, error rate {error_ratio:.3%}, " f"{stats.num_requests} requests")
    print(f"Budget:   read p95 < {READ_P95_BUDGET_MS}ms, error rate < {ERROR_RATE_BUDGET:.1%}")
    if _MISSING:
        print("")
        print("MISSING ON THIS BUILD (a deployment gap, not a latency result):")
        for name, code in sorted(_MISSING.items()):
            print(f"  {name} -> HTTP {code}")

    breaches = []
    if error_ratio > ERROR_RATE_BUDGET:
        breaches.append(f"error rate {error_ratio:.3%} exceeds the budget")
    if p95 > READ_P95_BUDGET_MS:
        breaches.append(f"p95 {p95}ms exceeds {READ_P95_BUDGET_MS}ms")
    if breaches:
        print("")
        for breach in breaches:
            print(f"  BREACH: {breach}")
        environment.process_exit_code = 1
    else:
        print("")
        print("Both budgets met on the public surface.")


if os.environ.get("RAKHO_LIVE_HOST_CHECK") == "1":
    # A guard the operator can trip in CI to make the intent explicit.
    print("Live public-surface check enabled.")
