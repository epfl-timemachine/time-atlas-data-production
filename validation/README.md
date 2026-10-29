# Data validation

Run commands from the repository root using the existing environment:

```sh
source data-production-venv/bin/activate
python -m pip install -r validation/requirements.txt
```

## RDE schema releases

The shared source is
[time-atlas-json-schema](https://github.com/epfl-timemachine/time-atlas-json-schema).
Applications use a complete, pinned local schema bundle. Validation never fetches
schemas from the network.

This repository is pinned to the official
[`v1.0.0` release](https://github.com/epfl-timemachine/time-atlas-json-schema/releases/tag/v1.0.0),
adopted on 2026-10-06. `validation/rde-schemas.lock.json` records its source commit,
immutable archive URL, archive checksum and per-schema hashes. The validator
requires and checks this pin automatically before using `validation/schemas`.
Missing locks, missing schemas and local modifications stop validation.

`sync_schemas.py` is the unchanged
[upstream v1.0.0 sync helper](https://github.com/epfl-timemachine/time-atlas-json-schema/blob/v1.0.0/scripts/sync_schemas.py).

To reinstall `v1.0.0`, download its manifest and archive into a temporary
directory, then verify and install them:

```sh
(
set -e
schema_download_dir="$(mktemp -d)"
trap 'rm -rf "$schema_download_dir"' EXIT
schema_release_url="https://github.com/epfl-timemachine/time-atlas-json-schema/releases/download/v1.0.0"

curl --fail --location \
  "$schema_release_url/time-atlas-rde-schemas-1.0.0.manifest.json" \
  --output "$schema_download_dir/rde-schemas.lock.json"
curl --fail --location \
  "$schema_release_url/time-atlas-rde-schemas-1.0.0.tar.gz" \
  --output "$schema_download_dir/schemas.tar.gz"

python validation/sync_schemas.py \
  --manifest "$schema_download_dir/rde-schemas.lock.json" \
  --archive "$schema_download_dir/schemas.tar.gz" \
  --destination validation/schemas
cp "$schema_download_dir/rde-schemas.lock.json" validation/rde-schemas.lock.json
)
```

The subshell stops on any failure and cleans up its temporary downloads. Review
the release version, source commit and archive hash, and commit
`validation/rde-schemas.lock.json` with the updated schemas. The sync tool verifies the archive checksum, internal
manifest, exact file set, schema IDs and individual hashes before writing. It
removes obsolete `.schema.json` files; do not edit the generated schema copies.
The `curl` download path also works with macOS Python installations whose default
certificate store is not configured; TLS verification remains enabled.

For later updates, choose an explicit release version and repeat the process in
a pull request. Do not fetch `latest` during normal validation or application
builds. The sync helper can also download the archive itself when called without
`--archive`.

The validator checks the lock automatically before loading the default schemas.
To check integrity without validating a dataset:

```sh
python validation/sync_schemas.py \
  --manifest validation/rde-schemas.lock.json \
  --destination validation/schemas \
  --check
```

## Running RDE validation

For exactly the current Sommarioni output files, without archived `data_v1`
copies or IIIF validation:

```sh
python validation/validate_data.py \
  --file rde/datasets/venice-1808-sommarioni/dataset.json \
  --file rde/datasets/venice-1808-sommarioni/historical_records.json \
  --file rde/datasets/venice-1808-sommarioni/observations.json \
  --error_interrupt
```

To try a candidate bundle without replacing the default schemas, add:

```sh
  --schema-directory /absolute/path/to/candidate/schemas \
  --schema-manifest /absolute/path/to/candidate/release.manifest.json
```

Both paths must refer to the same bundle. An explicit missing manifest or any
schema drift fails validation setup. A custom schema directory without an
adjacent lock is supported for inspecting legacy schemas or downloaded Pages
files, but it is not a release pin.

The existing dataset traversal remains available:

```sh
python validation/validate_data.py --dataset venice-1808-sommarioni --error_interrupt
```

Dataset mode recursively includes archived RDE files and checks any associated
IIIF files. `--file` selects only the named RDE files. Schema/data paths are
resolved consistently when running from the repository root or `validation/`;
explicit file paths are relative to the current working directory. `--file`
validates complete envelopes, including missing required fields and invalid
`type_in_file` lists. Dataset discovery recognizes only JSON files containing both
`type_in_file` and `rde_objects`; use `--file` when checking malformed envelopes
that may be missing either field.

## Regression checks

```sh
python -m unittest discover -s validation/tests -v
```

These tests cover the actual pinned bundle, offline reference resolution, archive
and manifest integrity, schema replacement and drift detection, explicit file
selection and file-level validation errors. They do not require data submodules,
IIIF dependencies or network access.

[The validation workflow](../.github/workflows/validation.yml) runs the integrity
check and regression suite on Python 3.12 and 3.13 for relevant pull requests and
pushes to `main`. The Docker build also loads and verifies the pinned bundle in its
smoke test. Neither check downloads schemas or advances the pinned release.

## IIIF

IIIF uses the repository's adapted
[IIIF presentation validator](https://github.com/IIIF/presentation-validator).
Run it separately with:

```sh
python validation/validate_data.py --only_iiif
```

The IIIF validator is loaded only when IIIF validation is requested, so checking
RDE schemas does not require importing it.
