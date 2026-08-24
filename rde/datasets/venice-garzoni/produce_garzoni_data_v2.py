"""
produce_garzoni_data_v2.py

Rewrite of produce_garzoni_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling.

UUID seeds replicate the legacy CSV-serialization strategy so Geometry, HR,
Observation, Dataset, and external POI references remain stable.
"""

import json
import os
import sys
from datetime import datetime as dt

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from tqdm import tqdm

# Library path bootstrap.
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
    clean_metadata,
    datetime_from_int,
    find_latest_file,
    find_layer_uuid,
    csv_seed,
)

gpd.options.io_engine = "pyogrio"


def short_person_string_from_elems(
    full_name: str,
    gender: str,
    age: int,
    origin: str,
) -> str:
    base = f"{full_name}, {gender.lower().replace('grz:', '')}"
    if age and type(age) is int:
        base += f", {age}"
    if origin and type(origin) is str and len(origin) > 0:
        base += f", {origin}"
    return base


def correct_date_and_strptime(date_value: str) -> dt:
    """
    Preserve legacy date correction for non-leap February 29 and day zero dates.
    """
    try:
        return dt.strptime(date_value, "%Y-%m-%d")
    except Exception as exc:
        if "02-29" in date_value:
            return correct_date_and_strptime(date_value.replace("02-29", "01-03"))
        if "-00" in date_value:
            return correct_date_and_strptime(date_value.replace("-00", "-01"))
        raise exc


def parse_coordinates(coord: str) -> Point:
    c1, c2 = coord.split(" ")
    lat = float(c1.replace("Point(", ""))
    lon = float(c2.replace(")", ""))
    return Point(lat, lon)


def assert_unique(values: list[str], label: str) -> None:
    duplicates = pd.Series(values)[pd.Series(values).duplicated()].unique().tolist()
    if duplicates:
        raise ValueError(f"Duplicate {label} UUIDs: {duplicates[:10]}")


def validate_unresolved_poi_collection(
    hrs: list[HistoricalRecord],
    obs_list: list[Observation],
    geometries: list[Geometry],
    dataset: Dataset,
) -> None:
    """
    Validate links owned by this batch.

    Garzoni observations intentionally keep part_of_point_of_interest as the
    unresolved boolean flag emitted by v1.
    """
    all_ids = [rde.id for rde in [dataset] + hrs + obs_list + geometries]
    assert_unique(all_ids, "RDE")

    hr_ids = {hr.id for hr in hrs}
    obs_ids = {obs.id for obs in obs_list}
    geom_ids = {geom.id for geom in geometries}

    for hr in hrs:
        if hr.dataset != dataset.id:
            raise ValueError(f"HR {hr.id} references unexpected dataset {hr.dataset}")
        assert_unique([str(ref) for ref in hr.has_observations], f"HR {hr.id} observation references")
        missing_obs = [ref for ref in hr.has_observations if ref not in obs_ids]
        if missing_obs:
            raise ValueError(f"HR {hr.id} references missing observations: {missing_obs[:10]}")

    for obs in obs_list:
        if obs.historical_record not in hr_ids:
            raise ValueError(f"Observation {obs.id} references missing HR {obs.historical_record}")
        assert_unique([str(ref) for ref in obs.has_geometries], f"Observation {obs.id} geometry references")
        missing_geoms = [ref for ref in obs.has_geometries if ref not in geom_ids]
        if missing_geoms:
            raise ValueError(f"Observation {obs.id} references missing geometries: {missing_geoms[:10]}")


with open("dataproduction_config.json", encoding="utf-8") as f:
    DATA_CONFIG = json.load(f)

VENICE_DATA_SRC = os.path.join(parent_dir, "data-venice")
GARZONI_DATA_SRC = os.path.join(VENICE_DATA_SRC, "data-alignment/Garzoni")

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
TR = RDETimeRange(
    datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)

collection_manifest_uid = uuid_mgr._generate_uuid(f"collection_{DS_SLUG}")
MAP_FOLDER = "../../maps/venice-1740-parish/"
parish_layer_uuid = find_layer_uuid(find_latest_file(MAP_FOLDER + "layers", "json"), "parish")

# Geometry RDE production.
gdf = gpd.read_file(os.path.join(VENICE_DATA_SRC, "1740_redrawn_parishes_cleaned_wikidata_standardised.geojson"))
gdf["id"] = gdf["id"].astype(int)

sestiere_to_acronym = {
    "Castello": "CS",
    "Cannaregio": "CN",
    "S.Marco": "SM",
    "Dorsoduro": "DD",
    "S. Croce": "SC",
    "S. Polo": "SP",
    "San Marco": "SM",
}
gdf["district_acronym"] = gdf["SESTIERE"].apply(lambda v: sestiere_to_acronym[v])

