"""Offline regression tests for schema loading and RDE validation."""

from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema.exceptions import ValidationError
from referencing.exceptions import NoSuchResource


VALIDATION_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VALIDATION_DIRECTORY))
import sync_schemas
import validate_data


class ValidateDataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.validation = self.root / "validation"
        self.schema_directory = self.validation / "schemas"
        self.schema_directory.mkdir(parents=True)
        self.schema_types = ("historical_record", "observation", "dataset", "area")
        for name in self.schema_types:
            self.write_schema(name, {
                "$schema": sync_schemas.DIALECT,
                "$id": sync_schemas.BASE_URI + name + ".schema.json",
                "type": "object",
                "properties": {"id": {"type": "string"}, "rde_type": {"const": name}},
                "required": ["id", "rde_type"],
            })
        self.write_schema("file", {
            "$schema": sync_schemas.DIALECT,
            "$id": sync_schemas.BASE_URI + "file.schema.json",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "creation_time": {"type": "string"},
                "type_in_file": {"type": "array", "minItems": 1, "items": {"enum": list(self.schema_types)}},
                "rde_objects": {"type": "array", "items": {"anyOf": [
                    {"$ref": sync_schemas.BASE_URI + name + ".schema.json"} for name in self.schema_types
                ]}},
            },
            "required": ["name", "creation_time", "type_in_file", "rde_objects"],
        })
        self.lock_path = self.validation / "rde-schemas.lock.json"
        self.manifest = {
            "manifest_version": 1,
            "package": sync_schemas.PACKAGE,
            "version": "1.0.0",
            "source_repository": sync_schemas.REPOSITORY,
            "source_commit": "a" * 40,
            "source_dirty": False,
            "schema_dialect": sync_schemas.DIALECT,
            "schema_base_uri": sync_schemas.BASE_URI,
            "files": {f"rde/{path.name}": {
                "id": json.loads(path.read_bytes())["$id"],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            } for path in self.schema_directory.glob("*.schema.json")},
            "archive": {
                "name": "time-atlas-rde-schemas-1.0.0.tar.gz",
                "url": sync_schemas.REPOSITORY + "/releases/download/v1.0.0/time-atlas-rde-schemas-1.0.0.tar.gz",
                "sha256": "0" * 64,
            },
        }
        self.content = {
            "name": "test data", "creation_time": "2026-10-06",
            "type_in_file": ["dataset"],
            "rde_objects": [{"id": "dataset-id", "rde_type": "dataset"}],
        }
        self.data_path = self.root / "dataset.json"
        self.write_data(self.content)
        validate_data.uuid_store.clear()

    def write_schema(self, name, schema):
        (self.schema_directory / f"{name}.schema.json").write_text(json.dumps(schema), encoding="utf-8")

    def write_data(self, content):
        self.data_path.write_text(json.dumps(content), encoding="utf-8")

    def write_lock(self):
        self.lock_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def validator(self):
        return validate_data.build_validator(self.schema_directory)[2]

    def cli(self, cwd, *args):
        for name in ("validate_data.py", "sync_schemas.py"):
            shutil.copyfile(VALIDATION_DIRECTORY / name, self.validation / name)
        return subprocess.run(
            [sys.executable, str(self.validation / "validate_data.py"), *args],
            cwd=cwd, capture_output=True, text=True, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_load_and_validate_local_ids_without_network(self):
        with patch("socket.socket.connect", side_effect=AssertionError("Network must not be used")):
            schemas, registry, validator = validate_data.build_validator(self.schema_directory)
            self.assertEqual(set(schemas), {"file", *self.schema_types})
            self.assertTrue(validate_data.validate_file(self.data_path, validator))
            with self.assertRaises(NoSuchResource):
                registry.get_or_retrieve("https://example.invalid/missing.schema.json")

    def test_explicit_and_adjacent_locks_detect_changed_missing_and_extra_files(self):
        self.write_lock()
        validate_data.build_validator(self.schema_directory, self.lock_path)
        target = self.schema_directory / "dataset.schema.json"
        original = target.read_bytes()
        target.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "changed: dataset"):
            validate_data.build_validator(self.schema_directory)
        target.unlink()
        with self.assertRaisesRegex(ValueError, "missing: dataset"):
            validate_data.build_validator(self.schema_directory, self.lock_path)
        target.write_bytes(original)
        self.write_schema("extra", {})
        with self.assertRaisesRegex(ValueError, "unexpected: extra"):
            validate_data.build_validator(self.schema_directory)

    def test_default_bundle_requires_lock_even_with_explicit_directory(self):
        with patch.object(validate_data, "DEFAULT_SCHEMA_DIRECTORY", self.schema_directory):
            for directory in (None, self.schema_directory, self.schema_directory / ".." / "schemas"):
                with self.subTest(directory=directory), self.assertRaises(FileNotFoundError):
                    validate_data.build_validator(directory)
            self.write_lock()
            validate_data.build_validator()

    def test_missing_explicit_lock_is_rejected_for_custom_bundle(self):
        with self.assertRaises(FileNotFoundError):
            validate_data.build_validator(self.schema_directory, self.lock_path)

    def test_canonical_types_and_mixed_file_are_valid(self):
        validator = self.validator()
        for name in self.schema_types:
            with self.subTest(name=name):
                content = copy.deepcopy(self.content)
                content["type_in_file"] = [name]
                content["rde_objects"] = [{"id": name + "-id", "rde_type": name}]
                self.write_data(content)
                self.assertTrue(validate_data.validate_file(self.data_path, validator))
        content["type_in_file"] = ["historical_record", "observation"]
        content["rde_objects"] = [{"id": name, "rde_type": name} for name in content["type_in_file"]]
        self.write_data(content)
        self.assertTrue(validate_data.validate_file(self.data_path, validator))

    def test_invalid_envelope_with_valid_objects_is_reported(self):
        del self.content["name"]
        self.write_data(self.content)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertFalse(validate_data.validate_file(self.data_path, self.validator()))
        self.assertIn("'name' is a required property", output.getvalue())

    def test_empty_unknown_and_malformed_types_report_original_validation_error(self):
        validator = self.validator()
        for types in ([], ["unknown"], "dataset", [None]):
            with self.subTest(types=types):
                self.content["type_in_file"] = types
                self.write_data(self.content)
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertFalse(validate_data.validate_file(self.data_path, validator))
                self.assertIn("/type_in_file", output.getvalue())
                with self.assertRaises(ValidationError):
                    validate_data.validate_file(self.data_path, validator, raise_error=True)
        error = ValidationError("original envelope error")
        with patch.object(validate_data, "Draft202012Validator") as factory:
            factory.return_value.validate.side_effect = error
            with self.assertRaises(ValidationError) as raised:
                validate_data.validate_file(self.data_path, factory.return_value, raise_error=True)
        self.assertIs(raised.exception, error)

    def test_error_output_is_bounded_for_large_invalid_object(self):
        self.content["rde_objects"] = [{"metadata": "x" * 10000}]
        self.write_data(self.content)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertFalse(validate_data.validate_file(self.data_path, self.validator()))
        self.assertIn("/rde_objects/0", output.getvalue())
        self.assertLess(len(output.getvalue()), 500)

    def test_valid_files_contribute_to_uuid_uniqueness_check(self):
        validator = self.validator()
        self.assertTrue(validate_data.validate_file(self.data_path, validator))
        self.assertEqual(validate_data.uuid_store[self.data_path], ["dataset-id"])
        duplicate = self.root / "duplicate.json"
        shutil.copyfile(self.data_path, duplicate)
        self.assertTrue(validate_data.validate_file(duplicate, validator))
        with redirect_stdout(io.StringIO()):
            self.assertFalse(validate_data.check_uuid_uniqueness())
            with self.assertRaisesRegex(ValueError, "found in multiple files"):
                validate_data.check_uuid_uniqueness(raise_error=True)

    def test_exact_file_cli_works_from_repository_root_and_validation_directory(self):
        self.write_lock()
        # There are deliberately no dataset directories or IIIF modules here.
        root_result = self.cli(self.root, "--file", "dataset.json")
        self.assertEqual(root_result.returncode, 0, root_result.stderr)
        validation_result = self.cli(self.validation, "--file", "../dataset.json")
        self.assertEqual(validation_result.returncode, 0, validation_result.stderr)

    def test_exact_file_cli_overrides_schema_paths_and_returns_failure(self):
        self.write_lock()
        alternate = self.root / "candidate" / "schemas"
        alternate.parent.mkdir()
        shutil.move(self.schema_directory, alternate)
        options = ("--schema-directory", str(alternate), "--schema-manifest", str(self.lock_path), "--file", str(self.data_path))
        result = self.cli(self.root, *options)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.content["type_in_file"] = []
        self.write_data(self.content)
        result = self.cli(self.root, *options)
        self.assertEqual(result.returncode, 1)
        self.assertIn("/type_in_file", result.stdout)

    def test_selected_files_skip_crawling_and_iiif_and_report_all_failures(self):
        del self.content["name"]
        self.write_data(self.content)
        second = self.root / "second.json"
        shutil.copyfile(self.data_path, second)
        with patch.object(validate_data, "validate_iiif_file_and_report", side_effect=AssertionError("Unexpected IIIF validation")):
            output = io.StringIO()
            with redirect_stdout(output):
                result = validate_data.main([
                    "--schema-directory", str(self.schema_directory),
                    "--file", str(self.data_path), "--file", str(second),
                ])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue().count("Error in "), 2)

    def test_interrupt_applies_to_maps_areas_and_pois(self):
        self.write_lock()
        for directory in ("datasets", "maps", "areas/data", "pois"):
            (self.root / "rde" / directory).mkdir(parents=True)
        del self.content["name"]
        for location in ("maps/example/map.json", "areas/data/area.json", "pois/poi.json"):
            with self.subTest(location=location):
                target = self.root / "rde" / location
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(self.content), encoding="utf-8")
                with patch.object(validate_data, "REPOSITORY_ROOT", self.root), redirect_stdout(io.StringIO()):
                    with self.assertRaises(ValidationError):
                        validate_data.main(["--schema-directory", str(self.schema_directory), "--error_interrupt"])
                result = self.cli(self.root, "--error_interrupt")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Validation failed", result.stderr)
                target.unlink()


