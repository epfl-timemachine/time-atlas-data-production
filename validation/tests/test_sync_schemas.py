"""Offline release-consumer tests using the complete committed schema bundle."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


VALIDATION_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VALIDATION_DIRECTORY))
import sync_schemas


class SyncSchemasTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.destination = self.root / "schemas"
        self.lock_path = self.root / "rde-schemas.lock.json"
        self.archive_path = self.root / "schemas.tar.gz"
        self.release = sync_schemas.load_manifest(VALIDATION_DIRECTORY / "rde-schemas.lock.json")
        self.internal = {key: value for key, value in self.release.items() if key != "archive"}
        self.schemas = {
            name: (VALIDATION_DIRECTORY / "schemas" / Path(name).name).read_bytes()
            for name in self.release["files"]
        }
        self.write_archive()

    def write_archive(self, *, internal=None, schemas=None, extra_members=()):
        """Build a synthetic release archive without downloading any assets.

        Repin its archive hash so malformed-content tests exercise checks beyond
        the outer checksum. Schema hashes still come from the committed lock.
        """
        contents = {"manifest.json": json.dumps(self.internal if internal is None else internal).encode()}
        contents.update(self.schemas if schemas is None else schemas)
        with tarfile.open(self.archive_path, "w:gz") as archive:
            for name, content in contents.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            for member, content in extra_members:
                archive.addfile(member, io.BytesIO(content))
        self.manifest = copy.deepcopy(self.internal)
        self.manifest["archive"] = {
            **self.release["archive"],
            "sha256": hashlib.sha256(self.archive_path.read_bytes()).hexdigest(),
        }
        self.lock_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def run_cli(self, *options, output=None):
        if output is None:
            output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            sync_schemas.main([
                "--manifest", str(self.lock_path), "--destination", str(self.destination), *options,
            ])
        return output.getvalue()

    def sync(self):
        self.run_cli("--archive", str(self.archive_path))

    def snapshot(self):
        return {
            path.relative_to(self.destination).as_posix(): path.read_bytes()
            for path in self.destination.rglob("*") if path.is_file()
        }

    def assert_rejected_without_writes(self, message):
        before = self.snapshot()
        output = io.StringIO()
        with self.assertRaises(SystemExit) as error:
            self.run_cli("--archive", str(self.archive_path), output=output)
        self.assertEqual(error.exception.code, 1)
        self.assertIn(message, output.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_complete_released_bundle_roundtrip_and_offline_check(self):
        self.sync()
        self.assertEqual(self.snapshot(), {Path(name).name: data for name, data in self.schemas.items()})
        self.archive_path.unlink()
        with patch.object(sync_schemas, "urlopen", side_effect=AssertionError("Unexpected network")):
            self.assertIn(f"Checked {len(self.schemas)} schemas", self.run_cli("--check"))
        # The synthesized archive differs, but every installed schema must also
        # satisfy the real release lock committed to this repository.
        sync_schemas.check_destination(self.release, self.destination)

    def test_sync_removes_stale_schemas_and_preserves_unrelated_files(self):
        (self.destination / "nested").mkdir(parents=True)
        (self.destination / "old.schema.json").write_text("old", encoding="utf-8")
        (self.destination / "nested" / "stale.schema.json").write_text("old", encoding="utf-8")
        (self.destination / "README.txt").write_text("keep", encoding="utf-8")
        self.sync()
        self.assertFalse((self.destination / "old.schema.json").exists())
        self.assertFalse((self.destination / "nested" / "stale.schema.json").exists())
        self.assertEqual((self.destination / "README.txt").read_text(), "keep")
        sync_schemas.check_destination(self.manifest, self.destination)

    def test_check_reports_missing_changed_and_extra_schemas_without_writes(self):
        self.sync()
        (self.destination / "file.schema.json").write_text("{}", encoding="utf-8")
        (self.destination / "observation.schema.json").unlink()
        (self.destination / "extra.schema.json").write_text("{}", encoding="utf-8")
        before = self.snapshot()
        with patch.object(sync_schemas, "urlopen", side_effect=AssertionError("Unexpected network")):
            with self.assertRaises(ValueError) as error:
                sync_schemas.check_destination(self.manifest, self.destination)
        for message in ("missing: observation", "changed: file", "unexpected: extra"):
            self.assertIn(message, str(error.exception))
        with self.assertRaises(SystemExit) as error:
            self.run_cli("--check")
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_archive_is_rejected_before_writes(self):
        self.sync()
        self.archive_path.write_bytes(b"not a tar archive")
        self.assert_rejected_without_writes("Archive SHA-256 mismatch")

    def test_internal_manifest_mismatch_is_rejected_before_writes(self):
        self.sync()
        internal = copy.deepcopy(self.internal)
        internal["source_commit"] = "b" * 40
        self.write_archive(internal=internal)
        self.assert_rejected_without_writes("Internal archive manifest")

    def test_corrupted_schema_is_rejected_before_writes(self):
        self.sync()
        schemas = {**self.schemas, "rde/file.schema.json": b"{}"}
        self.write_archive(schemas=schemas)
        self.assert_rejected_without_writes("Schema SHA-256 mismatch")

    def test_schema_id_and_dialect_are_verified_even_with_matching_hashes(self):
        self.sync()
        for key, value in (("$id", "https://example.invalid/file.schema.json"), ("$schema", "draft-07")):
            with self.subTest(key=key):
                schema = json.loads(self.schemas["rde/file.schema.json"])
                schema[key] = value
                content = json.dumps(schema).encode()
                self.internal = copy.deepcopy({key: value for key, value in self.release.items() if key != "archive"})
                self.internal["files"]["rde/file.schema.json"]["sha256"] = hashlib.sha256(content).hexdigest()
                self.write_archive(schemas={**self.schemas, "rde/file.schema.json": content})
                self.assert_rejected_without_writes("mismatch")

    def test_archive_traversal_duplicate_and_link_members_are_rejected_before_writes(self):
        self.sync()
        traversal = tarfile.TarInfo("../outside.schema.json")
        traversal.size = 4
        duplicate = tarfile.TarInfo("rde/file.schema.json")
        duplicate.size = 4
        link = tarfile.TarInfo("rde/file.schema.json")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside.schema.json"
        for member, content, omit_file, message in (
            (traversal, b"evil", False, "Archive members"),
            (duplicate, b"evil", False, "duplicate paths"),
            (link, b"", True, "only regular files"),
        ):
            with self.subTest(name=member.name, type=member.type):
                schemas = dict(self.schemas)
                if omit_file:
                    del schemas["rde/file.schema.json"]
                self.write_archive(schemas=schemas, extra_members=[(member, content)])
                self.assert_rejected_without_writes(message)
                self.assertFalse((self.root / "outside.schema.json").exists())

    def test_download_uses_pinned_archive_url(self):
        with patch.object(sync_schemas, "urlopen", return_value=io.BytesIO(self.archive_path.read_bytes())) as download:
            self.run_cli()
        download.assert_called_once_with(self.manifest["archive"]["url"], timeout=30)
        sync_schemas.check_destination(self.manifest, self.destination)


if __name__ == "__main__":
    unittest.main()
