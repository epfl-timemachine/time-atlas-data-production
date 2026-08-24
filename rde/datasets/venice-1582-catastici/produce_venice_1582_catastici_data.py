"""Produce the 1582 Venice Redecima Catastici index dataset.

The source tables are the adjudicated semantic extraction materialized under
``src/asve445-semantic-gpt56-v8-final``.  Each index entry becomes one
HistoricalRecord.  Every distinct, high-confidence reconciled parish mentioned
by an entry becomes an Observation linked to the existing Venice 1740 parish
geometry.  The observation coordinate follows the Garzoni convention: the
parish church coordinate when available, otherwise a point inside the parish
polygon.

The script also creates one IIIF Presentation 3 manifest for the 402 scanned
pages.  HistoricalRecord annotations are attached to the canvas matching each
entry's PDF page.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point


DATASET_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATASET_DIR.parents[2]
TIMEATLAS_DIR = REPO_ROOT / "time-atlas-python"
for import_path in (REPO_ROOT, TIMEATLAS_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from timeatlas.DocumentModel import (  # noqa: E402
    Annotation,
    Collection,
    Document,
    Page,
    Selector,
    SelectorType,
)
from timeatlas.RDEModel import (  # noqa: E402
    Dataset,
    Geometry,
    HistoricalRecord,
    MultiLingualValue,
    Observation,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TimeAtlas import RDECollection  # noqa: E402
from timeatlas.production import clean_metadata, datetime_from_int  # noqa: E402
from timeatlas.TAEnums import MetadataType  # noqa: E402


CONFIG_PATH = DATASET_DIR / "dataproduction_config.json"
SOURCE_ROOT = DATASET_DIR / "src" / "asve445-semantic-gpt56-v8-final"
MATERIALIZED_DIR = SOURCE_ROOT / "materialized"
RECONCILIATION_DIR = SOURCE_ROOT / "parish_reconciliation"
IMAGE_METADATA_PATH = DATASET_DIR / "src" / "images_width_height.csv"
ENTRY_GEOMETRY_PATH = DATASET_DIR / "src" / "entry_geometry" / "entry_geometry.csv"

BIBLIOGRAPHICAL_CITATION_TEMPLATE = (
    "ASVe, Dieci savi alle decime in Rialto, Redecima 1582, "
    "Indice delle condizioni, pg. {page}"
)

PARISH_GEOJSON_PATH = (
    REPO_ROOT / "data-venice" / "1740_redrawn_parishes_cleaned_wikidata_standardised.geojson"
)
GARZONI_PARISH_COORDINATES_PATH = (
    REPO_ROOT
    / "data-venice"
    / "data-alignment"
    / "Garzoni"
    / "grz_parish_to_geometry_id_and_church_coordinates.csv"
)
PARISH_MAP_DIR = REPO_ROOT / "rde" / "maps" / "venice-1740-parish"

IIIF_IMAGE_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"
# DocumentModel URL-encodes this raw IIIF identifier once, producing the
# required ``venice%2Fcatastici_1582%2F`` prefix in published image URLs.
IIIF_IMAGE_IDENTIFIER_PREFIX = "venice/catastici_1582/"

GARZONI_UUID_NAMESPACE = "https://timemachine.epfl.ch/venice/garzoni"

# Canonical 1740 feature names whose spelling differs from the Garzoni parish
# vocabulary.  The selected rows supply church coordinates only; observations
# still link to the geometry of the reconciled 1740 feature ID.
GARZONI_NAME_OVERRIDES = {
    17: "grz:San_Zuane_Novo",
    22: "grz:San_Antonin",
    25: "grz:San_Biagio",
    33: "grz:Anzolo_Raffael",
    34: "grz:San_Nicolo_dei_Mendicoli",
    36: "grz:Santa_Margarita",
    40: "grz:San_Simeon_Piccolo",
    41: "grz:San_Simeon_Grande",
    42: "grz:San_Zan_Degola",
    43: "grz:San_Giacomo_dell_Orio",
    46: "grz:San_Cassan",
    49: "grz:San_Agostin",
    52: "grz:San_Aponal",
    55: "grz:San_Giovanni_Elemosinario",
    61: "grz:San_Geminian",
    67: "grz:San_Samuele",
    68: "grz:San_Angelo",
    69: "grz:San_Benetto",
    72: "grz:Santa_Agnese",
}


def ordered_unique(values) -> list:
    """Return non-empty values in first-occurrence order."""
    result = []
    seen = set()
    for value in values:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            continue
        value = str(value).strip()
        if not value or value.lower() == "nan" or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def grouped_values(
    dataframe: pd.DataFrame,
    value_col: str,
    *,
    formatter=None,
) -> dict[str, list[str]]:
    """Aggregate an ordered source table to ENTRY_ID -> unique string values."""
    if dataframe.empty:
        return {}
    sort_cols = [col for col in ("ENTRY_ID", "SEQUENCE") if col in dataframe.columns]
    ordered = dataframe.sort_values(sort_cols, kind="stable") if sort_cols else dataframe
    result = {}
    for entry_id, group in ordered.groupby("ENTRY_ID", sort=False):
        values = (
            [formatter(row) for _, row in group.iterrows()]
            if formatter
            else group[value_col].tolist()
        )
        result[str(entry_id)] = ordered_unique(values)
    return result


def parse_json_list(value) -> list[str]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    if isinstance(value, list):
        return ordered_unique(value)
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        parsed = [value]
    return ordered_unique(parsed if isinstance(parsed, list) else [parsed])


def normalize_parish_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    normalized = normalized.lower().replace("grz:", "").replace("_", " ")
    normalized = re.sub(r"\b(san|santa|santo|santi|sancti|ss)\b", "s", normalized)
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def parse_garzoni_point(value: str) -> Point:
    match = re.fullmatch(
        r"Point\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)",
        str(value),
    )
    if not match:
        raise ValueError(f"Invalid Garzoni point: {value}")
    return Point(float(match.group(1)), float(match.group(2)))


def build_metadata_dataframe(entries: pd.DataFrame) -> pd.DataFrame:
    people = pd.read_csv(MATERIALIZED_DIR / "people.csv")
    roles = pd.read_csv(MATERIALIZED_DIR / "roles_and_occupations.csv")
    places = pd.read_csv(MATERIALIZED_DIR / "places.csv")
    references = pd.read_csv(MATERIALIZED_DIR / "references.csv")
    relationships = pd.read_csv(MATERIALIZED_DIR / "relationships.csv")
    cross_references = pd.read_csv(MATERIALIZED_DIR / "cross_references.csv")
    places_reconciled = pd.read_csv(RECONCILIATION_DIR / "places_reconciled.csv")

    primary_people = grouped_values(
        people[people["ENTRY_ROLE"] == "holder"], "DISPLAY_NAME"
    )
    related_people = grouped_values(
        people[people["ENTRY_ROLE"] != "holder"], "DISPLAY_NAME"
    )
    occupations = grouped_values(
        roles[roles["ROLE_TYPE"] == "occupation"], "RAW_TEXT"
    )
    other_roles = grouped_values(
        roles[roles["ROLE_TYPE"] != "occupation"],
        "RAW_TEXT",
        formatter=lambda row: f"{row['ROLE_TYPE']}: {row['RAW_TEXT']}",
    )
    place_mentions = grouped_values(places, "RAW_TEXT")
    archival_references = grouped_values(references, "FULLY_QUALIFIED_KEY")
    relationship_values = grouped_values(
        relationships,
        "RAW_PHRASE",
        formatter=lambda row: f"{row['RELATION_TYPE']}: {row['RAW_PHRASE']}",
    )
    cross_reference_values = grouped_values(cross_references, "RAW_CROSS_REFERENCE")

    matched_parishes = places_reconciled[
        (places_reconciled["RECONCILIATION_SCOPE"] == "parish_candidate")
        & (places_reconciled["MATCH_STATUS"] == "matched")
        & (places_reconciled["MATCH_CONFIDENCE"] == "high")
    ]
    parishes = grouped_values(matched_parishes, "PARISH_CANONICAL_NAME")

    rows = []
    for _, entry in entries.sort_values(["PDF_PAGE", "SOURCE_LINE_START", "ENTRY_ID"]).iterrows():
        entry_id = str(entry["ENTRY_ID"])
        holders = primary_people.get(entry_id, [])
        display_label = "; ".join(holders) if holders else str(entry["RAW_ENTRY"])
        rows.append(
            {
                "DISPLAY_LABEL": display_label,
                "ENTRY_ID": entry_id,
                "PDF_PAGE": int(entry["PDF_PAGE"]),
                "PRINTED_PAGE": int(entry["PRINTED_PAGE"]),
                "CITATION": BIBLIOGRAPHICAL_CITATION_TEMPLATE.format(
                    page=int(entry["PRINTED_PAGE"])
                ),
                "SOURCE_LINE_START": int(entry["SOURCE_LINE_START"]),
                "SOURCE_LINE_END": int(entry["SOURCE_LINE_END"]),
                "INDEX_HEADING": entry["INDEX_HEADING"],
                "ENTRY_TYPE": entry["ENTRY_TYPE"],
                "RAW_ENTRY": entry["RAW_ENTRY"],
                "EDITORIAL_QUALIFIERS": parse_json_list(entry["EDITORIAL_QUALIFIER_RAW"]),
                "PRIMARY_PEOPLE": holders,
                "RELATED_PEOPLE": related_people.get(entry_id, []),
                "OCCUPATIONS": occupations.get(entry_id, []),
                "OTHER_ROLES": other_roles.get(entry_id, []),
                "PARISHES": parishes.get(entry_id, []),
                "PLACE_MENTIONS": place_mentions.get(entry_id, []),
                "ARCHIVAL_REFERENCES": archival_references.get(entry_id, []),
                "RELATIONSHIPS": relationship_values.get(entry_id, []),
                "CROSS_REFERENCES": cross_reference_values.get(entry_id, []),
                "EXTRACTION_CONFIDENCE": entry["EXTRACTION_CONFIDENCE"],
                "REVIEW_STATUS": entry["REVIEW_STATUS"],
                "REVIEW_NOTE": None if pd.isna(entry["REVIEW_NOTE"]) else entry["REVIEW_NOTE"],
            }
        )
    return pd.DataFrame(rows)


def load_exact_entry_selector_polygons(
    image_metadata: pd.DataFrame,
) -> dict[str, list[list[tuple[float, float]]]]:
    """Load exact source-span polygons and rescale them to IIIF canvas pixels."""
    geometry = pd.read_csv(ENTRY_GEOMETRY_PATH)
    if not geometry["ENTRY_ID"].is_unique:
        raise ValueError("Entry geometry must contain exactly one row per ENTRY_ID")

    image_by_page = image_metadata.set_index("PDF_PAGE")
    selectors = {}
    exact_rows = geometry[
        (geometry["MAPPING_STATUS"] == "mapped")
        & (geometry["ASSOCIATION_SCOPE"] == "exact_source_span")
    ]
    for _, row in exact_rows.iterrows():
        page_number = int(row["PDF_PAGE"])
        if page_number not in image_by_page.index:
            raise ValueError(f"Entry geometry refers to missing PDF page {page_number}")
        image_row = image_by_page.loc[page_number]
        scale_x = int(image_row["width"]) / float(row["CANVAS_WIDTH"])
        scale_y = int(image_row["height"]) / float(row["CANVAS_HEIGHT"])
        if not np.isclose(scale_x, scale_y):
            raise ValueError(
                f"Entry geometry page {page_number} needs a non-uniform transform "
                f"({scale_x}, {scale_y})"
            )
        source_polygons = json.loads(row["POLYGONS_JSON"])
        if not source_polygons:
            raise ValueError(f"Mapped entry {row['ENTRY_ID']} has no polygons")
        polygons = []
        for polygon in source_polygons:
            if not polygon:
                raise ValueError(f"Entry {row['ENTRY_ID']} contains an empty polygon")
            scaled = [
                (round(float(x) * scale_x, 6), round(float(y) * scale_y, 6))
                for x, y in polygon
            ]
            if any(
                x < 0 or y < 0 or x > int(image_row["width"]) or y > int(image_row["height"])
                for x, y in scaled
            ):
                raise ValueError(f"Entry {row['ENTRY_ID']} selector falls outside its IIIF canvas")
            polygons.append(scaled)
        selectors[str(row["ENTRY_ID"])] = polygons
    return selectors


def load_parish_geometry_and_coordinates(
    used_feature_ids: set[int],
) -> tuple[dict[int, Geometry], dict[int, Point], list[int]]:
    with (PARISH_MAP_DIR / "layers.json").open(encoding="utf-8") as file:
        layer_objects = json.load(file)["rde_objects"]
    parish_layers = [layer for layer in layer_objects if "parish" in layer["slug"]]
    if len(parish_layers) != 1:
        raise ValueError(f"Expected one 1740 parish layer, found {len(parish_layers)}")
    parish_layer_uuid = parish_layers[0]["id"]

    parish_gdf = gpd.read_file(PARISH_GEOJSON_PATH)
    parish_gdf["id"] = parish_gdf["id"].astype(int)
    if not used_feature_ids.issubset(set(parish_gdf["id"])):
        missing = sorted(used_feature_ids - set(parish_gdf["id"]))
        raise ValueError(f"Reconciled parish feature IDs absent from GeoJSON: {missing}")

    # Reproduce the UUIDs already serialized in rde/maps/venice-1740-parish.
    geometry_objects = Geometry.geometries_from_gdf(
        parish_gdf,
        ["geometry"],
        parish_layer_uuid,
        uuid_manager=UUIDManager(GARZONI_UUID_NAMESPACE),
    )
    geometry_by_feature = {
        int(feature_id): geometry
        for feature_id, geometry in zip(parish_gdf["id"], geometry_objects)
    }
    with (PARISH_MAP_DIR / "geometries.json").open(encoding="utf-8") as file:
        serialized_geometry_ids = {obj["id"] for obj in json.load(file)["rde_objects"]}
    if {geometry.id for geometry in geometry_objects} != serialized_geometry_ids:
        raise ValueError("Reproduced parish geometry UUIDs differ from the existing map")

    coordinate_rows = pd.read_csv(GARZONI_PARISH_COORDINATES_PATH)
    coordinate_rows["normalized_name"] = coordinate_rows["grz_parish"].map(normalize_parish_name)
    parish_row_by_feature = parish_gdf.set_index("id")
    coordinate_by_feature = {}
    fallback_feature_ids = []

    for feature_id in sorted(used_feature_ids):
        selected = pd.DataFrame()
        override_name = GARZONI_NAME_OVERRIDES.get(feature_id)
        if override_name:
            selected = coordinate_rows[coordinate_rows["grz_parish"] == override_name]
        else:
            canonical_name = parish_row_by_feature.loc[feature_id, "NAME"]
            selected = coordinate_rows[
                coordinate_rows["normalized_name"] == normalize_parish_name(canonical_name)
            ]

        if len(selected) == 1:
            coordinate_by_feature[feature_id] = parse_garzoni_point(
                selected.iloc[0]["church_coordinate"]
            )
        elif len(selected) == 0:
            # Sant'Eufemia and Ghetto Vecchio have no Garzoni church row.
            coordinate_by_feature[feature_id] = parish_row_by_feature.loc[
                feature_id, "geometry"
            ].representative_point()
            fallback_feature_ids.append(feature_id)
        else:
            raise ValueError(
                f"Ambiguous church coordinate for parish feature {feature_id}: "
                f"{selected['grz_parish'].tolist()}"
            )

    return geometry_by_feature, coordinate_by_feature, fallback_feature_ids


def main() -> None:
    # Dataset configs conventionally contain paths relative to their own folder.
    os.chdir(DATASET_DIR)
    with CONFIG_PATH.open(encoding="utf-8") as file:
        data_config = json.load(file)

    entries = pd.read_csv(MATERIALIZED_DIR / "entries.csv")
    if not entries["ENTRY_ID"].is_unique:
        raise ValueError("ENTRY_ID is not unique")
    if set(entries["PDF_PAGE"]) - set(range(1, 403)):
        raise ValueError("An entry refers to a PDF page outside 1..402")

    metadata_df = build_metadata_dataframe(entries)
    if len(metadata_df) != len(entries):
        raise ValueError("Metadata row count differs from entry count")

    places_reconciled = pd.read_csv(RECONCILIATION_DIR / "places_reconciled.csv")
    matched_places = places_reconciled[
        (places_reconciled["RECONCILIATION_SCOPE"] == "parish_candidate")
        & (places_reconciled["MATCH_STATUS"] == "matched")
        & (places_reconciled["MATCH_CONFIDENCE"] == "high")
    ].copy()
    matched_places["PARISH_FEATURE_ID"] = matched_places["PARISH_FEATURE_ID"].astype(int)
    observation_places = (
        matched_places[
            ["ENTRY_ID", "PARISH_FEATURE_ID", "PARISH_CANONICAL_NAME"]
        ]
        .drop_duplicates(["ENTRY_ID", "PARISH_FEATURE_ID"])
        .sort_values(["ENTRY_ID", "PARISH_FEATURE_ID"])
    )
    used_feature_ids = set(observation_places["PARISH_FEATURE_ID"])
    geometry_by_feature, coordinate_by_feature, fallback_feature_ids = (
        load_parish_geometry_and_coordinates(used_feature_ids)
    )

    uuid_manager = UUIDManager(data_config["UUID_NAMESPACE"])
    dataset_slug = data_config["DATASET_CONFIGURATION"]["slug"]
    dataset_uuid = uuid_manager._generate_uuid(dataset_slug)
    time_range = RDETimeRange(
        datetime_from_int(data_config["TIMERANGE_MINIMUM"]),
        datetime_from_int(data_config["TIMERANGE_MAXIMUM"], match_to_end=True),
    )

    # Build HRs first so Observation references can use the generated class-prefixed IDs.
    historical_records = []
    hr_by_entry_id = {}
    metadata_by_entry_id = metadata_df.set_index("ENTRY_ID", drop=False)
    metadata_columns = list(data_config["DATASET_CONFIGURATION"]["labels"])
    for entry_id, metadata_row in metadata_by_entry_id.iterrows():
        historical_record = HistoricalRecord(
            id=(uuid_manager, str(entry_id)),
            dataset=dataset_uuid,
            time_range=time_range,
            paradata="ai",
            has_observations=[],
            metadata=clean_metadata(metadata_row[metadata_columns].to_dict()),
        )
        historical_records.append(historical_record)
        hr_by_entry_id[str(entry_id)] = historical_record

    observations = []
    for _, place in observation_places.iterrows():
        entry_id = str(place["ENTRY_ID"])
        feature_id = int(place["PARISH_FEATURE_ID"])
        observation = Observation(
            id=(uuid_manager, f"{entry_id}:parish:{feature_id}"),
            historical_record=hr_by_entry_id[entry_id].id,
            geometry=coordinate_by_feature[feature_id],
            has_geometries=[geometry_by_feature[feature_id].id],
            part_of_point_of_interest=True,
        )
        observations.append(observation)
        hr_by_entry_id[entry_id].has_observations.append(observation.id)

    manifest_uuid = uuid_manager._generate_uuid(f"manifest_{dataset_slug}")
    collection_uuid = uuid_manager._generate_uuid(f"collection_{dataset_slug}")
    document_label = MultiLingualValue(
        {
            "en": ["1582 Redecima index – Dieci savi alle decime in Rialto, busta 445"],
            "it": ["Indice della Redecima 1582 – Dieci savi alle decime in Rialto, busta 445"],
            "fr": ["Index de la Redecima de 1582 – Dieci savi alle decime in Rialto, busta 445"],
        }
    )

    image_metadata = pd.read_csv(IMAGE_METADATA_PATH)
    image_metadata["filename"] = image_metadata["filename"].str.lstrip("/")
    image_metadata["PDF_PAGE"] = image_metadata["filename"].map(
        lambda filename: int(Path(filename).stem)
    )
    image_metadata = image_metadata.sort_values("PDF_PAGE")
    if image_metadata["PDF_PAGE"].tolist() != list(range(1, 403)):
        raise ValueError("Image metadata must contain exactly pages 001.jpeg through 402.jpeg")
    selector_polygons_by_entry_id = load_exact_entry_selector_polygons(image_metadata)

    page_by_number = {}
    pages = []
    for _, image_row in image_metadata.iterrows():
        page_number = int(image_row["PDF_PAGE"])
        page = Page(
            id=(uuid_manager, f"{dataset_slug}:page:{page_number:03d}"),
            label=MultiLingualValue(
                {
                    "en": [f"PDF page {page_number}"],
                    "it": [f"Pagina PDF {page_number}"],
                }
            ),
            format=image_row["media_type"],
            range_idx=page_number,
            height=int(image_row["height"]),
            width=int(image_row["width"]),
            object_ref=f"{IIIF_IMAGE_IDENTIFIER_PREFIX}{image_row['filename']}",
            annotations=[],
        )
        pages.append(page)
        page_by_number[page_number] = page

    for historical_record in historical_records:
        metadata = historical_record.metadata
        page_number = int(metadata["PDF_PAGE"])
        entry_id = str(metadata["ENTRY_ID"])
        selector = None
        if entry_id in selector_polygons_by_entry_id:
            selector = Selector(
                SelectorType.SVG,
                selector_polygons_by_entry_id[entry_id],
                page_by_number[page_number].id,
            )
        page_by_number[page_number].annotations.append(
            Annotation(
                id=(uuid_manager, f"source:{historical_record.id}"),
                lang="it",
                value=html.escape(str(metadata["RAW_ENTRY"])),
                hr_id=historical_record.id,
                selector=selector,
            )
        )

    document = Document(id=manifest_uuid, label=document_label, items=pages)
    iiif_manifest_dir = DATASET_DIR / "iiif" / "manifests"
    iiif_collection_dir = DATASET_DIR / "iiif" / "collections"
    iiif_manifest_dir.mkdir(parents=True, exist_ok=True)
    iiif_collection_dir.mkdir(parents=True, exist_ok=True)
    with (iiif_manifest_dir / f"{manifest_uuid}.json").open("w", encoding="utf-8") as file:
        json.dump(
            document.to_iiif(uuid_manager, IIIF_IMAGE_BASE_URL),
            file,
            indent=2,
            ensure_ascii=False,
        )
    iiif_collection = Collection(
        id=collection_uuid,
        label=document_label,
        items=[document],
    )
    with (iiif_collection_dir / f"{collection_uuid}.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            iiif_collection.to_iiif(IIIF_IMAGE_BASE_URL),
            file,
            indent=2,
            ensure_ascii=False,
        )

    dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
        str(CONFIG_PATH),
        metadata_df,
        sources=[collection_uuid],
        ds_id=dataset_uuid,
    )
    dataset.version = "1.0.0"
    # Empty lists are valid nullable LIST fields, but pandas' null detection does
    # not infer that semantic automatically.
    for field_config in dataset.configuration.metadata_field_config:
        if field_config.type is MetadataType.LIST:
            field_config.nullable = any(
                not value for value in metadata_df[field_config.id].tolist()
            )

    referenced_geometries = [geometry_by_feature[feature_id] for feature_id in sorted(used_feature_ids)]
    validation_collection = RDECollection(
        historical_records + observations + referenced_geometries + [dataset]
    )
    validation_collection.validate_data()
    validation_collection.save_rde_to_files(
        str(DATASET_DIR),
        overwrite=True,
        rde_types=[HistoricalRecord, Observation, Dataset],
        dataset_slug=dataset_slug,
    )

    print(
        f"Saved {len(historical_records)} HRs, {len(observations)} observations, "
        f"1 dataset, 1 IIIF manifest, and 1 IIIF collection with "
        f"{len(selector_polygons_by_entry_id)} exact SVG entry selectors."
    )
    print(
        f"Linked {len(used_feature_ids)} existing 1740 parish geometries; "
        f"polygon representative-point fallback used for feature IDs {fallback_feature_ids}."
    )


if __name__ == "__main__":
    main()