geometries = Geometry.geometries_from_gdf(
    gdf,
    ["geometry"],
    parish_layer_uuid,
    uuid_manager=uuid_mgr,
)
geom_id_to_geom_uuid = (
    gdf.assign(uuid=[geometry.id for geometry in geometries])
    .groupby("id")["uuid"]
    .apply(list)
    .to_dict()
)

# Contract and people mention flattening.
print("loading garzoni data into a dataframe, this may take a while.")
garzoni_fp = os.path.join(GARZONI_DATA_SRC, "contracts_20240409_180544.xlsx")
contracts = pd.read_excel(garzoni_fp, engine="openpyxl", sheet_name="Person Mentions")

location_cols_primitive = ["Workshop - Parish", "Workshop - Insigna"]
location_cols = [f"{v} {k}" for k in location_cols_primitive for v in ["Master", "Guarantor", "Other"]]
roles = ["Apprentice", "Master", "Guarantor", "Other"]


def group_to_individual_mentions(contract_id: str, group: pd.DataFrame) -> pd.Series:
    vals = {
        "Contract ID": contract_id,
        "Apprentice": None,
        "Master": None,
        "Guarantor": None,
        "Other": None,
        "Master Workshop - Parish": None,
        "Master Workshop - Insigna": None,
        "Guarantor Workshop - Parish": None,
        "Guarantor Workshop - Insigna": None,
        "Other Workshop - Parish": None,
        "Other Workshop - Insigna": None,
    }
    for _, row in group.iterrows():
        id_line = short_person_string_from_elems(
            row["Full Name"],
            row["Gender"],
            row["Age"],
            row["Geo Origin - Transcript"],
        )
        if row["Tag"] in ("grz:Apprentice", "grz:Master"):
            vals[row["Tag"].replace("grz:", "")] = id_line
            vals["Profession - Standard Forms"] = row["Professions - Standard Forms"]
            vals["Profession - Transcripts"] = row["Professions - Transcripts"]
            if row["Workshop - Parish"]:
                vals["Master Workshop - Parish"] = row["Workshop - Parish"]
            if row["Workshop - Insigna"]:
                vals["Master Workshop - Insigna"] = row["Workshop - Insigna"]
        elif row["Tag"] == "grz:Guarantor":
            vals["Guarantor"] = id_line
            if row["Workshop - Parish"]:
                vals["Guarantor Workshop - Parish"] = row["Workshop - Parish"]
            if row["Workshop - Insigna"]:
                vals["Guarantor Workshop - Insigna"] = row["Workshop - Insigna"]
        elif row["Tag"] == "grz:Other":
            vals["Other"] = id_line
            if row["Workshop - Parish"]:
                vals["Other Workshop - Parish"] = row["Workshop - Parish"]
            if row["Workshop - Insigna"]:
                vals["Other Workshop - Insigna"] = row["Workshop - Insigna"]

    return pd.Series(vals)


vals = [
    group_to_individual_mentions(contract_id, group)
    for contract_id, group in contracts.groupby("Contract ID")
    .filter(lambda x: any((x["Workshop - Parish"].notnull())))
    .groupby("Contract ID")
]
df_flat_ = pd.DataFrame(vals)
df_flat = df_flat_[
    df_flat_["Master Workshop - Parish"].notnull()
    | df_flat_["Guarantor Workshop - Parish"].notnull()
]
df_flat = df_flat.replace({np.nan: None})

contract_ids_to_date = (
    pd.read_excel(garzoni_fp, engine="openpyxl", sheet_name="Contracts")
    .set_index("Contract ID")["Date"]
    .to_dict()
)
contract_ids_to_date = {
    key: correct_date_and_strptime(value)
    for key, value in contract_ids_to_date.items()
    if value != "0000-00-00"
}

img_path_fp = os.path.join(GARZONI_DATA_SRC, "contracts_id_to_img_path.json")
with open(img_path_fp, encoding="utf-8") as f:
    contracts_ids_to_img_path = json.load(f)

df_flat["date"] = df_flat["Contract ID"].apply(
    lambda value: contract_ids_to_date[value] if value in contract_ids_to_date else None
)
df_flat["start_time"] = df_flat["date"].apply(
    lambda value: value.replace(hour=0, minute=0, second=0).isoformat()
)
df_flat["end_time"] = df_flat["date"].apply(
    lambda value: value.replace(hour=23, minute=59, second=59).isoformat()
)
df_flat = df_flat[~df_flat.date.isna()].drop_duplicates()
df_flat["img_path"] = df_flat["Contract ID"].apply(
    lambda value: contracts_ids_to_img_path[value] if value in contracts_ids_to_img_path else None
)

grz_to_loc = pd.read_csv(os.path.join(GARZONI_DATA_SRC, "grz_parish_to_geometry_id_and_church_coordinates.csv"))
grz_to_loc["poi_uuid"] = [
    uuid_mgr._generate_uuid(csv_seed(row, ["church_coordinate"]))
    for _, row in grz_to_loc.iterrows()
]
grz_to_loc["church_coordinate"] = grz_to_loc["church_coordinate"].apply(parse_coordinates)

