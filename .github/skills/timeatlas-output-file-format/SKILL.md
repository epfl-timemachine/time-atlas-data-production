---
name: timeatlas-output-file-format
description: 'Rules for producing correctly formatted output JSON files when generating TimeAtlas Research Data Entities (RDE). Use when writing data production scripts (produce_*.py) or generating dataset output files. Covers file placement, naming, JSON wrapper structure, observation format, and required dataset metadata fields (description, paradata). Always apply these rules before saving any RDE output file.'
---

# TimeAtlas Dataset Output File Format

## When to Use

Apply these rules whenever generating output JSON files for a TimeAtlas dataset as part of a data production pipeline: `datasets.json`, `historical_records.json`, `observations.json`, `geometries.json`, etc.

---

## Rule 1 — File Placement: Root of Dataset Folder

All output JSON files **must** be saved directly at the root of the dataset folder. No subdirectories.

**CORRECT:**
```
rde/datasets/<dataset-slug>/datasets.json
rde/datasets/<dataset-slug>/historical_records.json
rde/datasets/<dataset-slug>/observations.json
```

**WRONG — never create output subdirectories:**
```
rde/datasets/<dataset-slug>/data/...          ❌
rde/datasets/<dataset-slug>/historical_records/...  ❌
rde/datasets/<dataset-slug>/observations/...  ❌
```

---

## Rule 2 — File Naming: Lowercase Snake-Case RDE Type

The filename must be the **plural lowercase snake_case** form of the RDE type, with `.json` extension:

| RDE Type | Correct Filename |
|---|---|
| `dataset` | `datasets.json` |
| `historical_record` | `historical_records.json` |
| `observation` | `observations.json` |
| `geometry` | `geometries.json` |
| `point_of_interest` | `points_of_interest.json` |

---

## Rule 3 — JSON Wrapper Structure

Every output file must be a plain JSON object (NOT a GeoJSON FeatureCollection) with these exact top-level fields:

```json
{
  "name": "<dataset_context>_<rde_type_plural>",
  "type_in_file": ["<rde_type_singular>"],
  "creation_time": "<ISO-8601 timestamp>",
  "rde_objects": [ ... ]
}
```

Field details:

- **`name`**: Short identifying name in `snake_case` combining dataset theme + RDE type plural.
  - Derive from the dataset slug or theme (e.g., `"sommarioni_historical_records"`, `"lausanne_1831_berney_dataset"`, `"sommarioni_obs"`).
  - Do NOT use the raw file path or the dataset slug verbatim with hyphens.

- **`type_in_file`**: Array containing the single RDE type string (e.g., `["historical_record"]`, `["dataset"]`, `["observation"]`).

- **`creation_time`**: ISO timestamp generated at save time. Use `now_ts()` from `utils/data_modeling.py`.

- **`rde_objects`**: Array of serialized RDE objects.

**Use the provided utility functions** to write files — they produce this wrapper automatically:
- `saving_routine(data, filepath, name=name, tpe=tpe)` — direct save
- `save_data_file_if_different(fp, filename, data, name, tpe)` — smart versioned save (skips write if data unchanged)

Both are defined in `utils/data_modeling.py`.

---

## Rule 4 — Observations: Plain JSON, Not GeoJSON

Observations must be stored as **plain JSON objects** with `geometry` as a direct field — never as a GeoJSON `FeatureCollection` or `Feature` wrapper.

**CORRECT — plain JSON object:**
```json
{
  "id": "...",
  "historical_record": "...",
  "has_geometries": [],
  "part_of_point_of_interest": null,
  "rde_type": "observation",
  "geometry": {
    "type": "Point",
    "coordinates": [12.345, 45.678]
  }
}
```

**WRONG — GeoJSON Feature/FeatureCollection wrapping:**
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": { "id": "...", ... },
      "geometry": { "type": "Point", ... }
    }
  ]
}
```

Do **not** use `.geojson` extension or a GeoJSON structure for observations. The output file is `observations.json`, a plain JSON file.

---

## Rule 5 — Dataset Object: Include `description` and `paradata`

The generated `dataset` object's `metadata` array **must** include both `description` and `paradata` fields from `DATASET_CONFIGURATION` in `dataproduction_config.json`. Do not omit these free-form metadata entries.

Construct them as `FreeFormMetadata` objects:

```python
from timeatlas.RDEModel import FreeFormMetadata, MetadataType, MultiLingualValue

metadata = [
    FreeFormMetadata(
        type=MetadataType.STRING,
        label=MultiLingualValue(values={
            "en": ["Description"],
            "fr": ["Description"],
            "it": ["Descrizione"],
            "nl": ["Beschrijving"],
            "de": ["Beschreibung"]
        }),
        value=MultiLingualValue(values=DATA_CONFIG['DATASET_CONFIGURATION']['description'])
    ),
    FreeFormMetadata(
        type=MetadataType.STRING,
        label=MultiLingualValue(values={
            "en": ["Paradata"],
            "fr": ["Paradata"],
            "it": ["Paradata"],
            "nl": ["Paradata"],
            "de": ["Paradata"]
        }),
        value=MultiLingualValue(values=DATA_CONFIG['DATASET_CONFIGURATION']['paradata'])
    )
]
```

Pass `metadata=metadata` when constructing the `Dataset` object or calling `produce_dataset_obj(...)`.

For a reference implementation, see the `produce_map_obj` function in `utils/data_modeling.py` (lines ~252–282) which shows the same `FreeFormMetadata` pattern for `description` and `paradata`.

---

## Reference Examples

Correctly structured output files from existing datasets:
- `rde/datasets/venice-1808-sommarioni/datasets.json` — dataset with `name`, `type_in_file`, `creation_time`
- `rde/datasets/venice-1808-sommarioni/historical_records.json` — historical records wrapper
- `rde/datasets/venice-1808-sommarioni/observations.json` — plain JSON observations with inline `geometry`
- `rde/datasets/lausanne-1831-berney/datasets.json` — dataset with full `metadata` array (description + paradata)
