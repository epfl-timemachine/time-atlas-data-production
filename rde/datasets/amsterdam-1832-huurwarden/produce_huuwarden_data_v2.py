"""
produce_huuwarden_data_v2.py

Rewrite of produce_huuwarden_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling.

UUID seeds for Geometry, HistoricalRecord, and Observation replicate the legacy
script so object identifiers stay identical between v1 and v2 runs.
"""

import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from tqdm import tqdm

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
    HeightInfo,
    HistoricalRecord,
    Observation,
    PointOfInterest,
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
from timeatlas.TAEnums import MetadataType  # noqa: E402
from utils.get_terrain_and_building_heights import processing_points  # noqa: E402


with open("dataproduction_config.json") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
TR = RDETimeRange(
    datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)

DATA_SRC_PATH = Path("src")
DATA_FOLDER = ""
MAP_FOLDER = "../../maps/amsterdam-1832-huurwarden/"
cadaster_layer_uuid = find_layer_uuid(
    find_latest_file(MAP_FOLDER + "layers", "json"),
    "huurwarden",
)


# 1. Geometry RDEs
geometries_fp = DATA_SRC_PATH / "1832_Adamhuurw_gebouwlaagkadaster"
gdf = normalize_to_epsg4326(gpd.read_file(geometries_fp), source_crs="EPSG:28992")

geometries = Geometry.geometries_from_gdf(
    gdf,
    ["OBJECTID"],
    cadaster_layer_uuid,
    uuid_manager=uuid_mgr,
    force_valid=True,
)
object_id_to_uuid = {
    row["OBJECTID"]: geometry.id
    for (_, row), geometry in zip(gdf.iterrows(), geometries)
}


# 2. Point layer, HistoricalRecord UUIDs, and Observation UUIDs
point_fp = DATA_SRC_PATH / "1832_AdamPointlayer"
df = normalize_to_epsg4326(gpd.read_file(point_fp), source_crs="EPSG:28992")
df["has_geometry"] = df["OBJECTID"].map(object_id_to_uuid)

df["hr_uuid"] = [
    uuid_mgr._generate_uuid(csv_seed(row, ["OBJECTID"], "hr"))
    for _, row in tqdm(df.iterrows(), total=len(df), desc="HistoricalRecord UUIDs")
]
df["obs_uuid"] = [
    uuid_mgr._generate_uuid(csv_seed(row, ["OBJECTID"], "obs"))
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Observation UUIDs")
]


# 3. Observation RDEs
obs_df = (
    df[["obs_uuid", "hr_uuid", "geometry"]]
    .groupby(by=["obs_uuid", "geometry"])
    .agg(list)
    .reset_index()
    .set_index("obs_uuid")
)
obs_df["has_geometry"] = (
    df[~df.duplicated("obs_uuid", keep="first")]
    .set_index("obs_uuid")["has_geometry"]
)
obs_df["hr_uuid"] = obs_df["hr_uuid"].apply(lambda values: values[0])

obs_list = Observation.observations_from_df(
    obs_df.reset_index(),
    id_col="obs_uuid",
    hr_col="hr_uuid",
    geometry_col="geometry",
    has_geometries_col="has_geometry",
)


# 4. HistoricalRecord RDEs
exclude_hr_labels = {
    "geometry_id",
    "has_geometry",
    "obs_uuid",
    "hr_uuid",
    "geometry",
}
drop_cols = {
    "Periode",
    "OBJECTID",
}
exclude_cols = exclude_hr_labels.union(drop_cols)

df = df.replace({np.nan: None})
hr_metadata_cols = list(set(df.columns).difference(exclude_cols))

hrs = HistoricalRecord.historical_records_from_df(
    df,
    id_col="hr_uuid",
    obs_col="obs_uuid",
    dataset_id=DS_UUID,
    time_range=TR,
    metadata_cols=hr_metadata_cols,
)


# 5. Dataset RDE
labels_order = list(DATA_CONFIG["DATASET_CONFIGURATION"]["labels"].keys())
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    "dataproduction_config.json",
    df[[col for col in labels_order if col in df.columns]],
    ds_id=DS_UUID,
)
dataset.version = "1.0"


# 6. Validate and save
full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
points_of_interest = full_collection.consolidate_data()
print(
    f"Produced {len(points_of_interest)} points of interest from "
    f"{len(obs_list)} observations."
)

poi_by_id = {poi.id: poi for poi in points_of_interest}
poi_heights = processing_points(
    gpd.GeoDataFrame(
        {"poi_id": list(poi_by_id)},
        geometry=[poi.geometry for poi in points_of_interest],
        crs="EPSG:4326",
    )
)
for _, row in poi_heights.iterrows():
    poi_by_id[row.poi_id].height = HeightInfo(
        terrain=float(row.terrain_height),
        building=float(row.building_height),
    )

full_collection.validate_data()
print("Validation passed.")

full_collection.save_rde_to_files(MAP_FOLDER, overwrite=False, rde_types=[Geometry])
print(f"Saved {len(geometries)} geometries to {MAP_FOLDER}")

full_collection.save_rde_to_files(
    DATA_FOLDER or ".",
    overwrite=False,
    rde_types=[HistoricalRecord, Observation, PointOfInterest, Dataset],
    dataset_slug=DS_SLUG,
)
print(
    f"Saved {len(hrs)} HRs, {len(obs_list)} observations, "
    f"{len(points_of_interest)} points of interest, and 1 dataset to current dir"
)