class ReleasedBundleTests(unittest.TestCase):
    """Exercise the actual committed schemas without requiring generated data."""

    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("Network must not be used"))
        network.start()
        self.addCleanup(network.stop)
        self.schemas, self.registry, self.validator = validate_data.build_validator()
        self.content = {
            "name": "release integration test",
            "creation_time": "2026-10-06",
            "type_in_file": ["dataset", "observation"],
            "rde_objects": [{
                "id": "dataset-id", "rde_type": "dataset", "slug": "release-test",
                "creation_time": "2026-10-06", "version": "1.0.0",
                "name": {"en": ["Test dataset"]},
                "start_time": "1808", "end_time": "1808",
                "sources": [], "has_areas": [],
                "metadata": [{"label": {"en": ["Source"]}, "value": {"en": ["Test"]}}],
                "configuration": {
                    "main_label": "name", "sub_label": "", "display_thumbnail": False,
                    "metadata_field_config": [{
                        "id": "name", "type": "string", "display_label": {"en": ["Name"]},
                        "nullable": False, "indexable": True, "short_display": True,
                        "hidden": False, "tag": None, "paradata": None,
                    }],
                },
            }, {
                "id": "observation-id", "rde_type": "observation",
                "historical_record": "record-id", "has_geometries": None,
                "part_of_point_of_interest": None,
                "geometry": {"type": "Point", "coordinates": [12.33, 45.44]},
            }],
        }

    def test_every_released_reference_resolves_offline(self):
        references = []

        def visit(node, resolver):
            if isinstance(node, dict):
                if "$ref" in node:
                    references.append(node["$ref"])
                    resolver.lookup(node["$ref"])
                for value in node.values():
                    visit(value, resolver)
            elif isinstance(node, list):
                for value in node:
                    visit(value, resolver)

        for schema in self.schemas.values():
            visit(schema, self.registry.resolver(schema["$id"]))
        self.assertTrue(references)
        with self.assertRaises(NoSuchResource):
            self.registry.get_or_retrieve("https://example.invalid/missing.schema.json")

    def test_mixed_released_envelope_and_nested_schema_constraints(self):
        self.validator.validate(self.content)
        self.content["rde_objects"][0]["metadata"][0]["value"]["en"] = "must be a list"
        with self.assertRaises(ValidationError):
            self.validator.validate(self.content)

    def test_released_envelope_requires_name_and_nonempty_types(self):
        for field, value in (("name", None), ("type_in_file", [])):
            with self.subTest(field=field):
                invalid = copy.deepcopy(self.content)
                if value is None:
                    del invalid[field]
                else:
                    invalid[field] = value
                with self.assertRaises(ValidationError):
                    self.validator.validate(invalid)


if __name__ == "__main__":
    unittest.main()
