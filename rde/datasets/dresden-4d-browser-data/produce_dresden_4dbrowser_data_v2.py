"""
produce_dresden_4dbrowser_data_v2.py

Rewrite of produce_dresden_4dbrowser_data.py using the timeatlas library
classes directly, without procedural wrappers from utils/data_modeling or
utils/iiif.

UUID seeds for HistoricalRecord, Observation, Manifest, and Collection objects
replicate the legacy script so RDE object identifiers stay identical between v1
and v2 runs. Observations are intentionally written with the unresolved
``part_of_point_of_interest=True`` flag; the global POI merge step resolves
those flags later in the full production pipeline.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime as dt
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import Point
from tqdm import tqdm


# Library path bootstrap
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
os.chdir(SCRIPT_DIR)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TIMEATLAS_DIR = REPO_ROOT / "time-atlas-python"
if str(TIMEATLAS_DIR) not in sys.path:
    sys.path.insert(0, str(TIMEATLAS_DIR))

from timeatlas.DocumentModel import Annotation, Collection, Document, Page  # noqa: E402
from timeatlas.RDEModel import (  # noqa: E402
    Dataset,
    HistoricalRecord,
    MultiLingualValue,
    Observation,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TimeAtlas import RDECollection  # noqa: E402
from timeatlas.helpers import _clean_metadata, _get_area_uuids, _seed  # noqa: E402


IIIF_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"

with open(SCRIPT_DIR / "dataproduction_config.json", encoding="utf-8") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
AREA_UUIDS = _get_area_uuids(DATA_CONFIG["AREA_LOCS"])


def _parse_start_date(date_obj: dict, fallback: str) -> str:
    if "from" in date_obj:
        return dt.strptime(date_obj["from"], "%Y-%m-%d").isoformat()
    return fallback


def _parse_end_date(date_obj: dict, fallback: str, match_to_end: bool = False) -> str:
    if "to" not in date_obj:
        return fallback
    parsed = dt.strptime(date_obj["to"], "%Y-%m-%d")
    if match_to_end:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed.isoformat()


particles = [
    "_elb_",
    "_df_",
    "_tu_",
    "_b_",
]


def extract_image_name_from_id(image_id: str) -> str:
    """
    Example:

    rJ5Ttp3SM_df_bika100_0000745_motiv.jpg => df_bika100_0000745_motiv.jpg
    """
    # pesky exceptions...
    if image_id == "n4-AEV02P2_Frauenkirche_2.jpg":
        return "Frauenkirche_2.jpg"
    if image_id == "oZdXlelHb_pVAdwAEwV2F8Bq-Y79-EVw-0.jpg":
        return "pVAdwAEwV2F8Bq-Y79-EVw-0.jpg"
    if image_id == "GQY5WxrLD_pVAdwAEwV2F8Bq-Y79-EVw-120.jpg":
        return "pVAdwAEwV2F8Bq-Y79-EVw-120.jpg"
    if image_id == "6GCTvlgxW_pVAdwAEwV2F8Bq-Y79-EVw-240.jpg":
        return "pVAdwAEwV2F8Bq-Y79-EVw-240.jpg"
    if image_id == "r4iVpFcBk_R01qJLpOaxBCEQxmW2fpMg-0.jpg":
        return "R01qJLpOaxBCEQxmW2fpMg-0.jpg"
    if image_id == "EbT8P3itT_R01qJLpOaxBCEQxmW2fpMg-120.jpg":
        return "R01qJLpOaxBCEQxmW2fpMg-120.jpg"
    if image_id == "vpJmmMwzq_R01qJLpOaxBCEQxmW2fpMg-240.jpg":
        return "R01qJLpOaxBCEQxmW2fpMg-240.jpg"
    if image_id == "ojq_Ygoa__Visualisierung_Kulturpalast_Au_enansicht__Copyright_gmp_Architekten.jpg":
        return "Visualisierung_Kulturpalast_Au_enansicht__Copyright_gmp_Architekten.jpg"
    if image_id == "RMAVEX-dv_photo.jpg":
        return "photo.jpg"

    if "YsvzEFUMgTI" in image_id:
        return image_id.split("_")[-1]

    if "Vaak" in image_id:
        return "Vaak_" + image_id.split("_")[-1]

    particle = None
    for p in particles:
        if p in image_id:
            particle = p
            break
    if particle is None:
        raise ValueError(f"Unexpected image_id format: {image_id}")
    splits = image_id.split(particle)
    if len(splits) != 2:
        raise ValueError(f"Unexpected image_id format: {image_id}")
    _, post = splits
    return particle[1:] + post


# 1. Source data and temporal normalization
with open(SCRIPT_DIR / "src/404_images.txt", encoding="utf-8") as f:
    exclude_ids = f.read().splitlines()

df = pd.read_json(SCRIPT_DIR / "src/dresden_4d_data.json")
df = df[~df["id"].isin(exclude_ids)].copy()

df.rename(columns={"date": "date_obj"}, inplace=True)
df["geometry"] = df["camera"].apply(lambda value: Point(value["longitude"], value["latitude"]))

# Legacy behaviour: missing start dates use the dataset minimum; missing end dates
# use the dataset maximum without end-of-day expansion.
now_fallback = dt.now().isoformat()
min_date = df["date_obj"].apply(lambda value: _parse_start_date(value, now_fallback)).min()
max_date = df["date_obj"].apply(lambda value: _parse_end_date(value, min_date)).max()
df["start_time"] = df["date_obj"].apply(lambda value: _parse_start_date(value, min_date))
df["end_time"] = df["date_obj"].apply(lambda value: _parse_end_date(value, max_date, match_to_end=True))

gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")

gdf["obs_uuid"] = [
    uuid_mgr._generate_uuid(_seed(row, ["id"], "obs"))
    for _, row in tqdm(gdf.iterrows(), total=len(gdf), desc="Observation UUIDs")
]
gdf["hr_uuid"] = [
    uuid_mgr._generate_uuid(_seed(row, ["id"], "hr"))
    for _, row in tqdm(gdf.iterrows(), total=len(gdf), desc="HistoricalRecord UUIDs")
]


# 2. Observation RDEs
obs_list = [
    Observation(
        id=row.obs_uuid,
        historical_record=row.hr_uuid,
        geometry=row.geometry,
        has_geometries=None,
        part_of_point_of_interest=True,
    )
    for _, row in tqdm(gdf.iterrows(), total=len(gdf), desc="Observations")
]


# 3. HistoricalRecord RDEs
hr_obs_df = gdf[["obs_uuid", "hr_uuid"]].groupby("hr_uuid").agg(list)
hr_df = gdf.drop(columns=["id", "geometry", "obs_uuid"]).set_index("hr_uuid")
hr_df["obs_uuid"] = hr_obs_df["obs_uuid"]
hr_df = hr_df.reset_index()

drop_cols = [
    "file",
    "restrictedAccess",
    "date_obj",
    "camera",
    "spatialStatus",
    "vrcity_useAsTextureFrom",
    "vrcity_useAsTextureTo",
    "vrcity_projectionDistance",
    "annotationsAvailable",
    "pending",
    "needsValidation",
    "declined",
    "uploadedBy",
    "editedBy",
]
metadata_cols = [
    col
    for col in hr_df.columns
    if col not in {"hr_uuid", "obs_uuid", "start_time", "end_time", *drop_cols}
]

hrs = [
    HistoricalRecord(
        id=row.hr_uuid,
        dataset=DS_UUID,
        time_range=RDETimeRange(row.start_time, row.end_time),
        paradata="m",
        has_observations=[row.obs_uuid[0]],
        metadata=_clean_metadata({col: row[col] for col in metadata_cols}),
    )
    for _, row in tqdm(hr_df.iterrows(), total=len(hr_df), desc="Historical records")
]


# 4. IIIF manifests and collection
documents = {}
gdf["lat_lon"] = gdf["geometry"].apply(lambda geom: f"{geom.y},{geom.x}")
gdf["title"] = gdf["title"].fillna("Untitled")

for _, row in tqdm(gdf.iterrows(), total=len(gdf), desc="IIIF manifests"):
    file_obj = row["file"]
    filename = extract_image_name_from_id(row["id"])
    img_path = f"dresden/4d_browser/{filename}"
    manifest_uuid = uuid_mgr._generate_uuid(_seed(row, ["id"], "manifest"))
    original_source = f"https://4dbrowser.urbanhistory4d.org/explore/{row['lat_lon']}/image/{row['id']}"

    canvas_uuid = uuid_mgr._generate_uuid(f"{DS_UUID}_{manifest_uuid}_0")
    page = Page(
        id=canvas_uuid,
        label=MultiLingualValue({"en": [row["title"]]}),
        format="image/jpeg",
        range_idx=0,
        height=int(file_obj["height"]),
        width=int(file_obj["width"]),
        object_ref=img_path,
        annotations=[
            Annotation(
                id=uuid_mgr._generate_uuid(f"annotation_{canvas_uuid}_{row['hr_uuid']}"),
                lang="en",
                value=row["title"],
                hr_id=row["hr_uuid"],
                external_resource=original_source,
            )
        ],
    )
    documents[manifest_uuid] = Document(
        id=manifest_uuid,
        label=MultiLingualValue({"en": [row["title"]]}),
        items=[page],
    )

iiif_manifests_dir = SCRIPT_DIR / "iiif/manifests"
iiif_collections_dir = SCRIPT_DIR / "iiif/collections"
iiif_manifests_dir.mkdir(parents=True, exist_ok=True)
iiif_collections_dir.mkdir(parents=True, exist_ok=True)

for manifest_uuid, document in documents.items():
    with open(iiif_manifests_dir / f"{manifest_uuid}.json", "w", encoding="utf-8") as f:
        json.dump(document.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

collection_uuid = uuid_mgr._generate_uuid(f"{DS_SLUG}_collection")
collection = Collection(
    id=collection_uuid,
    label=MultiLingualValue({"en": ["Geolocated pictures of Dresden, Germany. Data retrieved from 4dbrowser.org."]}),
    items=list(documents.values()),
)
with open(iiif_collections_dir / f"{collection_uuid}.json", "w", encoding="utf-8") as f:
    json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)


# 5. Dataset RDE
labels_order = list(DATA_CONFIG["DATASET_CONFIGURATION"]["labels"].keys())
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    str(SCRIPT_DIR / "dataproduction_config.json"),
    hr_df[[col for col in labels_order if col in hr_df.columns]],
    sources=[collection_uuid],
    ds_id=DS_UUID,
)
dataset.time_range = RDETimeRange(min_date, max_date)
dataset.has_areas = AREA_UUIDS
dataset.version = "1.0"


# 6. Save RDE data
# This raw dataset intentionally keeps has_geometries=None to match the v1
# producer. RDECollection.validate_data expects iterable geometry references, so
# validation is left to the downstream full pipeline after POI consolidation.
full_collection = RDECollection(hrs + obs_list + [dataset])
full_collection.save_rde_to_files(
    str(SCRIPT_DIR),
    overwrite=True,
    rde_types=[HistoricalRecord, Observation, Dataset],
)
print(f"Saved {len(hrs)} HRs, {len(obs_list)} observations, and 1 dataset to {SCRIPT_DIR}")
