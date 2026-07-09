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
    DatasetConfiguration,
    FreeFormMetadata,
    Geometry,
    HistoricalRecord,
    MetadataFieldConfig,
    MultiLingualValue,
    Observation,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TimeAtlas import RDECollection  # noqa: E402
from timeatlas.TAEnums import METADATA_TYPE_TO_ENUM, ParadataValues  # noqa: E402
from timeatlas.helpers import (  # noqa: E402
    _clean_metadata,
    _datetime_from_int,
    _get_filepath_like,
    _get_layer_uuid,
    _seed,
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


def python_type_to_legacy_conf_type(value_type: type) -> str:
    if value_type is int or str(value_type).startswith("int"):
        return "INTEGER"
    if value_type is str or str(value_type) == "str":
        return "STRING"
    if value_type is float or str(value_type).startswith("float"):
        return "FLOAT"
    if value_type is list or value_type is np.ndarray:
        return "LIST"
    return str(value_type)


def get_legacy_likely_type_of_series(series: pd.Series):
    dtype = str(series.dtype)
    if dtype == "object":
        for value in series.values:
            if value:
                return type(value)
        return None
    return dtype


def is_legacy_empty_or_null(value) -> bool:
    if isinstance(value, (np.ndarray, pd.Series)):
        return value.size == 0 or np.any(pd.isna(value))
    if isinstance(value, list):
        return len(value) == 0 or any(pd.isna(value))
    if isinstance(value, str):
        return value.strip() == ""
    return np.any(pd.isna(value))


def quick_display_label(label: str) -> str:
    values = label.replace("_", " ").replace("-", "").split(" ")
    return " ".join(value[0].upper() + value[1:] for value in values)


def assert_no_overlap(left: list[str], right: list[str], left_name: str, right_name: str) -> None:
    overlap = set(left).intersection(set(right))
    if overlap:
        raise ValueError(f"The following fields are both in {left_name} and {right_name}: {overlap}")


def build_legacy_dataset_configuration(
    df: pd.DataFrame,
    config: dict,
) -> tuple[DatasetConfiguration, list[FreeFormMetadata]]:
    dataset_metadata_config = config["dataset_metadata_config"]
    indexable_array = config["indexed"]
    short_display = config["short_display"]
    hidden = config["hidden"]
    automatic_fields = config["automatic_fields"]
    semi_automatic_fields = config["semi_automatic_fields"]
    manual_fields = config["manual_fields"]
    ai_fields = config["ai_fields"]
    tagged_fields = config["tagged_fields"]
    labels = config["labels"]
    display_thumbnail = config["display_thumbnail"] if "display_thumbnail" in config else False
    external_source = config["external_source"] if "external_source" in config else False

    assert_no_overlap(automatic_fields, semi_automatic_fields, "automatic_fields", "semi_automatic_fields")
    assert_no_overlap(automatic_fields, manual_fields, "automatic_fields", "manual_fields")
    assert_no_overlap(automatic_fields, ai_fields, "automatic_fields", "ai_fields")
    assert_no_overlap(semi_automatic_fields, manual_fields, "semi_automatic_fields", "manual_fields")
    assert_no_overlap(semi_automatic_fields, ai_fields, "semi_automatic_fields", "ai_fields")
    assert_no_overlap(manual_fields, ai_fields, "manual_fields", "ai_fields")
    assert_no_overlap(hidden, short_display, "hidden", "short_display")

    dataset_metadata = [
        FreeFormMetadata(
            type=METADATA_TYPE_TO_ENUM[value["type"]],
            label=MultiLingualValue(values=value["display_label"]),
            value=MultiLingualValue(values=value["value"]),
        )
        for value in dataset_metadata_config.values()
    ]

    field_configs = []
    for col in df.columns:
        if "uid" in col:
            continue
        values = df[col]
        legacy_type = get_legacy_likely_type_of_series(values)
        conf_type = python_type_to_legacy_conf_type(legacy_type)
        curr_conf = MetadataFieldConfig(
            id=col,
            type=METADATA_TYPE_TO_ENUM[conf_type]
            if legacy_type in METADATA_TYPE_TO_ENUM
            else METADATA_TYPE_TO_ENUM["STRING"],
            display_label=MultiLingualValue(values=labels[col])
            if col in labels
            else quick_display_label(col),
            nullable=bool(is_legacy_empty_or_null(values)),
        )
        if col in indexable_array:
            curr_conf.indexable = True
        if col in hidden:
            curr_conf.hidden = True
        if col in short_display:
            curr_conf.short_display = True
        if col in tagged_fields:
            curr_conf.tag = tagged_fields[col]
        if col in automatic_fields:
            curr_conf.paradata = ParadataValues.AUTOMATIC.value
        elif col in semi_automatic_fields:
            curr_conf.paradata = ParadataValues.SEMIAUTOMATIC.value
        elif col in manual_fields:
            curr_conf.paradata = ParadataValues.MANUAL.value
        elif col in ai_fields:
            curr_conf.paradata = ParadataValues.AI.value
        field_configs.append(curr_conf)

    return (
        DatasetConfiguration(
            metadata_field_config=field_configs,
            main_label=config["main_label"],
            sub_label=config["sub_label"],
            display_thumbnail=display_thumbnail,
            external_source=external_source,
        ),
        dataset_metadata,
    )


def get_single_object_uuid(obj_fp: str) -> str:
    with open(obj_fp, encoding="utf-8") as f:
        return json.load(f)["rde_objects"][0]["id"]


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
    _datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    _datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)

