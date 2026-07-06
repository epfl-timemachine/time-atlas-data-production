"""
Produce the Amsterdam 1647-1652 housing-rent dataset with TimeAtlas classes.

Source files are kept in the sibling folder ``../7473120``. The CSV contains the
transcribed register rows; the shapefile contains point geometries keyed by the
same identifier in its ``UID1`` field.
"""

import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from tqdm import tqdm


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TIMEATLAS_DIR = REPO_ROOT / "time-atlas-python"
if str(TIMEATLAS_DIR) not in sys.path:
    sys.path.insert(0, str(TIMEATLAS_DIR))

from timeatlas.RDEModel import (  # noqa: E402
    Dataset,
    HistoricalRecord,
    Observation,
    PointOfInterest,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TimeAtlas import RDECollection  # noqa: E402
from timeatlas.helpers import _clean_metadata, _datetime_from_int  # noqa: E402


SOURCE_DIR = SCRIPT_DIR.parent / "7473120"


def source_path(filename: str) -> Path:
    path = SOURCE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing source file: {path}")
    return path


def full_name(row: pd.Series, cols: list[str]) -> str | None:
    parts = [row.get(col) for col in cols]
    parts = [str(part).strip() for part in parts if pd.notna(part) and str(part).strip()]
    return " ".join(parts) or None


with open(SCRIPT_DIR / "dataproduction_config.json", encoding="utf-8") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
TIME_RANGE = RDETimeRange(
    _datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    _datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)

csv_columns = {
    "UID": "source_uid",
    "inventory nr.": "inventory_nr",
    "wijk": "wijk",
    "folio": "folio",
    "folio front/backside": "folio_side",
    "Ordernumber": "order_number",
    "Street": "street",
    "rent/own": "rent_or_own",
    "value": "rental_value",
    "tax": "tax",
    "notes": "notes",
    "FirstnameO": "owner_first_name",
    "PatronymO": "owner_patronym",
    "LastnameO": "owner_last_name",
    "owner_modifier": "owner_modifier",
    "FirstnameR": "renter_first_name",
    "PatronymR": "renter_patronym",
    "LastnameR": "renter_last_name",
    "renter_modifier": "renter_modifier",
}

df = pd.read_csv(source_path("Verponding1647-1652.csv"), encoding="utf-8-sig")
df = df.drop(columns=[col for col in df.columns if str(col).startswith("Unnamed:")])
df = df.rename(columns=csv_columns)
df["source_uid"] = df["source_uid"].astype(str)
df["owner_full_name"] = df.apply(
    lambda row: full_name(row, ["owner_first_name", "owner_patronym", "owner_last_name", "owner_modifier"]),
    axis=1,
)
df["renter_full_name"] = df.apply(
    lambda row: full_name(row, ["renter_first_name", "renter_patronym", "renter_last_name", "renter_modifier"]),
    axis=1,
)
df["ownership_status"] = df["rent_or_own"].map({"r": "rented", "o": "owner-occupied"}).fillna(df["rent_or_own"])

gdf = gpd.read_file(source_path("Verponding_wijken.shp"))
if gdf.crs is None:
    gdf = gdf.set_crs("EPSG:4326")
else:
    gdf = gdf.to_crs("EPSG:4326")

gdf = gdf.rename(
    columns={
        "UID": "geometry_uid",
        "UID1": "source_uid",
        "inventory": "geometry_inventory",
        "profession": "profession",
    }
)
gdf["source_uid"] = gdf["source_uid"].astype(str)

geometry_lookup = gdf[["source_uid", "geometry_uid", "profession", "geometry"]].copy()
df = df.merge(geometry_lookup, on="source_uid", how="left")
df = df.replace({np.nan: None})

metadata_cols = [
    col
    for col in DATA_CONFIG["DATASET_CONFIGURATION"]["labels"]
    if col in df.columns
]

hrs: list[HistoricalRecord] = []
obs_list: list[Observation] = []
for _, row in tqdm(df.iterrows(), total=len(df), desc="HRs & Obs"):
    hr_uuid = uuid_mgr._generate_uuid(f"historical-record:{row['source_uid']}")
    has_observations = []

    if isinstance(row["geometry"], Point):
        obs_uuid = uuid_mgr._generate_uuid(f"observation:{row['source_uid']}")
        has_observations.append(obs_uuid)
        obs_list.append(
            Observation(
                id=obs_uuid,
                historical_record=hr_uuid,
                geometry=row["geometry"],
                has_geometries=[],
                part_of_point_of_interest=True,
            )
        )

    hrs.append(
        HistoricalRecord(
            id=hr_uuid,
            dataset=DS_UUID,
            time_range=TIME_RANGE,
            paradata="m",
            has_observations=has_observations,
            metadata=_clean_metadata({col: row[col] for col in metadata_cols}),
        )
    )

dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    str(SCRIPT_DIR / "dataproduction_config.json"),
    pd.DataFrame([hr.metadata for hr in hrs])[[col for col in metadata_cols if col != "geometry"]],
    sources=[],
    ds_id=DS_UUID,
)
dataset.version = "1.0"

full_collection = RDECollection(hrs + obs_list + [dataset])
full_collection.validate_data()
print("Validation passed.")

full_collection.save_rde_to_files(
    str(SCRIPT_DIR),
    overwrite=True,
    rde_types=[HistoricalRecord, Observation, PointOfInterest, Dataset],
)
print(f"Saved {len(hrs)} HRs, {len(obs_list)} observations, {len(pois)} PoIs and 1 dataset -> {SCRIPT_DIR}")
