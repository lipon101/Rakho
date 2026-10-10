#!/usr/bin/env python3
"""Trigger a Render deploy through the service's Deploy Hook, then prove it landed.

Why this exists
---------------
Render's auto-deploy is disabled for the Rakho service (``render.yaml`` ships no
auto-deploy key), so a push to ``main`` does **not** change what is running. The
only way to deploy is to POST the service's Deploy Hook URL. That makes "I
pushed the commits" and "the commits are live" two different facts, and this
script exists to close the gap between them.

The important half is not the POST. It is the *verification*: the hook returns
``200`` the moment Render **accepts** the request to build, which says nothing
about whether the build succeeds or which commit it contains. A build can fail,
or a previous build can still be serving traffic, and every dashboard would look
perfectly green. So after triggering, this polls ``/api/v1/version/`` on the live
host until the running process reports the commit we expect --- or gives up with
a diagnosis.

The hook URL is a secret
------------------------
The Deploy Hook URL is a credential: anyone holding it can deploy your service.
It is therefore read from the environment (``RENDER_DEPLOY_HOOK_URL``) and never
passed on the command line (which lands in shell history and ``ps``) and never
committed. When it is missing the script stops with instructions rather than
inventing a URL --- a fabricated hook would either 404 or, worse, hit someone
else's service.

Usage
-----
    export RENDER_DEPLOY_HOOK_URL='https://api.render.com/deploy/srv-...?key=...'
    python scripts/render_deploy.py --expect-commit "$(git rev-parse HEAD)"

    # Just ask what is live right now, without deploying anything:
    python scripts/render_deploy.py --check-only

    # No hook configured yet? Wire it up end to end against a local mock:
    python scripts/render_deploy.py --hook-url http://127.0.0.1:9099/hook \\
        --base http://127.0.0.1:8000 --expect-commit abc123

    # Record what was observed, for a report or a CI log to quote verbatim:
    python scripts/render_deploy.py --check-only --write-markdown /tmp/deploy.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The encrypted store lives beside this script. It is imported defensively: the
# deploy path must keep working with only the standard library --- a deploy that
# fails because a third-party package resolved differently is a deploy that
# fails for the wrong reason --- so the store is an *additional* way to supply
# the hook, never a new hard dependency. If it cannot be imported, the script
# falls back to the environment variable exactly as it did before.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import secret_store
except ImportError:  # pragma: no cover - only if the file is missing
    secret_store = None  # type: ignore[assignment]

DEFAULT_BASE = "https://rakho-api.onrender.com"
HOOK_ENV_VAR = "RENDER_DEPLOY_HOOK_URL"
#: Where the encrypted store lives, overridable so a test or a second
#: environment can point at its own store without touching the default.
STORE_ENV_VAR = "RAKHO_SECRET_STORE"


#: Statuses that mean "Render accepted the trigger and queued a build". The real
#: hook answers **202 Accepted**: it accepts the request without claiming the
#: build succeeded, which is exactly why the verdict below cannot rest on this
#: response --- acceptance is evidence, not proof. 401/403/404 are excluded on
#: purpose: those mean the URL is wrong or revoked, and retrying them is
#: indistinguishable from brute-forcing. Overridable via the environment so a
#: change on Render's side cannot silently turn every deploy into a false failure.
def _status_set(env_name: str, default: str) -> frozenset[int]:
    """Parse a comma-separated status list from the environment, ignoring blanks."""
    raw = os.environ.get(env_name, default)
    return frozenset(int(part) for part in raw.split(",") if part.strip())


HOOK_ACCEPTED_STATUSES: frozenset[int] = _status_set("RENDER_HOOK_ACCEPTED_STATUSES", "200,201,202")

#: Statuses that mean "the running process confirmed the commit we asked for".
#: Kept to exactly 200: a proxy answering 202 or 204 cannot vouch for the
#: process's own build identity, so only the process's own 200 is proof.
VERIFY_SUCCEEDED_STATUSES: frozenset[int] = _status_set("RENDER_VERIFY_STATUSES", "200")

#: How long to wait for the new build to answer. A Render free-tier build of
#: this app (pip install + collectstatic + migrate) has taken several minutes;
#: the ceiling is generous because giving up early reports a false failure on a
#: deploy that was merely slow, and a false failure trains people to ignore the
#: check. Overridable for a fast local test.
DEFAULT_TIMEOUT = 900
DEFAULT_INTERVAL = 10


#: Every secret value this process has resolved, so it can be scrubbed from
#: anything printed. Populated as the hook is resolved; empty until then.
_SECRETS: list[str] = []


def _redact(message: str) -> str:
    """Scrub credentials from a message before it is printed.

    Two layers, because they catch different mistakes. The exact values this
    process holds catch a traceback quoting the URL it was handed; the
    credential *shapes* catch a token that was never in this process at all,
    which is the case a value-only scrubber misses.
    """
    if secret_store is not None:
        return secret_store.redact(message, tuple(_SECRETS))
    scrubbed = message
    for value in _SECRETS:
        if value:
            scrubbed = scrubbed.replace(value, "***REDACTED***")
    return scrubbed


def _log(message: str) -> None:
    text = _redact(message)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        # A Windows console inherits a legacy code page (cp1252) that has no
        # arrow, and an unencodable character must not abort a deploy that is
        # otherwise going fine. Redaction already happened above, so the
        # fallback path leaks nothing that the normal path would have hidden.
        print(text.encode("ascii", "backslashreplace").decode("ascii"), flush=True)


def _fetch_json(url: str, timeout: int = 30) -> tuple[int, dict | None]:
    """GET a JSON document, returning ``(status, body_or_None)``.

    Never raises for an HTTP error status: a 404 while the old build is still
    serving is an expected intermediate state, not a crash.
    """
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "rakho-deploy/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https/localhost scheme
            raw = response.read().decode("utf-8", "replace")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError) as exc:
        # Connection refused / DNS failure / timeout. The host is asleep or
        # unreachable; the poll loop treats this as "not yet".
        _log(f"  (host not reachable yet: {exc})")
        return 0, None


def read_live_commit(base: str) -> dict | None:
    """The build identity the live host is serving, or ``None`` if it cannot say.

    ``None`` covers three states a careless caller would collapse into one: the
    host is asleep or unreachable, the host is running a build older than
    ``/api/v1/version/`` --- where ``/health/`` still answers 200 while every
    Phase 1-6 route 404s, which is exactly the state this project was in --- and
    the host answered but its body was not the JSON we expect.

    Reporting ``None`` rather than guessing is what lets the caller tell the
    difference between "old build" and "new build wrong". ``reachable``
    distinguishes the first state from the other two, so a caller can say "asleep"
    instead of a vague "not verified".
    """
    status, body = _fetch_json(f"{base.rstrip('/')}/api/v1/version/")
    reachable = status != 0
    if status in VERIFY_SUCCEEDED_STATUSES and isinstance(body, dict):
        body.setdefault("reachable", reachable)
        return body
    return None


def trigger_hook(hook_url: str, attempts: int = 3, backoff: float = 5.0) -> bool:
    """POST the deploy hook, retrying transient failures.

    A retry is safe: Render treats a deploy request as idempotent-ish (it starts
    a build for the current commit), so a duplicate POST costs a duplicate build
    at worst, which is vastly better than a silently skipped deploy.

    What counts as success is ``HOOK_ACCEPTED_STATUSES``. The real hook answers
    **202**, and an earlier revision accepted only 200/201 --- so it rejected the
    real answer, retried, and started duplicate builds while reporting failure.
    Acceptance here still proves nothing about the running build; that is the
    job of ``wait_for_commit`` below, and conflating the two is the mistake this
    function is careful not to make.
    """
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(hook_url, method="POST", data=b"")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                code = response.status
                if code in HOOK_ACCEPTED_STATUSES:
                    _log(f"Deploy hook accepted the request (HTTP {code}).")
                    # Deliberately not reported as "done": acceptance means a
                    # build was queued, not that it succeeded or carries our
                    # commit. wait_for_commit() is what proves that.
                    return True
                _log(f"  attempt {attempt}: hook returned HTTP {code}")
        except urllib.error.HTTPError as exc:
            _log(f"  attempt {attempt}: hook returned HTTP {exc.code}")
            if exc.code in (401, 403, 404):
                # Not transient: the URL is wrong or revoked. Retrying cannot
                # help, and hammering it looks like an attack.
                _log("  That status is not transient --- the hook URL is wrong, revoked, or for another service.")
                return False
        except (urllib.error.URLError, OSError) as exc:
            _log(f"  attempt {attempt}: could not reach the hook ({exc})")
        if attempt < attempts:
            time.sleep(backoff)
    return False


def wait_for_commit(
    base: str,
    expect_commit: str,
    timeout: int,
    interval: int,
) -> tuple[bool, dict | None]:
    """Poll ``/version/`` until the live build reports ``expect_commit``.

    Compares on the short sha as well as the full one, because Render reports the
    full 40-character sha while an operator types the 7-character abbreviation
    that ``git rev-parse --short HEAD`` prints --- and a check that fails on a
    technicality is a check that gets worked around.
    """
    expected = expect_commit.strip().lower()
    short = expected[:7]
    deadline = time.monotonic() + timeout
    last: dict | None = None
    announced_old_build = False

    while time.monotonic() < deadline:
        body = read_live_commit(base)
        if body is not None:
            last = body
            live = str(body.get("commit", "")).strip().lower()
            if live and (live == expected or live.startswith(short) or short.startswith(live[:7])):
                return True, body
            if not announced_old_build:
                _log("  The host is serving a DIFFERENT build " f"(live commit: {live or 'unknown'}, expected: {expected or 'unknown'}).")
                _log("  That is the expected intermediate state while the new build deploys.")
                announced_old_build = True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # Only narrate the wait when there is a real interval. A 0-interval run
        # is an explicit choice (tests, or an impatient operator) and narrating
        # it would print the same line thousands of times.
        if interval > 0:
            _log(f"  waiting for the new build… ({int(remaining)}s left)")
            time.sleep(min(interval, remaining))
    return False, last


def _store_path(args: argparse.Namespace) -> Path:
    """Where the encrypted store lives for this run."""
    explicit = getattr(args, "store", "") or os.environ.get(STORE_ENV_VAR, "").strip()
    if explicit:
        return Path(explicit)
    if secret_store is not None:
        return secret_store.DEFAULT_STORE
    return Path(__file__).resolve().parents[1] / ".secrets" / "deploy.enc"


def _resolve_hook(args: argparse.Namespace) -> str | None:
    """The hook URL, in order: command line, encrypted store, environment.

    The command-line form exists only so the mechanism can be exercised against a
    local mock. The encrypted store is the preferred production path --- it is
    the one that keeps the credential off the disk in plaintext and out of the
    process environment. The environment variable is the fallback, used only
    when no store is present, so an existing deployment that has not migrated
    yet keeps working.

    A store that exists but cannot be decrypted is *not* silently skipped: that
    is a real problem (wrong passphrase, tampered file) and falling through to
    the environment would hide it. It is reported and the run stops.
    """
    if args.hook_url:
        return args.hook_url

    store = _store_path(args)
    if secret_store is not None and store.exists():
        try:
            # The canonical name first, then the legacy spelling, so a store
            # written before the canonical names existed still opens.
            value = secret_store.load_secret_with_aliases(secret_store.SECRET_RENDER_DEPLOY_HOOK, store_path=store)
        except secret_store.SecretStoreError as exc:
            _log(f"The encrypted store at {store} could not be read: {exc}")
            _log("Refusing to fall back to the environment variable, because a store that exists but will not open is a problem to fix, not to bypass.")
            return None
        if value:
            _log(f"Using the deploy hook from the encrypted store ({store}).")
            return value

    value = os.environ.get(HOOK_ENV_VAR, "").strip()
    if value:
        _log("Using the deploy hook from the environment variable (no encrypted store found).")
    return value or None


def _write_verdict_markdown(
    path: str,
    verdict: str,
    exit_code: int,
    before: dict | None,
    after: dict | None,
    expect: str,
) -> None:
    """Write what this run actually observed, for the report to quote verbatim.

    A deploy result is a fact about a running service, not a number anyone
    computes, so it is recorded at the moment it is observed. A report that
    paraphrased it from memory would be the one place an invented sha could slip
    through. The hook URL is never written here --- only build identity.

    A write failure is reported and swallowed on purpose: losing a note must
    never turn an otherwise-verified deploy into a failed job.
    """
    lines = [
        f"verdict: {verdict}",
        f"exit_code: {exit_code}",
        f"expected_commit: {expect}",
        f"live_before: {json.dumps(before) if before else 'none'}",
        f"live_after: {json.dumps(after) if after else 'none'}",
        f"observed_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
    ]
    try:
        with open(path, "w", encoding="utf-8") as handle:
            # Redacted on the way out as a belt-and-braces measure: the lines
            # above are build identity only, but a verdict file is exactly the
            # kind of artefact that gets pasted into a report, so nothing that
            # could be a credential is allowed to reach it.
            handle.write(_redact("\n".join(lines)) + "\n")
    except OSError as exc:
        _log(f"  (could not write {path}: {exc})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger a Render deploy and verify the new build is live.")
    parser.add_argument("--base", default=os.environ.get("RAKHO_BASE_URL", DEFAULT_BASE), help="Live service base URL.")
    parser.add_argument("--expect-commit", default="", help="Commit sha the live build must report, e.g. $(git rev-parse HEAD).")
    parser.add_argument("--hook-url", default="", help="Deploy Hook URL. Prefer the RENDER_DEPLOY_HOOK_URL env var; this is for local mocks.")
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("RENDER_DEPLOY_TIMEOUT", DEFAULT_TIMEOUT)))
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--store", default="", help=f"Path to the encrypted secret store (default: {STORE_ENV_VAR} or backend/.secrets/deploy.enc).")
    parser.add_argument("--check-only", action="store_true", help="Report what is live; do not trigger a deploy.")
    parser.add_argument(
        "--write-markdown",
        default="",
        help="Write the observed verdict to this path, for the report and CI log to quote verbatim.",
    )
    args = parser.parse_args(argv)

    base = args.base.rstrip("/")
    _log(f"Rakho deploy — target {base}")

    # ── 1. What is live right now? ────────────────────────────────────────────
    before = read_live_commit(base)
    if before is None:
        _log("Live build: the host did not report a commit.")
        _log("  Either it is asleep/unreachable, or it is running a build older than /api/v1/version/.")
    else:
        _log(f"Live build: commit {before.get('commit') or 'unknown'} " f"(branch {before.get('branch') or 'unknown'}, " f"rls_enabled={before.get('rls_enabled')})")

    if args.check_only:
        if args.write_markdown:
            _write_verdict_markdown(args.write_markdown, "check-only", 0, before, before, args.expect_commit)
        return 0

    # ── 2. Trigger the deploy ─────────────────────────────────────────────────
    hook = _resolve_hook(args)
    if hook:
        # Register the value so every later line --- including a traceback --- is
        # scrubbed of it before it is printed.
        _SECRETS.append(hook)
    if not hook:
        _log("")
        _log(f"No {HOOK_ENV_VAR} is configured, so nothing was triggered. Nothing was faked either.")
        _log("")
        _log("To wire it up (one time):")
        _log("  1. Render dashboard → the rakho-api service → Settings → Deploy Hook → copy the URL")
        _log("  2. Either export it for this shell:")
        _log(f"       export {HOOK_ENV_VAR}='<paste the URL here>'")
        _log("     …or, to deploy on every push, save it as a GitHub Actions secret:")
        _log("       repo → Settings → Secrets and variables → Actions → New repository secret")
        _log(f"       name: {HOOK_ENV_VAR}   value: <paste the URL here>")
        _log("")
        _log("Then run:")
        _log('  python scripts/render_deploy.py --expect-commit "$(git rev-parse HEAD)"')
        return 2

    _log("Triggering the deploy hook…")
    if not trigger_hook(hook):
        _log("The deploy hook could not be triggered.")
        if args.write_markdown:
            _write_verdict_markdown(args.write_markdown, "hook-failed", 1, before, None, args.expect_commit)
        return 1

    # ── 3. Prove the new build is live ────────────────────────────────────────
    if not args.expect_commit:
        _log("")
        _log("Deploy triggered, but --expect-commit was not given, so the running build cannot be confirmed.")
        _log('Re-run with: --expect-commit "$(git rev-parse HEAD)"')
        return 0

    _log(f"Waiting for the live host to serve {args.expect_commit[:7]} (timeout {args.timeout}s)…")
    ok, last = wait_for_commit(base, args.expect_commit, args.timeout, args.interval)

    if args.write_markdown:
        _write_verdict_markdown(
            args.write_markdown,
            "verified" if ok else "not-verified",
            0 if ok else 1,
            before,
            last,
            args.expect_commit,
        )

    if ok and last is not None:
        _log("")
        _log(f"VERIFIED: the live host is serving commit {last.get('commit')} " f"(rls_enabled={last.get('rls_enabled')}).")
        return 0

    _log("")
    _log("NOT VERIFIED: the live host never reported the expected commit within the timeout.")
    if last is not None:
        _log(f"  It is still serving: {last.get('commit') or 'unknown'}")
    else:
        _log("  The host never reported a build at all --- it is asleep, unreachable, or still too old to have /version/.")
    _log("  Check the Render build log for this deploy; a failed build leaves the old commit serving.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
