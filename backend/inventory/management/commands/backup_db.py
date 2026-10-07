"""``manage.py backup_db`` --- an auditable database backup.

The DoD asks for a backup *and* a restore drill, for the reason the two belong
together: a backup nobody has ever restored is a hypothesis, not a backup. This
command produces both halves of the evidence --- the dump, and a manifest
recording what was in it --- so ``restore_drill`` can prove afterwards that the
restored copy is the same database.

What the manifest is for: a ``pg_dump`` that exits 0 has produced a file, but
"produced a file" is not "captured the data". Recording the row count of every
table at dump time means the restore can be *checked* rather than trusted, and a
truncated or partial dump is caught at the next drill instead of during an
incident.

Refuses to run against SQLite: ``pg_dump`` is the only tool here, and a
"backup" that silently did nothing on a non-Postgres database would be worse
than no backup command at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def database_settings():
    """The default connection's parameters, validated as PostgreSQL."""
    config = connection.settings_dict
    if config.get("ENGINE", "").endswith("sqlite3"):
        raise CommandError("backup_db requires PostgreSQL. This database is SQLite, which has no pg_dump --- " "and a backup command that quietly does nothing is worse than none.")
    return config


def table_names():
    """Every table in the database, in a stable order.

    Taken from the live database rather than from Django's model registry: the
    registry would miss tables created by raw SQL in a migration, and those are
    exactly the ones a hand-written restore test forgets.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        return [row[0] for row in cursor.fetchall()]


def row_counts(tables):
    """``{table: row count}`` read in one pass per table.

    A ``count(*)`` per table is the only count that cannot be fooled by a
    partially applied restore; an estimate from ``pg_class.reltuples`` would be
    stale exactly when it matters.
    """
    counts = {}
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608 - table name from pg_tables
            counts[table] = cursor.fetchone()[0]
    return counts


def sha256_of(path: Path) -> str:
    """Checksum the dump in chunks, so a large file is not read into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_for_retention(backups: list[Path], keep: int) -> list[Path]:
    """Which backups to delete so that ``keep`` newest remain.

    Separated out because it is the part of a backup command that loses data
    when it is wrong, and it is far easier to test as a pure function than by
    running deletions on a real filesystem.
    """
    ordered = sorted(backups, key=lambda path: path.stat().st_mtime, reverse=True)
    return ordered[keep:]


class Command(BaseCommand):
    help = "Create a PostgreSQL backup of Rakho with a manifest of per-table row counts."

    def add_arguments(self, parser):
        parser.add_argument("--label", default="manual", help="A short label, e.g. pre-deploy or nightly.")
        parser.add_argument("--outdir", default="backups", help="Directory to write the dump into.")
        parser.add_argument("--keep", type=int, default=7, help="How many backups to retain (0 disables pruning).")
        parser.add_argument("--no-prune", action="store_true", help="Skip retention pruning entirely.")

    def handle(self, *args, **options):
        config = database_settings()
        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise CommandError("pg_dump not found on PATH. Install the PostgreSQL client tools.")

        outdir = Path(options["outdir"])
        outdir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        label = "".join(ch for ch in options["label"] if ch.isalnum() or ch in "-_") or "manual"
        dump_path = outdir / f"rakho_{label}_{stamp}.dump"

        tables = table_names()
        counts = row_counts(tables)
        self.stdout.write(f"Capturing {len(tables)} tables, {sum(counts.values()):,} rows total.")

        env = dict(os.environ, PGPASSWORD=config.get("PASSWORD", ""))
        command = [
            pg_dump,
            "--format=custom",  # pg_restore can then be selective and parallel
            "--no-owner",  # so the dump restores into a scratch role freely
            "--no-privileges",
            f"--host={config.get('HOST') or 'localhost'}",
            f"--port={config.get('PORT') or 5432}",
            f"--username={config.get('USER')}",
            f"--file={dump_path}",
            config.get("NAME"),
        ]
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
        if result.returncode != 0:
            # Remove the partial file: a half-written dump that looks like a
            # backup is the most dangerous artifact this command could leave.
            dump_path.unlink(missing_ok=True)
            raise CommandError(f"pg_dump failed ({result.returncode}): {result.stderr.strip()[:500]}")

        size = dump_path.stat().st_size
        if size == 0:
            dump_path.unlink(missing_ok=True)
            raise CommandError("pg_dump produced an empty file. Refusing to record it as a backup.")

        manifest = {
            "created_utc": stamp,
            "label": label,
            "database": config.get("NAME"),
            "engine": "postgresql",
            "dump_file": dump_path.name,
            "dump_bytes": size,
            "dump_sha256": sha256_of(dump_path),
            "table_count": len(tables),
            "total_rows": sum(counts.values()),
            "row_counts": counts,
        }
        manifest_path = dump_path.with_suffix(".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"Backup written: {dump_path} ({size:,} bytes)"))
        self.stdout.write(f"Manifest written: {manifest_path}")
        self.stdout.write(f"sha256 {manifest['dump_sha256']}")

        if not options["no_prune"] and options["keep"] > 0:
            self._prune(outdir, options["keep"])

    def _prune(self, outdir: Path, keep: int):
        dumps = sorted(outdir.glob("rakho_*.dump"))
        for stale in select_for_retention(dumps, keep):
            # The manifest goes with its dump: keeping one without the other
            # would leave a manifest describing a file that no longer exists.
            stale.with_suffix(".manifest.json").unlink(missing_ok=True)
            stale.unlink(missing_ok=True)
            self.stdout.write(f"Pruned old backup: {stale.name}")