parish_loc_cols = [col for col in location_cols if "Parish" in col]
parish_id_suffix = " parish id"
for loc_col in parish_loc_cols:
    df_flat[loc_col + parish_id_suffix] = None

for idx, row in df_flat.iterrows():
    for loc_col in parish_loc_cols:
        curr_val = row[loc_col]
        if type(curr_val) is str and curr_val:
            if curr_val in grz_to_loc["grz_parish"].values:
                df_flat.at[idx, loc_col + parish_id_suffix] = (
                    grz_to_loc[grz_to_loc["grz_parish"] == curr_val].iloc[0]["poi_uuid"]
                )
            else:
                print(f"Could not find {curr_val} in the grz_to_loc dataframe")

for loc_col in parish_loc_cols:
    parish_id_col = loc_col + parish_id_suffix
    df_flat[parish_id_col] = df_flat.apply(
        lambda row: (
            uuid_mgr._generate_uuid(csv_seed(row, ["Contract ID"], loc_col)),
            row[parish_id_col],
        )
        if row[parish_id_col]
        else None,
        axis=1,
    )

df_flat["hr_uuid"] = [
    uuid_mgr._generate_uuid(csv_seed(row, ["Contract ID"]))
    for _, row in tqdm(df_flat.iterrows(), total=len(df_flat), desc="HR UUIDs")
]

# Observation RDE production.
poi_uuid_to_geom_id = grz_to_loc.set_index("poi_uuid")["geom_id"].to_dict()
poi_uuid_to_geom_uuid = {
    poi_uuid: geom_id_to_geom_uuid[geom_id]
    for poi_uuid, geom_id in poi_uuid_to_geom_id.items()
    if geom_id in geom_id_to_geom_uuid
}
poi_uuid_to_coord = grz_to_loc.set_index("poi_uuid")["church_coordinate"].to_dict()

obs_list: list[Observation] = []
for _, row in tqdm(df_flat.iterrows(), total=len(df_flat), desc="Observations"):
    for loc_col in parish_loc_cols:
        parish_id_col = loc_col + parish_id_suffix
        if row[parish_id_col]:
            obs_uuid, poi_uuid = row[parish_id_col]
            obs_list.append(
                Observation(
                    id=obs_uuid,
                    historical_record=row.hr_uuid,
                    geometry=poi_uuid_to_coord[poi_uuid],
                    has_geometries=poi_uuid_to_geom_uuid[poi_uuid],
                    part_of_point_of_interest=True,
                )
            )

# Historical Record RDE production.
for loc_col in parish_loc_cols:
    df_flat[loc_col] = df_flat[loc_col].apply(
        lambda value: value.replace("grz:", "").replace("_", " ")
        if type(value) is str
        else value
    )

hr_metadata_cols = df_flat.columns.difference(
    ["hr_uuid"]
    + [loc_col + parish_id_suffix for loc_col in parish_loc_cols]
    + ["date", "start_time", "end_time", "img_path"]
)

hrs: list[HistoricalRecord] = []
for _, row in tqdm(df_flat.iterrows(), total=len(df_flat), desc="Historical records"):
    obs_refs = [
        row[loc_col + parish_id_suffix][0]
        for loc_col in parish_loc_cols
        if row[loc_col + parish_id_suffix]
    ]
    hrs.append(
        HistoricalRecord(
            id=row.hr_uuid,
            dataset=DS_UUID,
            time_range=RDETimeRange(row.start_time, row.end_time),
            paradata="m",
            has_observations=obs_refs,
            metadata=clean_metadata(row[hr_metadata_cols].to_dict()),
        )
    )

# Dataset object production.
metadata_order = [
    "Apprentice",
    "Master",
    "Guarantor",
    "Profession - Standard Forms",
    "Master Workshop - Parish",
    "Master Workshop - Insigna",
    "Guarantor Workshop - Insigna",
    "Guarantor Workshop - Parish",
    "Profession - Transcripts",
    "Other",
    "Other Workshop - Insigna",
    "Other Workshop - Parish",
    "Contract ID",
]

dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    "dataproduction_config.json",
    df_flat[metadata_order],
    sources=[collection_manifest_uid],
    ds_id=DS_UUID,
)

# Save.
validate_unresolved_poi_collection(hrs, obs_list, geometries, dataset)
print("Validation passed for dataset-owned references. Unresolved POI flags preserved.")

full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
full_collection.save_rde_to_files(MAP_FOLDER, overwrite=False, rde_types=[Geometry])
print(f"Saved {len(geometries)} geometries to {MAP_FOLDER}")

full_collection.save_rde_to_files(".", overwrite=False, rde_types=[HistoricalRecord, Observation, Dataset])
print(f"Saved {len(hrs)} HRs, {len(obs_list)} observations, and 1 dataset to current dir")
