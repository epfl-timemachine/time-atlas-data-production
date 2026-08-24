"""
produce_mhl_icono_data_v2.py

Rewrite of produce_mhl_icono_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling or utils/iiif.

UUID seeds for HR / Observation / IIIF document IDs replicate the legacy
CSV-serialisation strategy so the generated RDE objects remain comparable with
the original producer.
"""

import json
import os
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from tqdm import tqdm

# Library path bootstrap
parent_dir = os.path.abspath("../../../")
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

timeatlas_dir = os.path.join(parent_dir, "time-atlas-python")
if timeatlas_dir not in sys.path:
    sys.path.insert(0, timeatlas_dir)

from timeatlas.DocumentModel import Annotation, Collection, Document, Page
from timeatlas.RDEModel import (
    Dataset,
    HistoricalRecord,
    MultiLingualValue,
    Observation,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TimeAtlas import RDECollection
from timeatlas.production import datetime_from_int, csv_seed

IIIF_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"


with open("dataproduction_config.json", encoding="utf-8") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)

DATA_SRC_PATH = Path(parent_dir) / "data-lausanne" / "icono-data-processing"


def museris_record_url_from_image_url(image_url):
    """Build the Museris record URL using the image URL's authoritative ID."""
    match = re.search(r"(?:[?&]|&amp;)id=(\d+)", str(image_url))
    if match is None:
        raise ValueError(f"Could not extract a Museris ID from image URL: {image_url}")
    return f"https://museris.lausanne.ch/SGCM/Consultation.aspx?id={match.group(1)}"


# 1. Load and prepare source data
df_source = pd.read_json(next(DATA_SRC_PATH.glob("matched_records.json")))
df_source["record_url"] = df_source["image_url"].apply(museris_record_url_from_image_url)
image_ids = df_source["image_url"].str.extract(r"(?:[?&]|&amp;)id=(\d+)", expand=False)
record_ids = df_source["record_url"].str.extract(r"[?&]id=(\d+)", expand=False)
assert image_ids.notna().all(), "Every image URL must contain a Museris ID"
assert image_ids.equals(record_ids), "Museris IDs in record_url and image_url do not match"
df_source["geometry"] = df_source.apply(lambda row: Point(row["longitude"], row["latitude"]), axis=1)

institutions_to_keep = {
    "Musée Historique Lausanne",
    "Urbanisme",
}
gdf = df_source[df_source.institution.isin(institutions_to_keep)].copy()
gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326").drop(
    columns=["latitude", "longitude"]
)
gdf = gdf[gdf.start_year > 1500].copy()

df_wh = pd.read_csv(next(DATA_SRC_PATH.glob("wh_image_dimensions.csv")))
df_wh = df_wh[df_wh["image_url"].isin(gdf["image_url"])].copy()
df_wh["image_id"] = df_wh.image_url.apply(lambda url: f"image_{url.split('id=')[1]}.jpg")

gdf["start_time"] = gdf["start_year"].apply(lambda year: datetime_from_int(year * 10000 + 101))
gdf["end_time"] = gdf["end_year"].apply(
    lambda year: datetime_from_int(year * 10000 + 1231, match_to_end=True)
)
gdf["hr_uuid"] = gdf.apply(lambda row: uuid_mgr._generate_uuid(csv_seed(row, ["id"], "hr")), axis=1)
gdf["obs_uuid"] = gdf.apply(lambda row: uuid_mgr._generate_uuid(csv_seed(row, ["id"], "obs")), axis=1)


# 2. Observations
obs_list = Observation.observations_from_df(
    gdf,
    id_col="obs_uuid",
    hr_col="hr_uuid",
    geometry_col="geometry",
)


# 3. Merge image dimensions and generate IIIF manifests
df = gdf.merge(df_wh[["image_url", "image_id", "width", "height", "media_type"]], on="image_url")
df["display_title"] = df.apply(lambda row: f"({row['file_reference']}) {row['titre']}", axis=1)
df["image_fp"] = df["image_id"].apply(lambda image_id: "lausanne/mhl_iconographie/" + image_id)

os.makedirs("iiif/manifests", exist_ok=True)
os.makedirs("iiif/collections", exist_ok=True)

documents: dict[str, Document] = {}
for _, row in tqdm(df.iterrows(), total=len(df), desc="IIIF manifests"):
    manifest_uuid = uuid_mgr._generate_uuid(csv_seed(row, ["id"], "photograph_manifest"))
    canvas_uuid = uuid_mgr._generate_uuid(f"{DS_UUID}_{manifest_uuid}_0")
    description = row["description"] if pd.notna(row["description"]) else "No description available."

    page = Page(
        id=canvas_uuid,
        label=MultiLingualValue({"en": [row["display_title"]]}),
        format=row["media_type"],
        range_idx=0,
        height=int(row["height"]),
        width=int(row["width"]),
        object_ref=row["image_fp"],
        annotations=[
            Annotation(
                id=uuid_mgr._generate_uuid(f"annotation_{canvas_uuid}_{row['hr_uuid']}"),
                lang="en",
                value=row["display_title"],
                hr_id=row["hr_uuid"],
                external_resource=row["record_url"],
            )
        ],
    )
    document = Document(
        id=manifest_uuid,
        label=MultiLingualValue({"en": [f"{row['display_title']} {description}"]}),
        items=[page],
    )
    documents[manifest_uuid] = document
    with open(f"iiif/manifests/{manifest_uuid}.json", "w", encoding="utf-8") as f:
        json.dump(document.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

collection_uuid = uuid_mgr._generate_uuid(f"{DS_SLUG}_collection")
collection = Collection(
    id=collection_uuid,
    label=MultiLingualValue(
        {"en": ["Geolocated photographs from the MHL, Lausanne. Data retrieved from museris.lausanne.ch"]}
    ),
    items=list(documents.values()),
)
with open(f"iiif/collections/{collection_uuid}.json", "w", encoding="utf-8") as f:
    json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)


# 4. Historical Records
drop_cols = [
    "image_id",
    "width",
    "height",
    "media_type",
    "display_title",
    "image_fp",
    "geometry",
    "start_year",
    "end_year",
]
df_hr = df.drop(columns=drop_cols).replace({np.nan: None})
metadata_cols = [col for col in df_hr.columns if col not in {"hr_uuid", "obs_uuid", "start_time", "end_time"}]

hrs = HistoricalRecord.historical_records_from_df(
    df_hr,
    id_col="hr_uuid",
    obs_col="obs_uuid",
    dataset_id=DS_UUID,
    time_range=lambda row: RDETimeRange(row.start_time, row.end_time),
    metadata_cols=metadata_cols,
)


# 5. Dataset
labels_order = list(DATA_CONFIG["DATASET_CONFIGURATION"]["labels"].keys())
dataset_metadata_df = df_hr.drop(columns=["hr_uuid", "obs_uuid"])[labels_order].copy()
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    "dataproduction_config.json",
    dataset_metadata_df,
    ds_id=DS_UUID,
    sources=[collection_uuid],
)


# 6. Save RDE data
full_collection = RDECollection(hrs + obs_list + [dataset])
full_collection.save_rde_to_files(".", overwrite=True, rde_types=[HistoricalRecord, Observation, Dataset])
print(f"Saved {len(hrs)} HRs, {len(obs_list)} observations, 1 dataset -> .")
