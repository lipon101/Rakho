#!/usr/bin/env python3
"""Fail if a credential is about to be committed, or is already in the history.

Why this exists
---------------
Encryption-at-rest protects the secret on disk. It does nothing about the other
way a secret escapes: someone pastes it into a file, a test fixture, a doc, or a
commit message, and it is in the repository forever. A secret in git history
cannot be un-published by deleting the file --- the object stays reachable, and
anyone who cloned in the meantime has it.

So this scanner is the second lock. It runs in three places, each catching a
different moment:

* **pre-commit** (``--staged``) --- before the secret is ever written to an
  object, which is the only moment it can still be stopped cheaply.
* **CI** (``--tracked``) --- on every push, so a hook that was bypassed locally
  still fails the build.
* **audit** (``--git-history``) --- over every commit, to answer "was this ever
  committed?" honestly rather than hopefully.

It is deliberately pattern-based and low-false-positive. A scanner that cries
wolf gets disabled, and a disabled scanner protects nothing, so it matches
credential *shapes* (issuer prefixes, key material headers) rather than trying
to guess entropy in prose.

Usage
-----
    python scripts/check_secrets.py --staged          # pre-commit
    python scripts/check_secrets.py --tracked         # CI
    python scripts/check_secrets.py --git-history     # audit
    python scripts/check_secrets.py path/to/file ...  # explicit files
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# ── What counts as a secret ───────────────────────────────────────────────────
#: Each entry is (label, compiled pattern). The patterns are anchored on the
#: issuer's own prefix or on key-material headers, so ordinary prose and the
#: placeholder shapes used in documentation do not match. The Render pattern
#: requires a key of at least 20 characters precisely so that the documented
#: placeholder ``srv-XXXXXXXX?key=YYYYYYYY`` is not a false positive.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GitHub personal access token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("GitHub OAuth token", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("GitHub server-to-server token", re.compile(r"ghs_[A-Za-z0-9]{20,}")),
    ("GitHub user-to-server token", re.compile(r"ghu_[A-Za-z0-9]{20,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("Render deploy hook", re.compile(r"https://api\.render\.com/deploy/srv-[A-Za-z0-9]{6,}\?key=[A-Za-z0-9_-]{20,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key material", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
)

#: Files that must never be tracked, whatever they contain. The encrypted store
#: is on this list even though it is encrypted: a ciphertext in a public repo is
#: an offline attack target, and there is no reason to hand one out.
FORBIDDEN_PATHS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("the encrypted secret store", re.compile(r"(^|/)\.secrets/.*\.enc$")),
    ("a passphrase file", re.compile(r"(^|/)(secret\.key|passphrase(\.txt)?|\.passphrase)$")),
    ("a deploy hook file", re.compile(r"(^|/)deploy[_-]?hook(\.txt|\.url)?$")),
    ("a .env file", re.compile(r"(^|/)\.env$")),
)

#: Paths that are allowed to contain the *placeholder* shapes, because they are
#: documentation. They are still scanned for real credentials --- only the
#: placeholder is tolerated, and the patterns above already ignore it.
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".ruff_cache", "staticfiles", "htmlcov"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".zip", ".gz", ".apk", ".aab", ".jks", ".keystore", ".pyc", ".so", ".dylib"}


def _redact_hit(value: str) -> str:
    """Show enough of a hit to locate it, never enough to use it."""
    if len(value) <= 12:
        return "***"
    return f"{value[:8]}…{value[-4:]} ({len(value)} chars)"


def scan_text(text: str) -> list[tuple[str, str]]:
    """Return ``(label, redacted_sample)`` for every credential shape in ``text``."""
    hits: list[tuple[str, str]] = []
    for label, pattern in PATTERNS:
        for match in pattern.finditer(text):
            hits.append((label, _redact_hit(match.group(0))))
    return hits


def scan_file(path: Path) -> list[tuple[str, str]]:
    """Scan one file, tolerating binary and unreadable files."""
    if path.suffix.lower() in SKIP_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return scan_text(text)


def check_paths(paths: list[str]) -> list[str]:
    """Check a list of paths for forbidden filenames and credential contents."""
    problems: list[str] = []
    for raw in paths:
        path = Path(raw)
        normalised = raw.replace("\\", "/")
        for label, pattern in FORBIDDEN_PATHS:
            if pattern.search(normalised):
                problems.append(f"{raw}: this looks like {label}; it must never be committed.")
        if path.is_file():
            for label, sample in scan_file(path):
                problems.append(f"{raw}: contains what looks like a {label} — {sample}")
    return problems


def _git(*args: str) -> str:
    """Run a git command, returning stdout (empty on failure)."""
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def staged_paths() -> list[str]:
    return [p for p in _git("diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines() if p]


def tracked_paths() -> list[str]:
    return [p for p in _git("ls-files").splitlines() if p]


def iter_worktree(root: Path):
    """Yield every file under ``root``, skipping the usual noise directories."""
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def scan_git_history() -> list[str]:
    """Scan every blob in every commit for credential shapes.

    Uses ``git rev-list --objects --all`` to enumerate blobs and ``git cat-file``
    to read them, rather than ``git log -p``: the patch form re-renders diffs and
    can miss a secret that was added and removed within one commit, which is
    exactly the case an audit is looking for.
    """
    problems: list[str] = []
    seen: set[str] = set()
    listing = _git("rev-list", "--objects", "--all")
    for line in listing.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        sha, name = parts
        if sha in seen:
            continue
        seen.add(sha)
        if Path(name).suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            # Read bytes, not text. A repository contains binary blobs (images,
            # compiled artefacts, the odd stray file), and decoding them as UTF-8
            # raises --- which would crash the audit on the first binary object
            # and report nothing at all. Decoding with ``errors="replace"`` keeps
            # the scan going: a credential is ASCII, so a replaced byte cannot
            # hide one.
            blob = subprocess.run(["git", "cat-file", "-p", sha], capture_output=True, check=False)
        except OSError:  # pragma: no cover
            continue
        if blob.returncode != 0:
            continue
        for label, sample in scan_text(blob.stdout.decode("utf-8", "replace")):
            problems.append(f"history: {name} ({sha[:10]}) contains what looks like a {label} — {sample}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail if a credential is present in files or git history.")
    parser.add_argument("paths", nargs="*", help="Explicit files to scan.")
    parser.add_argument("--staged", action="store_true", help="Scan only files staged for commit (pre-commit).")
    parser.add_argument("--tracked", action="store_true", help="Scan every tracked file (CI).")
    parser.add_argument("--worktree", action="store_true", help="Scan every file in the working tree.")
    parser.add_argument("--git-history", action="store_true", help="Scan every blob in every commit (audit).")
    args = parser.parse_args(argv)

    problems: list[str] = []

    if args.staged:
        problems += check_paths(staged_paths())
    if args.tracked:
        problems += check_paths(tracked_paths())
    if args.worktree:
        root = Path.cwd()
        problems += check_paths([str(p.relative_to(root)) for p in iter_worktree(root)])
    if args.git_history:
        problems += scan_git_history()
    if args.paths:
        problems += check_paths(args.paths)

    if not any([args.staged, args.tracked, args.worktree, args.git_history, args.paths]):
        parser.error("choose at least one of --staged, --tracked, --worktree, --git-history, or pass paths")

    if problems:
        print("Secret scan FAILED — the following must be fixed before this can be committed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("", file=sys.stderr)
        print("If a real credential is involved, rotate it first, then remove it from the change.", file=sys.stderr)
        return 1

    print("Secret scan passed: no credential shapes found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
