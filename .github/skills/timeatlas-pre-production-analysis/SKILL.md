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
| `DATASET_CONFIGURATION.main_label` | Formatting string for the primary display label of Historical Records (HRs) |
| `DATASET_CONFIGURATION.sub_label` | Formatting string for the secondary display label of Historical Records (HRs) |
| `indexed` | Field keys used for search/filter |
| `short_display` | Field keys shown in compact/card view |
| `manual_fields` / `semi_automatic_fields` / `ai_fields` | Fields classified by transcription method |

Only proceed to the analysis questions below once the config file exists and the namespace/slug are set.

---

## Question 1 — What is the geometry situation?

Identify which of the following cases applies, as they require different production patterns:

**Do not assume every dataset needs RDE Geometry, Map, or Layer objects.** First decide whether the source geometry is a reusable/vector layer in its own right, or whether it is only the coordinate evidence for observations. If the source contains only point locations that are equivalent to observation coordinates, generate observations directly; do **not** generate map/layer/geometries just to mirror those points.

**Do not generate PoIs in dataset-specific production scripts.** PoIs are produced and reconciled by the dedicated PoI/observation merge workflow, not by individual `rde/datasets/<dataset-slug>/produce_*.py` scripts. In dataset scripts, leave `Observation.part_of_point_of_interest` unset/`None` unless you are intentionally referencing an already-existing PoI UUID supplied by a separate authoritative process.

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

**Production decision:** if these points only locate records, treat them as observation coordinates and generate corresponding Observations. Keep `has_geometries=[]` and do not create a map folder, layer, or geometry RDEs. Only create a map/layer/geometry set for points when the point collection is intended to be a standalone vector layer users should toggle independently of observations.

**Production pattern:**
```python
gdf['geometry'] = gdf.apply(lambda x: Point(x['longitude'], x['latitude']), axis=1)
# observation coordinate = geometry directly
obs = Observation(
    id=(uuid_manager, str(row[UNIQUE_ID_COL])),
    historical_record=hr.id,
    geometry=row.geometry,
    has_geometries=[],
    part_of_point_of_interest=True # should be False only in the case the current observation needs spatial indexing without a PoI for interaction on the map. 
)
```

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


### 3f. HR card labels: choose a meaningful main label and sublabel

`main_label` and `sub_label` control the two textual lines used to identify an **Historical Record (HR)** in search results and card views. They are formatting strings, not bare field keys: use the configured metadata keys as `${field_name}`, combining fields only where the combination makes one clear human-readable identification.

The interface already displays the HR time range. **Never include a date, year, date range, temporal precision, or date comment in either `main_label` or `sub_label`, even when it is a valuable metadata field.** Keep such information in metadata and, when useful, `short_display` or `indexed`.

#### Selection principles

1. **Make the main label answer “what record is this?”** Choose the record's strongest human-facing identifier: a title, a named person, a place/building name, a document entry heading, or a concise subject label. Prefer a transcription or normalized value that readers can understand over internal codes.
2. **Make the sublabel add a different discriminator.** Use a role, profession, place, property function, author/creator, or concise description. Do not repeat the main label, merely restate part of it, or put a weaker version of the same value on the second line.
3. **Use the source's own granularity.** Labels identify the HR, not its observation or a future PoI. For example, an entry about an owner and a parcel should foreground the owner or the entry label; a photograph should foreground its title or depicted building, not an unrelated geocoded administrative value.
4. **Prefer stable, legible metadata.** Avoid internal IDs, UUIDs, page/folio numbers, file paths, URLs, OCR confidence, provenance, extraction/review status, coordinates, and technical measurements such as length, area, or energy values. These remain useful as metadata, filters, or short-display fields.
5. **Avoid long, noisy text.** A short description, transcription, or comment is acceptable only when no concise title/name exists. Do not make a raw full transcription the default label if it is likely to be a paragraph or boilerplate.
6. **Plan for missing values.** A label must remain informative for ordinary records. Do not choose a sparse field as the sole main label; select a populated fallback field or create a source-derived display field during production when the data warrants it. Do not fill missing labels with identifiers merely to satisfy the configuration.
7. **Use source language deliberately.** Preserve historically meaningful names and titles. When a standardized or translated equivalent is clearly more useful for recognition, prefer it; retain the source transcription in metadata. Do not combine several alternative spellings just to make the label longer.

#### Label patterns by HR/document typology

