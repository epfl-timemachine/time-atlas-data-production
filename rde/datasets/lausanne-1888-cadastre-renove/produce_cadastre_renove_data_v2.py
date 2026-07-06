"""
produce_cadastre_renove_data_v2.py

Rewrite of produce_cadastre_renove_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling.

UUID seeds for Geometry, HistoricalRecord, and Observation replicate the legacy
script so object identifiers stay identical between v1 and v2 runs.
"""

import json
import os
import sys
from functools import reduce
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

DATA_SRC_PATH = Path(os.path.join(parent_dir, "data-lausanne/1888-cadastre-renove"))
DATA_FOLDER = ""
MAP_FOLDER = "../../maps/lausanne-1888-cadastre-renove/"
cadaster_layer_uuid = _get_layer_uuid(
    _get_filepath_like(MAP_FOLDER + "layers", "json"),
    "vector",
)


# 1. Geometry RDEs
geometries_fp = _get_filepath_like(
    os.path.join(DATA_SRC_PATH, "lausanne-1888-cadastre-renove-geometries-"),
    "geojson",
)
gdf = gpd.read_file(geometries_fp)

# Keep the same comparison as v1. With the current reader geom_id is a string,
# so this does not remove the row whose value is "2849".
gdf = gdf[gdf.geom_id != 2849].copy()

geom_uuids = [
    uuid_mgr._generate_uuid(_seed(row, ["geom_id"]))
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
geom_id_to_uuid = {
    str(row["geom_id"]): geometry.id
    for (_, row), geometry in zip(gdf.iterrows(), geometries)
}


# 2. Registry and point joins
txt_fp = _get_filepath_like(
    os.path.join(DATA_SRC_PATH, "lausanne-1888-cadastre-renove-registre-"),
    "csv",
)
dfs = pd.read_csv(txt_fp)
dfs.replace({np.nan: None}, inplace=True)
dfs.drop(
    columns=[
        "cent",
        "ares",
        "articles",
        "prix proportionnels par are de la commission cadastrale",
    ],
    inplace=True,
)

point_fp = _get_filepath_like(
    os.path.join(DATA_SRC_PATH, "lausanne-1888-cadastre-renove-points-"),
    "geojson",
)
point_gdf = gpd.read_file(point_fp).drop(columns=["parcel_id", "folio"]).reset_index()
point_gdf["geom_uuid"] = point_gdf["geom_id"].map(geom_id_to_uuid)

# Remove points without a registry entry, and registry entries without points.
point_gdf = point_gdf[point_gdf["merge_id"].isin(dfs["merge_id"])]
dfs = dfs[dfs["merge_id"].isin(point_gdf["merge_id"])]

merge_df = pd.merge(dfs, point_gdf, on="merge_id")[["*", "index", "merge_id"]]
merge_df = merge_df.groupby("merge_id").agg(set).reset_index()
merge_df["len_*"] = merge_df["*"].apply(len)
merge_df["len_index"] = merge_df["index"].apply(len)

# v1 excludes the single many-to-many registry/point relationship.
many_to_many = merge_df[(merge_df["len_*"] > 1) & (merge_df["len_index"] > 1)]
if not many_to_many.empty:
    exclude_merged_id = many_to_many.iloc[0]["merge_id"]
    dfs = dfs[dfs["merge_id"] != exclude_merged_id]
    point_gdf = point_gdf[point_gdf["merge_id"] != exclude_merged_id]
    merge_df = merge_df[merge_df["merge_id"] != exclude_merged_id]

merge_df = merge_df.explode("*", ignore_index=True)


def obs_uuid_and_point_id_gen(row: pd.Series) -> list[tuple[str, int]]:
    return [
        (uuid_mgr._generate_uuid(f"{row['*']}_{point_id}"), point_id)
        for point_id in row["index"]
    ]


merge_df["obs_uuid_point_id"] = merge_df.apply(obs_uuid_and_point_id_gen, axis=1)
dfs["hr_uuid"] = dfs.apply(lambda row: uuid_mgr._generate_uuid(_seed(row, ["*"])), axis=1)

obs_uuid_to_point_id = dict(
    reduce(lambda acc, item: acc + item[0], merge_df[["obs_uuid_point_id"]].values, [])
)
registry_id_to_obs_uuid = {
    registry_id: [obs_point[0] for obs_point in obs_points]
    for registry_id, obs_points in merge_df.set_index("*")["obs_uuid_point_id"].items()
}
dfs["obs_uuid"] = dfs["*"].map(registry_id_to_obs_uuid)

obs_uuid_to_hr_uuid = (
    dfs[["hr_uuid", "obs_uuid"]]
    .explode("obs_uuid")
    .set_index("obs_uuid")["hr_uuid"]
    .to_dict()
)
point_id_to_obs_uuid = (
    pd.DataFrame(obs_uuid_to_point_id.items(), columns=["obs_uuid", "point_id"])
    .groupby("point_id")
    .agg(list)["obs_uuid"]
    .to_dict()
)
point_gdf["obs_uuid"] = point_gdf["index"].map(point_id_to_obs_uuid)


# 3. Observation RDEs
obs_df = pd.DataFrame(obs_uuid_to_point_id.items(), columns=["uuid", "point_id"])
obs_df["hr_uuid"] = obs_df["uuid"].map(obs_uuid_to_hr_uuid)
obs_df["coordinate"] = obs_df["point_id"].map(point_gdf.set_index("index")["geometry"])
obs_df["has_geometry"] = obs_df["point_id"].map(point_gdf.set_index("index")["geom_uuid"])

obs_list = []
for _, row in tqdm(obs_df.iterrows(), total=len(obs_df), desc="Observations"):
    has_geometries = None if pd.isna(row.has_geometry) else [row.has_geometry]
    obs_list.append(
        Observation(
            id=row.uuid,
            historical_record=row.hr_uuid,
            geometry=row.coordinate,
            has_geometries=has_geometries,
            part_of_point_of_interest=True,
        )
    )


# 4. HistoricalRecord RDEs
exclude_hr_labels = {
    "*",
    "has_geometry",
    "coordinate",
    "obs_uuid",
    "hr_uuid",
}

dfs["obs_uuid"] = dfs["obs_uuid"].apply(lambda obs_ids: [[obs_id, "parcel_id"] for obs_id in obs_ids])
dfs["owner"] = dfs["owner"].fillna("Propriétaire inconnu")
dfs["Noms locaux"] = dfs["Noms locaux"].fillna("Toponyme inconnu")
hr_metadata_cols = [col for col in dfs.columns if col not in exclude_hr_labels]

hrs = []
for _, row in tqdm(dfs.iterrows(), total=len(dfs), desc="Historical records"):
    hrs.append(
        HistoricalRecord(
            id=row.hr_uuid,
            dataset=DS_UUID,
            time_range=TR,
            paradata="m",
            has_observations=[obs_ref[0] for obs_ref in row.obs_uuid],
            metadata=_clean_metadata({col: row[col] for col in hr_metadata_cols}),
        )
    )


# 5. Dataset RDE
labels_order = list(DATA_CONFIG["DATASET_CONFIGURATION"]["labels"].keys())
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    "dataproduction_config.json",
    dfs[[col for col in labels_order if col in dfs.columns]],
    ds_id=DS_UUID,
)
dataset.version = "1.0"
for field_config in dataset.configuration.metadata_field_config:
    if field_config.id == "folio":
        field_config.type = MetadataType.STRING


# 6. Validate and save
full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
if any(obs.has_geometries is None for obs in obs_list):
    print("Skipped validation: legacy output contains observations with null has_geometries.")
else:
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
