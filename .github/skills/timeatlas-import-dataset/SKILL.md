---
name: timeatlas-import-dataset
description: Import a produced TimeAtlas dataset into a backend instance with the official time-atlas-python import workflow. Use when asked to upload, validate, queue, publish, or verify a dataset import; when preparing RDECollection data for backend ingestion; or when diagnosing an incomplete TimeAtlas import. Resolve missing Points of Interest and Areas, require a user token and team UUID, run the authenticated import workflow, and confirm the published dataset is served by the target backend.
---

# Import a TimeAtlas Dataset

Use the public `TimeAtlasImportClient` exported by `timeatlas`. Its current implementation is in `timeatlas/importing.py`; do not assume a literal `import.py` module exists.

Treat an import as a write to a backend. Confirm the target versioned API URL, dataset directory, visibility, and permission to import before starting. Obtain these required values from the user if they are not already available:

- API root ending in `/v1`
- personal access token
- team UUID

Never print the token, place it in source code, commit it, or include it in the final report. Prefer environment variables or a local ignored credential file containing `TOKEN=...` and `TEAM_ID=...`.

## 1. Prepare the environment and collection

Run every Python command from the repository environment:

```bash
source data-production-venv/bin/activate
```

Load all produced RDE envelopes from the dataset directory. Use the in-memory collection directly when the production script already exposes one.

```python
from timeatlas import RDECollection

dataset_dir = "rde/datasets/<dataset-slug>"
collection = RDECollection.read_rde_from_files(dataset_dir)
```

Confirm the collection contains exactly the intended `Dataset` and its associated records. Inspect entity counts and UUID references before mutating or uploading anything.

## 2. Resolve the PoI situation

Inspect every Observation's `part_of_point_of_interest` and the collection's `PointOfInterest` entities.

- Preserve intentionally excluded observations marked `False`; these require spatial indexing without an interactive PoI.
- Preserve valid authoritative PoI links only when their PoIs are included in the collection and the references are consistent.
- If the dataset's observations that should appear interactively are not tied to PoIs, generate dedicated deterministic PoIs and patch their references before validation:

```python
points_of_interest = collection.aggregate_observations_into_points_of_interest()
```

This groups observations by coordinates rounded to five decimal places, creates deterministic PoI UUIDs, adds the PoIs to the collection, and updates observation references. Do not hand-roll random PoI UUIDs. Review the generated count and spot-check that each eligible observation references a serialized PoI.

Do not run whole-collection aggregation over a mixed collection if it would replace intentional authoritative PoI references. Aggregate only the unresolved Observation objects in a temporary `RDECollection`, then add the returned PoIs to the main collection; the shared Observation objects receive the generated references.

## 3. Resolve the Area situation

Every Dataset must be connected to at least one Area for backend spatial indexing.

- If the dataset has no area reference, let local validation create a deterministic ad-hoc Area from the union extent of its Observation and Geometry RDEs.
- If a suitable Area already exists in the collection, attach its UUID to `Dataset.has_areas`.
- If the Dataset references an Area absent from the collection, keep it only when that exact UUID already exists on the target backend. The import client checks this before upload and stops if it is unavailable.
- If no local spatial extent exists from which to create an Area, stop and resolve the missing spatial data with the user; do not invent a boundary.

## 4. Validate locally

Run collection validation after PoI preparation:

```python
collection.validate_data()
```

Validation may add the extent-derived Area. Treat validation errors as blockers. Review warnings, especially external Area references, rather than suppressing them. Save or inspect the final envelopes when useful; `run_collection_workflow` serializes the validated collection again before upload.

## 5. Run the authenticated workflow

Instantiate the client from environment-provided secrets:

```python
import os
from timeatlas import TimeAtlasImportClient

client = TimeAtlasImportClient(
    "https://<backend>/v1",
    token=os.environ["TIMEATLAS_TOKEN"],
    team_id=os.environ["TIMEATLAS_TEAM_ID"],
)

result = client.run_collection_workflow(
    collection,
    "<temporary-or-dedicated-import-output-dir>",
    visibility="public",
    on_event=lambda event: print(event.get("message", event.get("type", "event"))),
)
```

Alternatively use `TimeAtlasImportClient.from_credentials_file(api_url, path)` for an ignored local credential file.

The workflow performs the required sequence: verify external Areas, serialize, upload and checksum files, create the import, wait for packaging, request server validation, require a passed validation report, queue the import, wait for completion, then publish Areas, PoIs, Datasets, and Maps present in the collection. Do not manually skip or reorder these stages.

Treat `ImportWorkflowError`, timeout, server validation failures, and failure/cancellation statuses as unsuccessful imports. If the final status is `completed_with_indexing_errors`, inspect events and backend errors and do not claim full success until serving checks pass.

## 6. Verify that the backend serves the data

Do not finish at a successful upload or queue status. Verify all of the following:

1. `result.validation_report["status"] == "passed"` and `failures` is empty.
2. `result.import_data["status"]` is `completed`; investigate `completed_with_indexing_errors`.
3. Publication results show the intended visibility for the Dataset and, when present, Areas, PoIs, and Maps.
4. A fresh unauthenticated public client can retrieve the published Dataset by UUID and slug when visibility is `public`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from timeatlas import TimeAtlas

# TimeAtlas loads its default pickle cache during construction. Isolate the
# verification before construction so a stale or populated project cache can
# neither break the check nor satisfy it without a backend request.
default_cache = TimeAtlas.default_save_cache_filepath
try:
    with TemporaryDirectory() as temporary_directory:
        TimeAtlas.default_save_cache_filepath = str(
            Path(temporary_directory) / "empty-verification-cache.pkl"
        )
        served = TimeAtlas("https://<backend>/v1")
finally:
    TimeAtlas.default_save_cache_filepath = default_cache

assert served.get_dataset(dataset.id).id == dataset.id
assert served.get_dataset_by_slug(dataset.slug).id == dataset.id
```

5. Sample at least one imported HistoricalRecord, Observation, and generated PoI when those types exist. Retrieve them through the backend's read endpoints and verify their UUIDs and cross-references. For a private import, perform equivalent authenticated reads instead of expecting public access.
6. Confirm the returned Dataset is discoverable through the normal dataset listing/search surface and that referenced Areas resolve. Retry briefly only for documented asynchronous indexing; record any persistent indexing or retrieval failure.

Report the backend URL, team UUID, dataset slug and UUID, import UUID, terminal status, validation outcome, publication visibility, sampled entity checks, and any warnings. Redact the token and other secrets.