collection_manifest_uid = uuid_mgr._generate_uuid(f"collection_{DS_SLUG}")
MAP_FOLDER = "../../maps/venice-1740-parish/"
parish_layer_uuid = _get_layer_uuid(_get_filepath_like(MAP_FOLDER + "layers", "json"), "parish")

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

geom_uuids = [uuid_mgr._generate_uuid(_seed(row, ["geometry"])) for _, row in gdf.iterrows()]
geometries = [
    Geometry(id=geom_uuid, geometry=row.geometry, part_of_layer=parish_layer_uuid)
    for geom_uuid, (_, row) in tqdm(
        zip(geom_uuids, gdf.iterrows()),
        total=len(gdf),
        desc="Geometries",
    )
]
geom_id_to_geom_uuid = gdf.assign(uuid=geom_uuids).groupby("id")["uuid"].apply(list).to_dict()

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
    uuid_mgr._generate_uuid(_seed(row, ["church_coordinate"]))
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
            uuid_mgr._generate_uuid(_seed(row, ["Contract ID"], loc_col)),
            row[parish_id_col],
        )
        if row[parish_id_col]
        else None,
        axis=1,
    )

df_flat["hr_uuid"] = [
    uuid_mgr._generate_uuid(_seed(row, ["Contract ID"]))
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
            metadata=_clean_metadata(row[hr_metadata_cols].to_dict()),
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

dataset_configuration, dataset_metadata = build_legacy_dataset_configuration(
    df_flat[metadata_order],
    DATA_CONFIG["DATASET_CONFIGURATION"],
)
dataset = Dataset(
    id=DS_UUID,
    slug=DS_SLUG,
    metadata=dataset_metadata,
    version="1.0",
    creation_time=dt.now().isoformat(),
    name=MultiLingualValue(values=DATA_CONFIG["DATASET_CONFIGURATION"]["name"]),
    sources=[collection_manifest_uid],
    time_range=TR,
    configuration=dataset_configuration,
    has_areas=[get_single_object_uuid(path) for path in DATA_CONFIG["AREA_LOCS"]],
)

# Save.
validate_unresolved_poi_collection(hrs, obs_list, geometries, dataset)
print("Validation passed for dataset-owned references. Unresolved POI flags preserved.")

full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
full_collection.save_rde_to_files(MAP_FOLDER, overwrite=False, rde_types=[Geometry])
print(f"Saved {len(geometries)} geometries to {MAP_FOLDER}")

full_collection.save_rde_to_files(".", overwrite=False, rde_types=[HistoricalRecord, Observation, Dataset])
print(f"Saved {len(hrs)} HRs, {len(obs_list)} observations, and 1 dataset to current dir")
