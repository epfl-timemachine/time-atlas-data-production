"""
produce_dorigo_data_v2.py

Rewrite of produce_dorigo_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling.

UUID seeds for Geometry / HR / Observation replicate the legacy
CSV-serialisation strategy so object identifiers stay identical between
v1 and v2 runs.
"""

import json
import os
import sys
from functools import reduce
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.validation import make_valid


# Library path bootstrap
parent_dir = os.path.abspath("../../../")
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
timeatlas_dir = os.path.join(parent_dir, "time-atlas-python")
if timeatlas_dir not in sys.path:
    sys.path.insert(0, timeatlas_dir)

from timeatlas.RDEModel import (  # noqa: E402
    Dataset,
    Geometry,
    HistoricalRecord,
    Observation,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TimeAtlas import RDECollection  # noqa: E402
from timeatlas.production import (  # noqa: E402
    datetime_from_int,
    find_latest_file,
    find_layer_uuid,
    normalize_to_epsg4326,
    csv_seed,
)

from process.resolve_acronym import process_source_acronym  # noqa: E402


CITATION_FMT = "Dorigo W. (2003) “Venezia romanica”. Cierre edizioni. P."


def _union_geom_from_geometry_ids(geometry_ids: list[str], gdf: gpd.GeoDataFrame):
    if len(geometry_ids) > 1:
        return gdf[gdf["id"].isin(geometry_ids)].union_all(method="unary")
    return gdf[gdf["id"] == geometry_ids[0]]["geometry"].iloc[0]


def _geometry_uuids_from_ids(geometry_ids: list[str], gdf: gpd.GeoDataFrame) -> list[str]:
    return gdf[gdf["id"].isin(geometry_ids)]["uuid"].tolist()


def _pages_from_cell_ids(cell_ids: list[str], pages_by_annotation_id: dict[str, list[int]]) -> list[int]:
    pages = [
        pages_by_annotation_id[cell_id]
        for cell_id in cell_ids
        if cell_id and cell_id in pages_by_annotation_id
    ]
    if not pages:
        return []
    return sorted(set(reduce(lambda left, right: left + right, pages, [])))


def _try_parse_end_date(date_end) -> str | None:
    try:
        return datetime_from_int(date_end, match_to_end=True)
    except Exception:
        print(f"Could not parse date_end: {date_end}")
        return None


with open("dataproduction_config.json") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
TR = RDETimeRange(
    datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)

DORIGO_DATA_PATH = Path(os.path.join(parent_dir, "data-venice/Dorigo"))
DATA_FOLDER = ""
MAP_FOLDER = "../../maps/venice-dorigo/"
zones_layer_uuid = find_layer_uuid(
    find_latest_file(MAP_FOLDER + "layers", "json"),
    "venice-dorigo-map-zones",
)


# 1. Geometry RDEs
geometries_fp = list(DORIGO_DATA_PATH.rglob("*geometries.geojson"))[0]
gdf = normalize_to_epsg4326(gpd.read_file(geometries_fp))

gdf["geometry"] = gdf["geometry"].apply(lambda geom: geom if geom.is_valid else make_valid(geom))

geometries = Geometry.geometries_from_gdf(
    gdf,
    ["id"],
    zones_layer_uuid,
    uuid_manager=uuid_mgr,
    force_valid=True,
)
gdf["uuid"] = [geometry.id for geometry in geometries]


# 2. Historical source data
df = pd.read_json(list(DORIGO_DATA_PATH.rglob("*historical_records.json"))[0])
df = df.replace({np.nan: None})
df = df[~df["date_start"].isna()].copy()

df = process_source_acronym(df)
df.rename(columns={"source": "source_ocr", "source_resolved": "source"}, inplace=True)
df["start_time"] = df["date_start"].astype(int).apply(datetime_from_int)
df["end_time"] = df["date_end"].astype(int).apply(_try_parse_end_date)

with open(DORIGO_DATA_PATH / "ownerships_and_places/tables_manifest.json") as f:
    tables_manifest = json.load(f)

pages_by_annotation_id = {
    annotation["id"]: record["pages"]
    for record in tables_manifest
    for annotation in record["annotations"]
}
df["pages"] = df["table_cell_ids"].apply(
    lambda cell_ids: _pages_from_cell_ids(cell_ids, pages_by_annotation_id)
)
df["bibliographic_citation"] = df["pages"].apply(
    lambda pages: CITATION_FMT + "-".join(map(str, pages))
)


# 3. Observation geometry handles and UUID links
df["geometries"] = df["geometry_ids"].apply(
    lambda geometry_ids: _union_geom_from_geometry_ids(geometry_ids, gdf)
)
df["corrected_centroid"] = df["geometries"].apply(Geometry.representative_point_inside)
df["has_geometry"] = df["geometry_ids"].apply(
    lambda geometry_ids: _geometry_uuids_from_ids(geometry_ids, gdf)
)
df["hr_uuid"] = df.apply(lambda row: uuid_mgr._generate_uuid(csv_seed(row, ["id"])), axis=1)
df["obs_uuid"] = df.apply(
    lambda row: uuid_mgr._generate_uuid(csv_seed(row, ["id"], suffix="obs")),
    axis=1,
)


# 4. Observation RDEs
obs_list = Observation.observations_from_df(
    df,
    id_col="obs_uuid",
    hr_col="hr_uuid",
    geometry_col="corrected_centroid",
    has_geometries_col="has_geometry",
)


# 5. HistoricalRecord RDEs
hr_metadata_cols = [
    "bibliographic_citation",
    "place_name",
    "owner_name",
    "owner_title",
    "owner_last_name",
    "owner_first_name",
    "owner_name_appendix",
    "owner_ocr",
    "place_ocr",
    "date_comment",
    "source",
    "source_ocr",
]

df["owner_name"] = df["owner_name"].fillna("Unknown owner")
hrs = HistoricalRecord.historical_records_from_df(
    df,
    id_col="hr_uuid",
    obs_col="obs_uuid",
    dataset_id=DS_UUID,
    time_range=lambda row: RDETimeRange(row.start_time, row.end_time),
    metadata_cols=hr_metadata_cols,
)


# 6. Dataset RDE
labels_order = list(DATA_CONFIG["DATASET_CONFIGURATION"]["labels"].keys())
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    "dataproduction_config.json",
    df[[column for column in labels_order if column in df.columns]],
    ds_id=DS_UUID,
)
dataset.version = "1.1"


# 7. Validate and save
full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
full_collection.validate_data()
print("Validation passed.")

full_collection.save_rde_to_files(MAP_FOLDER, overwrite=False, rde_types=[Geometry])
print(f"Saved {len(geometries)} geometries to {MAP_FOLDER}")

full_collection.save_rde_to_files(
    DATA_FOLDER or ".",
    overwrite=False,
    rde_types=[HistoricalRecord, Observation, Dataset],
)
print(f"Saved {len(hrs)} HRs, {len(obs_list)} observations, and 1 dataset to current dir")
