---
name: timeatlas-pre-production-analysis
description: 'Pre-production source data analysis for TimeAtlas datasets. Use before writing any data production script (produce_*.py). Guides analysis of source files to determine: geometry vs coordinate-only observations, HR-to-observation cardinality, and what dataset configuration metadata can be inferred. Always run this analysis before starting data production.'
---

# TimeAtlas Pre-Production Source Data Analysis

## When to Use

Before writing any `produce_*.py` script for a new dataset, analyze the source data in the indicated source folder (may be `src/`) to answer three key questions. The answers directly determine how to write the production script.

---

## Step 0 — Create the dataset output folder and config file

Before any analysis, create a dedicated folder for the dataset under `rde/datasets/` if it does not already exist, and initialize its configuration file:

```bash
# Replace <dataset-slug> with the unique slug for the new dataset (e.g. venice-1808-sommarioni)
mkdir -p rde/datasets/<dataset-slug>
cp rde/datasets/dataproduction_config_template.json rde/datasets/<dataset-slug>/dataproduction_config.json
```

Then open `rde/datasets/<dataset-slug>/dataproduction_config.json` and fill in all fields:

| Field | What to fill |
|---|---|
| `UUID_NAMESPACE` | Unique URL identifying this dataset, e.g. `https://timemachine.epfl.ch/<area>/<dataset-slug>` |
| `TIMERANGE_MINIMUM` | Start date of the dataset's coverage (format `YYYYMMDD`) |
| `TIMERANGE_MAXIMUM` | End date of the dataset's coverage (format `YYYYMMDD`) |
| `AREA_LOCS` | List of area UUIDs the dataset belongs to |
| `DATASET_CONFIGURATION.slug` | URL-safe slug matching the folder name |
| `DATASET_CONFIGURATION.name` | Multilingual display name, e.g. `{"en": "...", "fr": "..."}` |
| `DATASET_CONFIGURATION.description` | Multilingual description of the dataset |
| `DATASET_CONFIGURATION.paradata` | Multilingual description of the production method |
| `DATASET_CONFIGURATION.main_label` | Field key used as the primary display label on POIs |
| `DATASET_CONFIGURATION.sub_label` | Field key used as the secondary display label on POIs |
| `indexed` | Field keys used for search/filter |
| `short_display` | Field keys shown in compact/card view |
| `manual_fields` / `semi_automatic_fields` / `ai_fields` | Fields classified by transcription method |

Only proceed to the analysis questions below once the config file exists and the namespace/slug are set.

---

## Question 1 — What is the geometry situation?

Identify which of the following cases applies, as they require different production patterns:

### Case A: Source has polygon/area geometries (GeoJSON or Shapefile)
Observations must be **derived** from the geometry — the observation coordinate is the centroid (constrained to inside the polygon).

**Indicators:** source files are `.geojson`/`.shp` with `Polygon`/`MultiPolygon` features, or a column references geometry IDs that join to a separate geometry file.

**Production pattern:**
```python
# Geometries → saved to map folder as RDEType.GEOM
# Centroid of geometry → used as observation coordinate
gdf['centroid'] = gdf['geometry'].apply(lambda g: g.centroid)
gdf['coordinate'] = gdf.apply(
    lambda x: constraint_point_to_center_of_one_polygon(x['centroid'], x['geometry']), axis=1
)
```
Geometries are saved separately to the **map folder** (`../../maps/<map-slug>/`), not the dataset folder.

---

### Case B: Source has point coordinates (lat/lon columns or Point geometry)
Observations use coordinates **directly from the source**.

**Indicators:** source CSV/JSON has columns like `latitude`/`longitude`, `lat`/`lon`, `x`/`y`, or WGS84 point coordinates.

**Production pattern:**
```python
gdf['geometry'] = gdf.apply(lambda x: Point(x['longitude'], x['latitude']), axis=1)
# observation coordinate = geometry directly
obs = produce_obs_obj(uuid, time_range, ds_uuid, hr_uuid, tpe, row.geometry, geometries_links=[])
```

---

### Case C: Source has no geometry at all
Observations **cannot be geolocated** — `geometry` field should be `None`, and `part_of_point_of_interest` should be `False`.

**Indicators:** source is purely tabular (CSV/JSON) with no coordinate columns and no linked geometry file.

**Production pattern:**
```python
obs = produce_obs_obj(uuid, time_range, ds_uuid, hr_uuid, tpe, coords=None, geometries_links=[], need_poi=False)
```

---

### Case D: Source has geometry for some records only (partial)
Same as Case A or B, but only a subset of records can be geolocated. Unlocated records use `coords=None, need_poi=False`.

---

## Question 2 — What is the HR-to-observation cardinality?

Determine how many observations correspond to each historical record. This governs the join logic.

| Pattern | Description | Example |
|---|---|---|
| **1 HR → 1 Obs** | Each source row produces exactly one HR and one observation | Photo archive, iconography datasets |
| **N HRs → 1 Obs** | Multiple records share the same location (e.g., same parcel/building) | Cadaster registers where many owners occupy same parcel |
| **1 HR → N Obs** | One record references multiple distinct locations | Rare; e.g., a single owner with properties at multiple addresses |

