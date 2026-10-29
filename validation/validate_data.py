"""Validate locally produced RDE files using a local, optionally pinned schema set."""

from argparse import ArgumentParser, BooleanOptionalAction
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource
from referencing.jsonschema import DRAFT202012

if __package__:
    from .sync_schemas import check_destination, load_manifest
else:
    from sync_schemas import check_destination, load_manifest


VALIDATION_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = VALIDATION_ROOT.parent
DEFAULT_SCHEMA_DIRECTORY = VALIDATION_ROOT / "schemas"
uuid_store = {}


def _offline_resource(uri):
    raise NoSuchResource(ref=uri)


def build_validator(schema_directory=None, schema_manifest=None):
    """Load a schema bundle and registry without retrieving remote references.

    The repository's default bundle requires its release lock. An adjacent lock
    is also used automatically for custom schema directories; custom directories
    without a lock remain available for inspecting candidate or legacy schemas.
    """
    directory = Path(schema_directory) if schema_directory is not None else DEFAULT_SCHEMA_DIRECTORY
    manifest_path = Path(schema_manifest) if schema_manifest is not None else directory.parent / "rde-schemas.lock.json"
    manifest = None
    if (schema_manifest is not None
            or directory.resolve() == DEFAULT_SCHEMA_DIRECTORY.resolve()
            or manifest_path.exists()):
        manifest = load_manifest(manifest_path)
        check_destination(manifest, directory)

    schemas = {}
    resources = []
    ids = set()
    for path in sorted(directory.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        if not isinstance(schema, dict) or not isinstance(schema.get("$id"), str):
            raise ValueError(f"Schema must declare a string $id: {path}")
        if schema["$id"] in ids:
            raise ValueError(f"Duplicate schema $id: {schema['$id']}")
        if manifest is not None and schema["$id"] != manifest["files"][f"rde/{path.name}"]["id"]:
            raise ValueError(f"Schema $id differs from its release lock: {path}")
        ids.add(schema["$id"])
        schemas[path.name.removesuffix(".schema.json")] = schema
        resources.append((schema["$id"], DRAFT202012.create_resource(schema)))
    if "file" not in schemas:
        raise ValueError(f"Missing file.schema.json in {directory}")
    registry = Registry(retrieve=_offline_resource).with_resources(resources)
    validator = Draft202012Validator(schema=schemas["file"], registry=registry)
    return schemas, registry, validator


def validate_iiif_file_and_report(fp: str, raise_error=False):
    # RDE validation and imports must not require the separate IIIF validator.
    if __package__:
        from .iiif_validation.schemavalidator import validate
    else:
        from iiif_validation.schemavalidator import validate

    try:
        err_reports = validate(Path(fp).read_text(encoding="utf-8"))
        if err_reports['warnings'] and len(err_reports['warnings']) > 0:
            print(f"{len(err_reports['warnings'])} warnings found in {fp}:")
            for warning in err_reports['warnings']:
                print('Warning:', warning)
        if err_reports['errorList'] and len(err_reports['errorList']) > 0:
            print(f"{len(err_reports['errorList'])} errors found in {fp}:")
            for error in err_reports['errorList']:
                print('Error:', error)
            if raise_error:
                raise Exception('Validation errors found: ', err_reports['errorList'])
    except Exception as error:
        print(f"Error validating {fp}: {error}")
        raise


def _validation_error_message(error):
    path = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path)
    if error.validator in {"anyOf", "oneOf"}:
        reason = "value does not match the permitted schema alternatives"
    else:
        reason = error.message
    if len(reason) > 240:
        reason = reason[:237] + "..."
    return f"at {path} ({error.validator}): {reason}"


def validate_file(fp: str, validator: Draft202012Validator, raise_error=False):
    """Report every invalid envelope and retain the original validation error."""
    with open(fp, encoding="utf-8") as stream:
        content = json.load(stream)
    uuid_store[fp] = []
    try:
        validator.validate(content)
    except ValidationError as error:
        if raise_error:
            raise
        print(f"Error in {fp} {_validation_error_message(error)}")
        return False
    # Valid envelopes may contain heterogeneous RDE types. There is no need to
    # guess a single object schema from the first type_in_file entry.
    uuid_store[fp] = [
        obj["id"] for obj in content["rde_objects"]
        if isinstance(obj, dict) and isinstance(obj.get("id"), str)
    ]
    return True


def is_file_holding_rde_objects(fp: str):
    with open(fp, encoding="utf-8") as stream:
        content = json.load(stream)
    return isinstance(content, dict) and 'type_in_file' in content and 'rde_objects' in content


