import csv
import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from inventory.models import CatalogMedicine

KAGGLE_ARCHIVE_URL = "https://www.kaggle.com/api/v1/datasets/download/ahmedshahriarsakib/assorted-medicine-dataset-of-bangladesh"


class Command(BaseCommand):
    help = "Imports medicine.csv from the public Assorted Medicine Dataset of Bangladesh archive."

    def add_arguments(self, parser):
        parser.add_argument("--archive", help="Path to the Kaggle ZIP archive. Skips downloading.")
        parser.add_argument("--download", action="store_true", help="Download the public Kaggle archive before import.")
        parser.add_argument("--clear", action="store_true", help="Delete prior imported catalog records before import.")

    def handle(self, *args, **options):
        archive_path = options.get("archive")
        temp_dir = None
        if options["download"]:
            temp_dir = tempfile.TemporaryDirectory()
            archive_path = str(Path(temp_dir.name) / "bangladesh-medicine-dataset.zip")
            self.stdout.write("Downloading the public Kaggle dataset archive…")
            try:
                with urlopen(KAGGLE_ARCHIVE_URL, timeout=120) as response, open(archive_path, "wb") as destination:
                    shutil.copyfileobj(response, destination)
            except Exception as exc:
                raise CommandError(f"Could not download the source archive: {exc}") from exc
        if not archive_path:
            raise CommandError("Provide --archive /path/to/archive.zip or use --download.")
        if not Path(archive_path).exists():
            raise CommandError(f"Archive does not exist: {archive_path}")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                file_name = next(name for name in archive.namelist() if Path(name).name.lower() == "medicine.csv")
                source = io.TextIOWrapper(archive.open(file_name), encoding="utf-8-sig", newline="")
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
            raise CommandError(f"Invalid source archive; medicine.csv was not found: {exc}") from exc
        with transaction.atomic():
            if options["clear"]:
                CatalogMedicine.objects.all().delete()
            CatalogMedicine.objects.bulk_create(records, batch_size=500, update_conflicts=True, update_fields=[
                "brand_name", "medicine_type", "slug", "dosage_form", "generic_name", "strength",
                "manufacturer_name", "package_container", "package_size_info", "updated_at",
            ], unique_fields=["source_brand_id"])
        self.stdout.write(self.style.SUCCESS(f"Imported or updated {len(records):,} Bangladesh medicine catalogue records."))
        if temp_dir:
            temp_dir.cleanup()

    @staticmethod
    def integer(value):
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
