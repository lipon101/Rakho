import csv
import io
import os
import zipfile
from pathlib import Path
from urllib.request import urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventory.models import CatalogMedicine

KAGGLE_ARCHIVE_URL = "https://www.kaggle.com/api/v1/datasets/download/ahmedshahriarsakib/assorted-medicine-dataset-of-bangladesh"

# The archive is kept next to the backend after the first download. Every
# later import reads this local copy — instant, offline, and independent of
# Kaggle being reachable. Delete the folder (or pass --refresh) to re-download.
CACHE_DIR = Path(__file__).resolve().parents[3] / "catalog_cache"
CACHE_NAME = "bangladesh-medicine-dataset.zip"


class Command(BaseCommand):
    help = (
        "Imports medicine.csv from the Assorted Medicine Dataset of Bangladesh "
        "into the local catalogue table. Downloads the public archive once and "
        "caches it; later runs reuse the cached copy."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--archive", help="Path to a Kaggle ZIP archive. Skips download and cache entirely.")
        parser.add_argument(
            "--download", action="store_true",
            help="Ensure the archive is available: use the local cache, downloading only when missing.")
        parser.add_argument(
            "--refresh", action="store_true",
            help="Re-download the archive even if a cached copy exists.")
        parser.add_argument(
            "--clear", action="store_true",
            help="Delete prior imported catalog records before import.")

    def handle(self, *args, **options):
        archive_path = self._resolve_archive(options)
        if not archive_path:
            raise CommandError(
                "Provide --archive /path/to/archive.zip or use --download.")
        if not Path(archive_path).exists():
            raise CommandError(f"Archive does not exist: {archive_path}")
        records = self._read_records(archive_path)
        with transaction.atomic():
            if options["clear"]:
                CatalogMedicine.objects.all().delete()
            CatalogMedicine.objects.bulk_create(
                records, batch_size=500, update_conflicts=True, update_fields=[
                    "brand_name", "medicine_type", "slug", "dosage_form",
                    "generic_name", "strength", "manufacturer_name",
                    "package_container", "package_size_info", "updated_at",
                ], unique_fields=["source_brand_id"])
        self.stdout.write(self.style.SUCCESS(
            f"Imported or updated {len(records):,} Bangladesh medicine catalogue records."))

    def _resolve_archive(self, options):
        """Locate the archive: explicit path, local cache, or a fresh download.

        No TemporaryDirectory anywhere: the download lands in the cache via a
        .part file and an atomic rename, so there is no temp folder for
        Windows to hold a lock on while cleaning up — the exact failure that
        crashed the admin import button (WinError 32) after the data had
        already saved.
        """
        explicit = options.get("archive")
        if explicit:
            return explicit
        if not options["download"]:
            return None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached = CACHE_DIR / CACHE_NAME
        if cached.exists() and not options["refresh"]:
            self.stdout.write(f"Using cached archive: {cached}")
            return str(cached)
        part = cached.with_suffix(".zip.part")
        self.stdout.write("Downloading the public Kaggle dataset archive…")
        try:
            with urlopen(KAGGLE_ARCHIVE_URL, timeout=300) as response, open(part, "wb") as destination:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    destination.write(chunk)
            # Atomic on the same volume: a half-downloaded zip can never pose
            # as a complete cached copy.
            os.replace(part, cached)
        except Exception as exc:
            part.unlink(missing_ok=True)
            raise CommandError(f"Could not download the source archive: {exc}") from exc
        return str(cached)

    def _read_records(self, archive_path):
        """Parse medicine.csv out of the archive into CatalogMedicine rows."""
        try:
            with zipfile.ZipFile(archive_path) as archive:
                file_name = next(
                    name for name in archive.namelist()
                    if Path(name).name.lower() == "medicine.csv")
                source = io.TextIOWrapper(
                    archive.open(file_name), encoding="utf-8-sig", newline="")
                reader = csv.DictReader(source)
                records = []
                for row in reader:
                    brand_id = self.integer(row.get("brand id"))
                    if not brand_id or not row.get("brand name", "").strip():
                        continue
                    records.append(CatalogMedicine(
                        source_brand_id=brand_id,
                        brand_name=row.get("brand name", "").strip(),
                        medicine_type=row.get("type", "allopathic").strip() or "allopathic",
                        slug=row.get("slug", "").strip()[:280],
                        dosage_form=row.get("dosage form", "").strip(),
                        generic_name=row.get("generic", "").strip(),
                        strength=row.get("strength", "").strip(),
                        manufacturer_name=row.get("manufacturer", "").strip(),
                        package_container=row.get("package container", "").strip(),
                        package_size_info=row.get("Package Size", "").strip(),
                    ))
        except (zipfile.BadZipFile, StopIteration) as exc:
            raise CommandError(
                f"Invalid source archive; medicine.csv was not found: {exc}") from exc
        return records

    @staticmethod
    def integer(value):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