def check_uuid_uniqueness(raise_error=False):
    uuid_file = {}
    valid = True
    for path, uuids in uuid_store.items():
        for uuid in uuids:
            if uuid not in uuid_file:
                uuid_file[uuid] = path
            else:
                message = f'UUID {uuid} found in multiple files: {uuid_file[uuid]} and {path}'
                print(message)
                valid = False
                if raise_error:
                    raise ValueError(message)
    return valid


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('-d', '--dataset', default=None, help='Dataset to validate (does not support maps and areas)')
    parser.add_argument('--only_iiif', default=False, action=BooleanOptionalAction, help='Only validate IIIF files')
    parser.add_argument('--error_interrupt', default=False, action=BooleanOptionalAction, help='Interrupt if any validation fails')
    parser.add_argument('--m', default=False, action=BooleanOptionalAction, help='Only validate maps')
    parser.add_argument('--schema-directory', type=Path, help='Local schema directory (default: validation/schemas)')
    parser.add_argument('--schema-manifest', type=Path, help='Release lock to verify before loading schemas')
    parser.add_argument('--file', type=Path, action='append', default=[], help='Validate this RDE file only; repeat to select several files, without IIIF or directory crawling')
    args = parser.parse_args(argv)
    if args.file and (args.only_iiif or args.dataset or args.m):
        parser.error('--file cannot be combined with --only_iiif, --dataset, or --m')

    uuid_store.clear()
    validator = None
    if not args.only_iiif:
        _, _, validator = build_validator(args.schema_directory, args.schema_manifest)

    valid = True

    def validate_rde(path):
        nonlocal valid
        print(f'Validating {path}')
        if not validate_file(path, validator, raise_error=args.error_interrupt):
            valid = False

    if args.file:
        # Avoid validating the same selection twice and reporting its UUIDs twice.
        for path in dict.fromkeys(path.resolve() for path in args.file):
            validate_rde(path)
        print('Checking unicity of UUIDs')
        return 0 if check_uuid_uniqueness(args.error_interrupt) and valid else 1

    dataset_root = REPOSITORY_ROOT / 'rde' / 'datasets'
    dataset_list = list(dataset_root.iterdir())
    if args.dataset:
        dataset_list = [path for path in dataset_list if args.dataset in path.name]
        if not dataset_list:
            print(f'Dataset {args.dataset} not found in {dataset_root}')
            return 1

    if not args.only_iiif:
        if not args.m:
            for dataset in dataset_list:
                # POIs are validated separately, as in the existing crawler.
                files = [path for path in dataset.rglob('*.json')
                         if 'iiif' not in str(path) and 'points_of_interest.json' not in str(path)
                         and is_file_holding_rde_objects(path)]
                for path in files:
                    validate_rde(path)

        if not args.dataset:
            map_root = REPOSITORY_ROOT / 'rde' / 'maps'
            for map_path in map_root.iterdir():
                for path in map_path.rglob('*.json'):
                    validate_rde(path)

        if not args.m and not args.dataset:
            area_root = REPOSITORY_ROOT / 'rde' / 'areas' / 'data'
            for path in area_root.rglob('*.json'):
                validate_rde(path)
            poi_root = REPOSITORY_ROOT / 'rde' / 'pois'
            for path in poi_root.rglob('*.json'):
                validate_rde(path)

    print('Checking unicity of UUIDs')
    if not check_uuid_uniqueness(args.error_interrupt):
        valid = False

    if not args.m:
        for dataset in dataset_list:
            iiif_path = dataset / 'iiif'
            if iiif_path.exists():
                collections = [path for path in (iiif_path / 'collections').iterdir() if path.suffix == '.json']
                if len(collections) > 1:
                    print('Multiple collections found in', dataset.name, ' is this expected?')
                    print('Validating collection manifests of', dataset.name)
                else:
                    print('Validating collection manifest of', dataset.name)
                for collection in collections:
                    validate_iiif_file_and_report(collection)
                manifests = list((iiif_path / 'manifests').iterdir())
                print('Validating ', len(manifests), ' manifests of ', dataset.name)
                for manifest in manifests:
                    if manifest.suffix == '.json':
                        try:
                            validate_iiif_file_and_report(manifest)
                        except Exception as error:
                            print(f"Error validating {manifest.name}: {error}")
    return 0 if valid else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValidationError as error:
        print(f'Validation failed {_validation_error_message(error)}', file=sys.stderr)
        sys.exit(1)