**How to detect:**
- Count unique identifier vs. unique geometry/coordinate pairs: `df.groupby('geometry_id')['record_id'].count().describe()`
- If the cardinality is 1:1, UUID generation can use a single seed per row.
- If N:1, observations must be deduplicated by coordinate before creation; HRs reference a single observation UUID.
- If 1:N, each HR produces multiple observation objects.

Instantiate a `UUIDManager` once per dataset using the dataset's URL namespace, then pass a `(manager, value)` tuple as the `id` argument to any `UUIDEntity` subclass (`HistoricalRecord`, `Observation`, etc.). The class name is automatically prepended to the value, preventing cross-type UUID collisions.

```python
from timeatlas.RDEModel import UUIDManager

# Instantiate once per dataset (URL must be unique per dataset)
uuid_manager = UUIDManager(DATA_CONFIG['UUID_NAMESPACE'])
```

**For 1:1 (most common for coordinate-based datasets):**
```python
# Pass (uuid_manager, unique_string_value) as id — class name is auto-prefixed
hr = HistoricalRecord(
    id=(uuid_manager, str(row[UNIQUE_ID_COL])),
    ...
)
obs = Observation(
    id=(uuid_manager, str(row[UNIQUE_ID_COL])),
    ...
)
```

**For geometry-grouped N:1 (cadaster-like):**
```python
# Use the geometry/location identifier as the unique seed for the observation
obs = Observation(
    id=(uuid_manager, str(row['geometry_id'])),
    ...
)
# Each HR uses its own unique record identifier
hr = HistoricalRecord(
    id=(uuid_manager, str(row[UNIQUE_ID_COL])),
    ...
)
```

---

## Question 3 — What dataset configuration can be derived from the source?

The `dataproduction_config.json` was created in Step 0. Now complete its field-level entries using the information extracted below. Inspect the source to extract:

### 3a. Field inventory
```python
# Quick audit of all columns in source
print(df.dtypes)
print(df.head(2))
print(df.isnull().sum())  # which fields are nullable
```

For each field, determine:
- **Type**: `STRING`, `INTEGER`, `FLOAT`, `LIST` → used in `metadata_field_config`
- **Nullable**: any `NaN`/`None` present → `"nullable": true`
- **Paradata class**: `"m"` (manual), `"sa"` (semi-automatic), `"a"` (automatic/AI) → reflects transcription method

### 3b. Unique identifier column
Identify the column(s) that uniquely identify each record — this string value is passed as the seed to `UUIDManager` for deterministic UUID generation. Confirm uniqueness before using a column as a seed.

```python
# Verify uniqueness
assert df[CANDIDATE_ID_COL].is_unique, "ID column is not unique!"
```

If no single column is unique, find the combination that is, and concatenate them into a single string seed:
```python
df.duplicated(subset=['col_a', 'col_b']).sum()  # should be 0
# combined seed example: str(row['col_a']) + '_' + str(row['col_b'])
```

### 3c. Time range
Check if the time range is uniform across all records or per-record:
- **Uniform** (entire dataset covers one period): set `TIMERANGE_MINIMUM` and `TIMERANGE_MAXIMUM` in config, apply to all HRs.
- **Per-record** (each row has its own date): derive `start_time`/`end_time` per HR from source columns.

```python
# Check for per-record dates
print(df[['start_year', 'end_year']].describe())
```

### 3d. Language(s) of the source data
Identify the primary language for `name`, `description`, `paradata` multilingual fields in `dataproduction_config.json`. Inspect text fields:
```python
print(df['text_column'].iloc[0])
```

### 3e. Linked external sources (IIIF)
Check if source has image/document URLs or file references:
- If yes → IIIF manifest generation will be needed
- Look for columns: `image_url`, `filename`, `page_number`, `folio`, `canvas_id`

---

## Checklist Before Writing the Production Script

Run through these checks and note the answers:

```
[ ] Geometry type: polygon / point coordinates / none / mixed
[ ] Obs derived from geometry centroid, or taken directly from coords?
[ ] HR:Obs cardinality: 1:1 / N:1 / 1:N
[ ] Unique identifier column confirmed as unique
[ ] Time range: uniform (from config) or per-record (from source columns)
[ ] Fields with nullable values identified
[ ] Paradata class for each field determined (m / sa / a)
[ ] Indexed fields identified (fields used for search/filter)
[ ] Short-display fields identified (fields shown in compact view)
[ ] IIIF / image sources present?
[ ] description and paradata text prepared for all supported languages
```

Only proceed to write the `produce_*.py` script once all items are resolved.

---

## Reference Implementations

Study these existing production scripts to see each pattern in action:

| Pattern | Reference Script |
|---|---|
| Polygon geometry → centroid obs, N:1 cardinality | `rde/datasets/venice-1808-sommarioni/produce_sommarioni_data.py` |
| Point coordinates in source, 1:1 cardinality | `rde/datasets/lausanne-mhl-iconographie/produce_mhl_icono_data.py` |
