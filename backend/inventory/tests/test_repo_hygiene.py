"""Repository hygiene --- guards against failures that are invisible in CI.

These tests exist because of a specific, real bug: an unanchored ``src/`` line
in ``.gitignore`` matched *any* directory named ``src`` at any depth, and this
repository keeps the Android app's real source at ``android/app/src/``. The
consequence was not a build failure or a red test --- it was that a brand-new
Kotlin file was silently excluded from git and did not even appear in
``git status``, so it would surface only when somebody cloned the repo and found
a file missing.

The lesson generalises: a ``.gitignore`` rule and an executable bit both fail
*silently*. Neither can be caught by a test that exercises the application, so
they are asserted here, directly against the real filesystem --- the only place
such a bug is observable.

Written with ``SimpleTestCase`` and ``unittest`` discovery on purpose. The
project's canonical runner is ``manage.py test``, which collects
``unittest.TestCase`` subclasses only; an earlier pytest-style draft of this
module was collected as **zero tests** and therefore guarded nothing while
appearing to. A guard that never runs is worse than no guard, because it creates
false confidence.

Git itself is asked the questions (``check-ignore``, ``ls-files -s``) rather than
re-implementing gitignore or mode matching here: a hand-written matcher would
only prove that our model of git agrees with itself.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


def _repo_root() -> Path | None:
    """The repository root, or None when git / the repo is unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return Path(out.stdout.strip())


ROOT = _repo_root()


def _git(*args: str) -> subprocess.CompletedProcess:
    assert ROOT is not None
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _is_ignored(relpath: str) -> tuple[bool, str]:
    """Is ``relpath`` ignored by .gitignore? Returns (ignored, matching-rule).

    Uses ``git check-ignore -q`` and its EXIT CODE rather than ``-v``'s output.
    That distinction is a real trap that produced a false failure while this
    guard was being written: ``-v`` prints the last matching pattern *even when
    that pattern is a ``!`` negation*, so a path git is deliberately NOT
    ignoring is reported with rc=0 and a pattern --- indistinguishable, from the
    output alone, from a path that IS ignored. ``-q`` with rc=0 is the only
    reliable signal for "this path is ignored".
    """
    ignored = _git("check-ignore", "-q", relpath).returncode == 0
    rule = ""
    if ignored:
        rule = _git("check-ignore", "-v", relpath).stdout.strip()
    return ignored, rule


# ── Paths that MUST remain visible to git ──
# Real product source, or a product path that will be created later. If any of
# these becomes ignored, a developer loses work with no error message.
PRODUCT_PATHS = (
    # Existing Android source --- the exact shape the original bug swallowed.
    "android/app/src/main/java/com/lipon/rakho/MainActivity.kt",
    "android/app/src/main/java/com/lipon/rakho/feature/pos/PosScreen.kt",
    "android/app/src/test/java/com/lipon/rakho/core/MoneyTest.kt",
    "android/app/src/main/res/values/strings.xml",
    "android/app/src/main/AndroidManifest.xml",
    # New Android files, in every source-set, at every depth.
    "android/app/src/main/java/com/lipon/rakho/feature/brandnew/BrandNewScreen.kt",
    "android/app/src/main/java/com/lipon/rakho/a/b/c/Deep.kt",
    "android/app/src/test/java/com/lipon/rakho/core/BrandNewTest.kt",
    "android/app/src/androidTest/java/com/lipon/rakho/Instrumented.kt",
    "android/app/src/main/res/values-bn/new_strings.xml",
    # New backend files.
    "backend/inventory/newmodule.py",
    "backend/inventory/tests/test_new_feature.py",
    "backend/config/settings/anewmode.py",
    "backend/inventory/migrations/0011_new.py",
    # The Android build files themselves.
    "android/build.gradle.kts",
    "android/gradlew",
    "android/gradle/wrapper/gradle-wrapper.jar",
)

# ── Paths that MUST stay ignored ──
# Getting these wrong is the opposite failure and a worse one: a committed
# secret or signing key. Any fix for the trap above must not weaken these.
SECRETS_AND_ARTIFACTS = (
    "backend/.secrets/deploy.enc",
    ".secrets/deploy.enc",
    "secret.key",
    "passphrase.txt",
    ".passphrase",
    "backend/.env",
    ".env",
    "android/local.properties",
    "android/keystore.properties",
    "release.jks",
    "release.keystore",
    "backend/loadtest/seed.json",
    "backend/.coverage",
    "backend/loadtest/results_stats.csv",
    "backend/backups/dump.sql",
    "android/app/build/outputs/apk/debug/app-debug.apk",
    "android/.gradle/8.0/fileHashes.bin",
    "backend/inventory/__pycache__/x.cpython-311.pyc",
)


