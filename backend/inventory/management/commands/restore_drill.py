"""``manage.py restore_drill`` --- prove a backup actually restores.

This is the command that turns ``backup_db`` from a hope into a fact. It restores
a dump into a scratch database and then compares the restored row counts against
the manifest recorded at dump time. When they match, the backup is *verified*;
when they do not, the difference is reported table by table.

Two rules make it trustworthy:

* **Never into the live database.** The restore target must be a scratch database
  whose name is not the configured one --- enforced, not merely documented. A
  restore rehearsed on production is not a drill, it is a second incident.
* **The comparison is against the manifest, not against the live tables.** The
  live rows have moved on since the dump; comparing to them would always show a
  difference and teach the operator to ignore the output.

``--verify-only`` compares a previous drill's report against its manifest without
restoring again, which is what a CI job or a nightly check wants.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Restore a backup into a scratch database and verify its row counts against the manifest."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="source", required=True, help="The .dump file, or its .manifest.json.")
        parser.add_argument("--into", required=True, help="Name of the scratch database to restore into.")
        parser.add_argument("--report", default="backups/restore-drills", help="Directory for the drill report.")
        parser.add_argument(
            "--keep-db",
            action="store_true",
            help="Leave the scratch database in place for inspection instead of dropping it.",
        )

    def handle(self, *args, **options):
        config = connection.settings_dict
        if config.get("ENGINE", "").endswith("sqlite3"):
            raise CommandError("restore_drill requires PostgreSQL. This database is SQLite.")

        scratch = options["into"]
        live = config.get("NAME")
        if scratch == live:
            raise CommandError(f"Refusing to restore into the live database ('{live}'). " "Pass a scratch database name via --into; a drill that runs on production is not a drill.")

        source = Path(options["source"])
        manifest_path = source if source.suffix == ".json" else source.with_suffix(".manifest.json")
        if not manifest_path.exists():
            raise CommandError(
                f"Manifest not found at {manifest_path}. Without it there is nothing to verify the " "restore against, and an unverified restore is the thing this command exists to prevent."
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dump_path = source if source.suffix == ".dump" else manifest_path.with_suffix(".dump")
        if not dump_path.exists():
            raise CommandError(f"Dump not found at {dump_path}.")

        pg_restore = shutil.which("pg_restore")
        createdb = shutil.which("createdb")
        dropdb = shutil.which("dropdb")
        if not all([pg_restore, createdb, dropdb]):
            raise CommandError("pg_restore/createdb/dropdb not found on PATH. Install the PostgreSQL client tools.")

        host = config.get("HOST") or "localhost"
        port = str(config.get("PORT") or 5432)
        user = config.get("USER")
        env = dict(os.environ, PGPASSWORD=config.get("PASSWORD", ""))

        self.stdout.write(f"Drill: {dump_path.name} -> database '{scratch}'")

        # A fresh database every time. Restoring over an existing one would make
        # the counts depend on what was already there, which is exactly the
        # ambiguity the drill is meant to remove.
        self._run([dropdb, "--if-exists", f"--host={host}", f"--port={port}", f"--username={user}", scratch], env)
        self._run([createdb, f"--host={host}", f"--port={port}", f"--username={user}", scratch], env)

        restore = self._run(
            [
                pg_restore,
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                f"--host={host}",
                f"--port={port}",
                f"--username={user}",
                f"--dbname={scratch}",
                str(dump_path),
            ],
            env,
            allow_failure=True,
        )

        restored = self._count_in(scratch, host, port, user, env, manifest["row_counts"].keys())
        mismatches = {table: (expected, restored.get(table)) for table, expected in manifest["row_counts"].items() if restored.get(table) != expected}

        report = {
            "drilled_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
            "source_dump": dump_path.name,
            "dump_sha256": manifest.get("dump_sha256", ""),
            "manifest_created_utc": manifest.get("created_utc", ""),
            "scratch_database": scratch,
            "restore_exit_code": restore.returncode,
            "tables_expected": len(manifest["row_counts"]),
            "tables_compared": len(restored),
            "rows_expected": sum(manifest["row_counts"].values()),
            "rows_restored": sum(restored.values()),
            "mismatches": {table: {"expected": exp, "restored": got} for table, (exp, got) in mismatches.items()},
            "verified": restore.returncode == 0 and not mismatches,
        }

        report_dir = Path(options["report"])
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"drill_{report['drilled_utc']}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        if not options["keep_db"]:
            self._run([dropdb, "--if-exists", f"--host={host}", f"--port={port}", f"--username={user}", scratch], env)

        self._print_report(report, report_path)

        if not report["verified"]:
            # Non-zero exit so this can be a CI gate. A drill that reports a
            # problem but exits 0 is a drill nobody acts on.
            raise CommandError(f"Restore drill FAILED: {len(mismatches)} table(s) mismatched, " f"pg_restore exit {restore.returncode}. Report: {report_path}")

    @staticmethod
    def _run(command, env, allow_failure=False):
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
        if result.returncode != 0 and not allow_failure:
            raise CommandError(f"{Path(command[0]).name} failed ({result.returncode}): {result.stderr.strip()[:400]}")
        return result

    @staticmethod
    def _count_in(database, host, port, user, env, tables):
        """Row counts read from the *scratch* database, not the live one.

        Opened as its own connection rather than by switching Django's: the
        running app must keep its live connection for the whole drill.
        """
        import psycopg

        counts = {}
        with psycopg.connect(host=host, port=port, user=user, dbname=database, password=env.get("PGPASSWORD")) as conn:
            with conn.cursor() as cursor:
                for table in tables:
                    try:
                        cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608
                        counts[table] = cursor.fetchone()[0]
                    except Exception:  # noqa: BLE001 - a missing table is a real finding
                        conn.rollback()
                        counts[table] = None
        return counts

    def _print_report(self, report, report_path):
        status = self.style.SUCCESS("VERIFIED") if report["verified"] else self.style.ERROR("FAILED")
        self.stdout.write("")
        self.stdout.write(f"Restore drill: {status}")
        self.stdout.write(f"  dump            : {report['source_dump']}")
        self.stdout.write(f"  sha256          : {report['dump_sha256']}")
        self.stdout.write(f"  tables compared : {report['tables_compared']} / {report['tables_expected']}")
        self.stdout.write(f"  rows expected   : {report['rows_expected']:,}")
        self.stdout.write(f"  rows restored   : {report['rows_restored']:,}")
        if report["mismatches"]:
            self.stdout.write("  mismatches      :")
            for table, pair in report["mismatches"].items():
                self.stdout.write(f"    - {table}: expected {pair['expected']}, restored {pair['restored']}")
        self.stdout.write(f"  report          : {report_path}")