| HR/document typology | Main label: prefer | Sublabel: prefer | Avoid in labels |
|---|---|---|---|
| Person, directory, census, apprenticeship, or transaction entry | Person's full name; for a relationship record, the meaningful pair of names | Profession, role, counterpart, organization, or address/place | Person IDs, rank/order numbers, date of entry |
| Cadastre, property, tenancy, or ownership record | Owner/occupant name, or a concise property/entry designation when the person is absent | Place/local name, parcel function/use, tenancy relation, or property type | Parcel/folio numbers as the only label; rent/tax/area measurements |
| Gazetteer, index, prosopography, or archival entry | Curated entry heading/display label, named entity, or normalized place/person name | Parish/district, occupation, entity type, or archival reference when it genuinely distinguishes entries | PDF/page/line positions, extraction confidence, review status |
| Photograph, postcard, artwork, map sheet, or other visual document | Supplied title; otherwise depicted building/landmark/place; otherwise a short curatorial subject | Creator/author, collection, locality, or concise description | Depiction/creation date, image URL, file reference, verbose visual/OCR text |
| Book, article, manuscript, or bibliographic/document record | Title or document/entry heading | Author/creator, owner/holding institution, collection, or document type | Citation alone, repository URL, page number |
| Building, infrastructure, or environmental/technical record | Building/street/place name; otherwise a human-readable class/type | Use/function, system/type, district, or another categorical characteristic | Length, area, height, energy, coordinates, and other raw measures |
| Journey, itinerary, event, or stay record | Named venue/event/place | Activity, route/stop, host, or concise non-temporal note | Stay/event dates or duration as a label |
| Generic record with no natural title | A short curated display field derived from the most meaningful available metadata | The best independent categorical or locational discriminator | Concatenated identifiers or an arbitrary first non-null column |

#### Configuring and reviewing the result

Use `${field_name}` placeholders, for example:

```json
"main_label": "${name}",
"sub_label": "${profession_eng}"
```

or, where the two fields together identify one person:

```json
"main_label": "${first_name} ${last_name}",
"sub_label": "${occupation}"
```

Before finalizing the configuration, inspect representative records including nulls, repeated names, and unusually long values. Check that the two lines can distinguish neighbouring search results without dates and that each line contains a reader-facing fact not already supplied by the interface.

Existing datasets illustrate the intended semantic pattern: person + profession (`amsterdam-1832-huurwarden`, `venice-1857-commercial-directory`), owner + place (`venice-1740-catastici`, `venice-1808-sommarioni`, `venice-dorigo`), title/building + creator or description (`lausanne-mhl-iconographie`, `venice-cini-photographs`), and curated entry + parish (`venice-1582-catastici`). Treat configurations that use a date or a raw measurement in a label as legacy examples to improve when that dataset is next revised; do not copy that choice into new configurations.


When constructing the dataset with `Dataset.constructor_from_dataconfiguration_file_and_dataframe(...)`, the `sources` argument must contain only UUIDs of TimeAtlas/IIIF source objects such as collections, manifests, or documents generated or referenced by the production pipeline. Do **not** put DOIs, external URLs, archival web pages, image URLs, repository URLs, citations, or free-text source labels in `sources`; those belong in `dataset_metadata_config` as metadata fields.

---

## Checklist Before Writing the Production Script

Run through these checks and note the answers:

```
[ ] Geometry type: polygon / point coordinates / none / mixed
[ ] Obs derived from geometry centroid, or taken directly from coords?
[ ] Does this dataset actually need Geometry/Map/Layer RDEs, or are source points only observation coordinates?
[ ] Confirm the dataset script does not generate PoIs directly
[ ] HR:Obs cardinality: 1:1 / N:1 / 1:N
[ ] Unique identifier column confirmed as unique
[ ] Time range: uniform (from config) or per-record (from source columns)
[ ] Fields with nullable values identified
[ ] Confirm the dataset script does not generate PoIs directly
[ ] Paradata class for each field determined (m / sa / a)
[ ] Main and sublabel identify the HR with complementary, reader-facing metadata
[ ] Neither label contains dates, years, date ranges, temporal precision, or date comments
[ ] Neither label relies on an ID, source location, URL, technical status, or raw measurement
[ ] Indexed fields identified (fields used for search/filter)
[ ] Short-display fields identified (fields shown in compact view)
[ ] IIIF / image sources present?
[ ] If using dataset `sources`, confirm each value is a collection/manifest/document UUID only
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
