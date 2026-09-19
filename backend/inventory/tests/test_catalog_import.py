"""Tests for the catalogue import command.

Two regressions live here. First, the import used a TemporaryDirectory for
the download and cleaned it up *after* committing the rows; on Windows the
freshly written zip is briefly held open (antivirus, indexer), the cleanup
raised WinError 32, and the admin showed an error page although the import
had succeeded. The command now downloads straight into a project-local cache
with an atomic rename, so there is no temp folder to clean up at all.

Second, the cache: after one download every later import must read the local
copy — instant, offline, and independent of Kaggle — until --refresh asks for
a fresh download explicitly.
"""
import csv
import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from inventory.models import CatalogMedicine
from inventory.management.commands import import_bangladesh_catalog as module


def _zip_bytes(rows):
    """A minimal Kaggle-shaped archive holding medicine.csv."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=[
            "brand id", "brand name", "type", "slug", "dosage form",
            "generic", "strength", "manufacturer", "package container",
            "Package Size",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        archive.writestr("medicine.csv", text.getvalue())
    return buffer.getvalue()


ROWS = [
    {"brand id": "101", "brand name": "Napa", "type": "allopathic",
     "slug": "napa", "dosage form": "Tablet", "generic": "Paracetamol",
     "strength": "500 mg", "manufacturer": "Beximco",
     "package container": "Box", "Package Size": "10x10"},
    {"brand id": "102", "brand name": "Seclo", "type": "allopathic",
     "slug": "seclo", "dosage form": "Capsule", "generic": "Omeprazole",
     "strength": "20 mg", "manufacturer": "Square",
     "package container": "Box", "Package Size": "10x10"},
]


class ImportCommandTests(TestCase):
    def setUp(self):
        # Point the command's cache at a throwaway directory per test: the
        # real project cache must never be read or written by the suite.
        self._cache_dir = Path(tempfile.mkdtemp(prefix="rakho-cache-test-"))
        patcher = mock.patch.object(module, "CACHE_DIR", self._cache_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(
            lambda: shutil.rmtree(self._cache_dir, ignore_errors=True))
        self.cache_zip = self._cache_dir / module.CACHE_NAME

    def _write_archive(self, name="a.zip"):
        archive = self._cache_dir / name
        archive.write_bytes(_zip_bytes(ROWS))
        return archive

    def test_import_from_explicit_archive(self):
        archive = self._write_archive("explicit.zip")
        call_command("import_bangladesh_catalog", archive=str(archive))
        self.assertEqual(CatalogMedicine.objects.count(), 2)
        self.assertTrue(CatalogMedicine.objects.filter(brand_name="Napa").exists())

    def test_reimport_upserts_without_duplicating(self):
        archive = self._write_archive()
        call_command("import_bangladesh_catalog", archive=str(archive))
        call_command("import_bangladesh_catalog", archive=str(archive))
        self.assertEqual(CatalogMedicine.objects.count(), 2)

    def test_no_download_and_no_archive_is_a_usage_error(self):
        with self.assertRaises(CommandError):
            call_command("import_bangladesh_catalog")

    def test_download_reuses_the_cache_without_a_second_request(self):
        """One download, then every later import reads the local copy."""
        payload = _zip_bytes(ROWS)
        with mock.patch.object(module, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.side_effect = [
                payload, b""]
            call_command("import_bangladesh_catalog", "--download")
        self.assertEqual(CatalogMedicine.objects.count(), 2)
        self.assertTrue(self.cache_zip.exists())

        # Second run: no network at all, cache supplies the archive.
        CatalogMedicine.objects.all().delete()
        with mock.patch.object(module, "urlopen") as urlopen_again:
            call_command("import_bangladesh_catalog", "--download")
            urlopen_again.assert_not_called()
        self.assertEqual(CatalogMedicine.objects.count(), 2)

    def test_refresh_re_downloads(self):
        payload = _zip_bytes(ROWS)
        with mock.patch.object(module, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.side_effect = [
                payload, b""] * 2
            call_command("import_bangladesh_catalog", "--download")
            call_command("import_bangladesh_catalog", "--download", "--refresh")
        self.assertEqual(urlopen.call_count, 2)
        self.assertTrue(self.cache_zip.exists())

    def test_failed_download_leaves_no_part_file_behind(self):
        with mock.patch.object(module, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(CommandError):
                call_command("import_bangladesh_catalog", "--download")
        self.assertFalse(self.cache_zip.exists())
        self.assertFalse(
            (self._cache_dir / (module.CACHE_NAME + ".part")).exists())

    def test_a_truncated_cached_zip_is_reported_not_crashed(self):
        """A corrupt cache raises a readable CommandError, not a traceback."""
        self.cache_zip.write_bytes(b"not a zip")
        with self.assertRaises(CommandError):
            call_command("import_bangladesh_catalog", "--download")

    def test_command_module_never_uses_temporary_directory(self):
        """The Windows crash came from TemporaryDirectory cleanup; it must
        never come back. The command imports no tempfile at all."""
        self.assertFalse(hasattr(module, "tempfile"))
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import tempfile", source)
        self.assertNotIn("TemporaryDirectory(", source)
        self.assertNotIn("temp_dir.cleanup", source)
