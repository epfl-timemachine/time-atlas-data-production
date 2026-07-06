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
    HistoricalRecord,
    Observation,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TimeAtlas import RDECollection  # noqa: E402
from timeatlas.helpers import (  # noqa: E402
    _clean_metadata,
    _datetime_from_int,
    _get_filepath_like,
    _get_layer_uuid,
    _seed,
)
from timeatlas.TAEnums import MetadataType  # noqa: E402


with open("dataproduction_config.json") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
TR = RDETimeRange(
    _datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    _datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)

DATA_SRC_PATH = Path("src")
DATA_FOLDER = ""
MAP_FOLDER = "../../maps/amsterdam-1832-huurwarden/"
cadaster_layer_uuid = _get_layer_uuid(
    _get_filepath_like(MAP_FOLDER + "layers", "json"),
    "huurwarden",
)


# 1. Geometry RDEs
geometries_fp = DATA_SRC_PATH / "1832_Adamhuurw_gebouwlaagkadaster"
gdf = gpd.read_file(geometries_fp).set_crs("EPSG:28992").to_crs("EPSG:4326")

geom_uuids = [
    uuid_mgr._generate_uuid(_seed(row, ["OBJECTID"]))
    for _, row in tqdm(gdf.iterrows(), total=len(gdf), desc="Geometry UUIDs")
]

geometries = [
    Geometry(
        id=geom_uuid,
        geometry=row.geometry,
        part_of_layer=cadaster_layer_uuid,
        force_valid=True,
    )
    for geom_uuid, (_, row) in tqdm(
        zip(geom_uuids, gdf.iterrows()),
        total=len(gdf),
        desc="Geometries",
    )
]
object_id_to_uuid = {
    row["OBJECTID"]: geometry.id
    for (_, row), geometry in zip(gdf.iterrows(), geometries)
}


# 2. Point layer, HistoricalRecord UUIDs, and Observation UUIDs
point_fp = DATA_SRC_PATH / "1832_AdamPointlayer"
df = gpd.read_file(point_fp).set_crs("EPSG:28992").to_crs("EPSG:4326")
df["has_geometry"] = df["OBJECTID"].map(object_id_to_uuid)

df["hr_uuid"] = [
    uuid_mgr._generate_uuid(_seed(row, ["OBJECTID"], "hr"))
    for _, row in tqdm(df.iterrows(), total=len(df), desc="HistoricalRecord UUIDs")
]
df["obs_uuid"] = [
    uuid_mgr._generate_uuid(_seed(row, ["OBJECTID"], "obs"))
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

obs_list = []
for _, row in tqdm(obs_df.reset_index().iterrows(), total=len(obs_df), desc="Observations"):
    obs_list.append(
        Observation(
            id=row.obs_uuid,
            historical_record=row.hr_uuid[0],
            geometry=row.geometry,
            has_geometries=[row.has_geometry],
            part_of_point_of_interest=True,
        )
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

hrs = []
for _, row in tqdm(df.iterrows(), total=len(df), desc="Historical records"):
    hrs.append(
        HistoricalRecord(
            id=row.hr_uuid,
            dataset=DS_UUID,
            time_range=TR,
            paradata="m",
            has_observations=[row.obs_uuid],
            metadata=_clean_metadata({col: row[col] for col in hr_metadata_cols}),
        )
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
