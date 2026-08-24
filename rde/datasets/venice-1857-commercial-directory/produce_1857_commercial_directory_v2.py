"""
produce_1857_commercial_directory_v2.py

Rewrite of produce_1857_commercial_directory.py using the timeatlas library
classes directly, without procedural wrappers from utils/data_modeling or
utils/iiif.

UUID seeds for HistoricalRecord and Observation replicate the legacy
CSV-serialization strategy so object identifiers stay identical between v1 and
v2 runs.
"""

import json
import os
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt

# Library path bootstrap
parent_dir = os.path.abspath("../../../")
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
timeatlas_dir = os.path.join(parent_dir, "time-atlas-python")
if timeatlas_dir not in sys.path:
    sys.path.insert(0, timeatlas_dir)

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
from timeatlas.production import datetime_from_int, csv_seed  # noqa: E402
from timeatlas.TAEnums import MetadataType  # noqa: E402


IIIF_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"
IMG_LOC_PREFIX = "venice/commercial_guides/1857/pages"


with open("dataproduction_config.json") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
TR = RDETimeRange(
    datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)


# 1. Source data
source_csv = sorted(Path("src").rglob("1857_commercial_guide_with_pages_20*.csv"))[-1]
df = pd.read_csv(source_csv)
df = df[df.geometry.notna()].copy()
df = df.replace({np.nan: None})

df["name"] = df["FIRST_N"].str.replace(",", "", regex=False) + " " + df["LAST_N"]
df["name"] = df["name"].fillna("No name registered")
df["geometry"] = df["geometry"].apply(wkt.loads)
gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")


# 2. Historical records and observations
exclude_hr_labels = {
    "geometry",
    "obs_uuid",
    "hr_uuid",
}
hr_metadata_cols = [col for col in df.columns if col not in exclude_hr_labels]

gdf["obs_uuid"] = gdf.apply(lambda row: uuid_mgr._generate_uuid(csv_seed(row, ["index"], suffix="obs")), axis=1)
gdf["hr_uuid"] = gdf.apply(lambda row: uuid_mgr._generate_uuid(csv_seed(row, ["index"], suffix="hr")), axis=1)
obs_list = Observation.observations_from_df(
    gdf,
    id_col="obs_uuid",
    hr_col="hr_uuid",
    geometry_col="geometry",
)
hrs = HistoricalRecord.historical_records_from_df(
    gdf,
    id_col="hr_uuid",
    obs_col="obs_uuid",
    dataset_id=DS_UUID,
    time_range=TR,
    metadata_cols=hr_metadata_cols,
)


# 3. IIIF manifest and collection
os.makedirs("iiif/manifests", exist_ok=True)
os.makedirs("iiif/collections", exist_ok=True)

registry_label = {
    "en": ["Commercial guide of Venice from 1857"],
    "it": ["Guida commerciale di Venezia del 1857"],
    "fr": ["Annuaire commercial de Venise de 1857"],
}

df_pages = pd.read_csv("src/1857_img_wh.csv")
df_pages["page_num"] = df_pages["filename"].apply(
    lambda value: int(value.replace("_", "").replace(".jpg", "").replace("/", ""))
)
df_pages.sort_values(by="page_num", inplace=True)

manifest_uid = uuid_mgr._generate_uuid(f"manifest_{DS_SLUG}")
pages = []
page_by_id = {}
page_to_canvas = {}

for _, row in df_pages.iterrows():
    page_num = int(row["page_num"])
    page = Page(
        id=uuid_mgr._generate_uuid(f"{DS_SLUG}_{manifest_uid}_{page_num}"),
        label=MultiLingualValue({"it": [f"pg. {page_num}"]}),
        format=row["media_type"],
        range_idx=page_num,
        height=int(row["height"]),
        width=int(row["width"]),
        object_ref=f"{IMG_LOC_PREFIX}{row['filename']}",
    )
    pages.append(page)
    page_by_id[page.id] = page
    page_to_canvas[page_num] = page.id


col_in_order = [
    "LAST_N",
    "FIRST_N",
    "PER_GRP",
    "PER_COMPL",
    "LOC_PAR",
    "LOC_STR",
    "NUM",
    "LOC_COMPL",
]


def cg_1857_metadata_object_to_string_representation(metadata: dict) -> str:
    def quick_check(value) -> str:
        if isinstance(value, (int, np.integer)):
            return str(value)
        if isinstance(value, str) and value.lower() != "nan" and len(value) > 0:
            return value
        return ""

    values = [quick_check(metadata.get(col, "")) for col in col_in_order]
    return " ".join(value for value in values if len(value) > 0)


hr_rows = []
for hr in hrs:
    metadata = hr.metadata
    page_num = metadata.get("PAGE_NUM")
    canvas_id = page_to_canvas.get(page_num)
    if canvas_id is None:
        continue
    hr_rows.append(
        {
            "hr_id": hr.id,
            "canvas_id": canvas_id,
            "display": cg_1857_metadata_object_to_string_representation(metadata),
        }
    )

if hr_rows:
    df_iiif_links = pd.DataFrame(hr_rows)
    for canvas_id, group in df_iiif_links.groupby("canvas_id", sort=False):
        page = page_by_id[canvas_id]
        page.annotations = [
            Annotation(
                id=uuid_mgr._generate_uuid(f"annotation_{canvas_id}_{row['hr_id']}"),
                lang="en",
                value=row["display"],
                hr_id=row["hr_id"],
            )
            for _, row in group.iterrows()
        ]

document = Document(
    id=manifest_uid,
    label=MultiLingualValue(registry_label),
    items=pages,
)
with open(f"iiif/manifests/{manifest_uid}.json", "w", encoding="utf-8") as f:
    json.dump(document.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

collection_uid = uuid_mgr._generate_uuid(f"collection_{DS_SLUG}")
collection = Collection(
    id=collection_uid,
    label=MultiLingualValue(registry_label),
    items=[document],
)
with open(f"iiif/collections/{collection_uid}.json", "w", encoding="utf-8") as f:
    json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)


# 4. Dataset
labels_order = list(DATA_CONFIG["DATASET_CONFIGURATION"]["labels"].keys())
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    "dataproduction_config.json",
    gdf[[col for col in labels_order if col in gdf.columns]],
    ds_id=DS_UUID,
)
dataset.version = "1.0"

# 5. Validate and save
full_collection = RDECollection(hrs + obs_list + [dataset])
if any(obs.has_geometries is None for obs in obs_list):
    full_collection.validate_data(mode="raw")
    print("Validation passed in raw mode: legacy output contains observations with null has_geometries.")
else:
    full_collection.validate_data()
    print("Validation passed.")

full_collection.save_rde_to_files(
    ".",
    overwrite=True,
    rde_types=[HistoricalRecord, Observation, Dataset],
)

# The current upload tooling keeps datasets.json. RDECollection writes
# dataset.json, so normalize the filename for this repository layout.
dataset_file = Path("dataset.json")
if dataset_file.exists():
    shutil.move(str(dataset_file), "datasets.json")

print(f"Saved {len(hrs)} HRs, {len(obs_list)} observations, and 1 dataset to current dir")