@unittest.skipIf(ROOT is None, "not inside a git working tree --- nothing to audit")
class RepoHygieneTests(unittest.TestCase):
    """Silent-failure guards for the repository's own configuration."""

    def test_product_path_is_not_gitignored(self):
        """No real product path may be excluded by .gitignore."""
        for relpath in PRODUCT_PATHS:
            with self.subTest(relpath=relpath):
                ignored, rule = _is_ignored(relpath)
                self.assertFalse(
                    ignored,
                    f"{relpath} is excluded from git by {rule}. A product file git "
                    "ignores is lost silently: it never reaches a clone and never "
                    "appears in `git status`. Anchor the offending rule to the repo "
                    "root (`/src/`, not `src/`).",
                )

    def test_secret_or_artifact_is_still_gitignored(self):
        """A secret, a signing key or a build artefact must never be committable."""
        for relpath in SECRETS_AND_ARTIFACTS:
            with self.subTest(relpath=relpath):
                ignored, _rule = _is_ignored(relpath)
                self.assertTrue(
                    ignored,
                    f"{relpath} is NOT ignored by .gitignore --- it could be "
                    "committed. If a broad negation was added to rescue product "
                    "paths, scope it more narrowly; it must not re-include a secret.",
                )

    def test_no_tracked_file_is_a_build_artifact_or_cache(self):
        """Nothing generated (caches, build output, coverage) may be tracked."""
        tracked = _git("ls-files").stdout.splitlines()
        self.assertTrue(tracked, "git ls-files returned nothing --- unable to audit")

        offenders = []
        cache_dirs = {
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            ".gradle",
            ".idea",
            "node_modules",
            "staticfiles",
            ".venv",
            "backups",
            "sbom",
        }
        artifacts = (
            ".pyc",
            ".pyo",
            ".apk",
            ".aab",
            ".jks",
            ".keystore",
            ".orig",
            ".rej",
            ".swp",
        )
        junk_names = {".DS_Store", "dump.rdb"}

        for path in tracked:
            if set(Path(path).parts) & cache_dirs:
                offenders.append(path)
            elif path.endswith(artifacts):
                offenders.append(path)
            elif Path(path).name in junk_names:
                offenders.append(path)

        self.assertEqual(
            offenders,
            [],
            "build output / cache is tracked in git:\n  " + "\n  ".join(offenders),
        )

    def test_app_source_is_actually_tracked(self):
        """The Android app's source must be present *in git*, not merely on disk.

        This is the positive form of the regression. The original bug did not
        delete files --- it stopped git from seeing new ones. Counting what git
        holds is the only way to tell those two situations apart.
        """
        tracked = _git("ls-files").stdout.splitlines()
        android_src = [p for p in tracked if p.startswith("android/app/src/")]

        self.assertGreaterEqual(
            len(android_src),
            50,
            f"only {len(android_src)} files tracked under android/app/src/ --- the " "Android source appears to be excluded from git",
        )
        self.assertTrue(
            any(p.endswith("MainActivity.kt") for p in android_src),
            "MainActivity.kt is not tracked",
        )
        self.assertTrue(
            any(p.endswith("gradle/wrapper/gradle-wrapper.jar") for p in tracked),
            "the Gradle wrapper JAR is not tracked --- a fresh clone could not build",
        )
        self.assertTrue(any(p.endswith("android/gradlew") for p in tracked), "android/gradlew is not tracked")
        self.assertTrue(
            any(p.endswith("android/gradlew.bat") for p in tracked),
            "android/gradlew.bat is not tracked",
        )
        self.assertTrue(
            any(p.endswith("android/settings.gradle.kts") for p in tracked),
            "android/settings.gradle.kts is not tracked",
        )

    def test_gradlew_is_executable_in_the_git_index(self):
        """A clone must receive an executable ``gradlew``.

        The executable bit lives in the git index, not the working copy, so a
        file that is +x locally can still arrive in a clone as non-executable
        --- the same class of bug as the non-executable pre-commit hook this
        project already hit once.
        """
        out = _git("ls-files", "-s", "android/gradlew")
        self.assertTrue(out.stdout.strip(), "android/gradlew is not tracked")
        mode = out.stdout.split()[0]
        self.assertEqual(
            mode,
            "100755",
            f"android/gradlew has git mode {mode}, expected 100755 --- a fresh " "clone would get a non-executable wrapper",
        )

    def test_precommit_hook_is_executable_in_the_git_index(self):
        """The secret guard only runs if git can actually execute it."""
        out = _git("ls-files", "-s", ".githooks/pre-commit")
        self.assertTrue(
            out.stdout.strip(),
            ".githooks/pre-commit is not tracked --- the secret guard would not " "exist in a clone",
        )
        mode = out.stdout.split()[0]
        self.assertEqual(
            mode,
            "100755",
            f".githooks/pre-commit has git mode {mode}, expected 100755 --- git " "silently skips a non-executable hook, so the secret scan would never run",
        )
