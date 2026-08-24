"""
produce_berney_data_v2.py

Rewrite of produce_berney_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling or utils/iiif.

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
from shapely.geometry import Point
from shapely.ops import unary_union
from tqdm import tqdm

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
    Geometry,
    HistoricalRecord,
    MultiLingualValue,
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
from timeatlas.TAEnums import MetadataType  # noqa: E402


IIIF_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"

with open("dataproduction_config.json") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
TR = RDETimeRange(
    datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)

DATA_SRC_PATH = Path(os.path.join(parent_dir, "data-lausanne/1831-cadastre-berney"))
DATA_FOLDER = ""
MAP_FOLDER = "../../maps/lausanne-1831-berney/"
cadaster_layer_uuid = find_layer_uuid(
    find_latest_file(MAP_FOLDER + "layers", "json"),
    "cadaster",
)


def compute_center(geoms: list) -> Point | None:
    if not geoms:
        return None
    if len(geoms) == 1:
        center = geoms[0].centroid
    else:
        center = unary_union(geoms).centroid
    return Point(center.x, center.y)


def format_filename_to_code(filename: str) -> str | int:
    code = filename.replace("PC_1827-1831_Berney_Vol-", "")
    if "legende" in code:
        code = code.replace("_legende", "") + " (légende)"
    code = code.split("_")[-1].replace(".jpg", "")
    return int(code) if code.isnumeric() else code


# 1. Geometry RDEs and registry rows
geometries_fp = DATA_SRC_PATH / "Berney_merge_legende_v7-7_formatted_for_timeatlas.geojson"
gdf = normalize_to_epsg4326(gpd.read_file(geometries_fp, use_arrow=True))
gdf["start_time"] = TR.start_time
gdf["end_time"] = TR.end_time

geometries = Geometry.geometries_from_gdf(
    gdf,
    ["geometry"],
    cadaster_layer_uuid,
    uuid_manager=uuid_mgr,
    force_valid=True,
)
gdf["uuid"] = [geometry.id for geometry in geometries]

df = gdf[gdf["identifier"] != ""].copy()
df = df.groupby("identifier").first().reset_index()

id_geoms = (
    df.groupby("identifier")
    .agg({"uuid": lambda values: list(values), "geometry": lambda values: list(values)})
    .reset_index()
)
id_geoms["center"] = id_geoms["geometry"].apply(compute_center)
id_to_geometries = id_geoms.set_index("identifier")["uuid"].to_dict()
id_to_center = id_geoms.set_index("identifier")["center"].to_dict()

df["has_geometry"] = df["identifier"].map(id_to_geometries)
df["center"] = df["identifier"].map(id_to_center)
df = df.drop(columns=["uuid"])

# 2. HistoricalRecord and Observation UUIDs
df["hr_uuid"] = [
    uuid_mgr._generate_uuid(csv_seed(row, ["identifier"], "hr"))
    for _, row in tqdm(df.iterrows(), total=len(df), desc="HistoricalRecord UUIDs")
]
df["obs_uuid"] = [
    uuid_mgr._generate_uuid(csv_seed(row, ["center"], "obs"))
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Observation UUIDs")
]


# 3. Observation RDEs
obs_df = df[["obs_uuid", "hr_uuid", "center", "has_geometry"]].copy().reset_index().set_index("obs_uuid")

obs_list = Observation.observations_from_df(
    obs_df.reset_index(),
    id_col="obs_uuid",
    hr_col="hr_uuid",
    geometry_col="center",
    has_geometries_col="has_geometry",
)


# 4. HistoricalRecord RDEs
exclude_hr_labels = {
    "geometry_id",
    "has_geometry",
    "obs_uuid",
    "hr_uuid",
    "geometry",
    "own_col_de",
    "page",
    "number",
}
drop_cols = {
    "page_filename",
    "center",
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


# 5. IIIF documents
hr_uuid_to_page_filename = df.set_index("hr_uuid")["page_filename"].to_dict()
df_pages = pd.read_csv(DATA_SRC_PATH / "wh_images.csv")
df_pages["page_num"] = df_pages["filename"].apply(format_filename_to_code)

manifest_uid = uuid_mgr._generate_uuid(f"manifest_{DS_SLUG}")
registry_label = MultiLingualValue(
    {
        "fr": ["Cadastre de Lausanne en 1831"],
        "en": ["Lausanne's cadaster in 1831"],
        "it": ["Cadastre di Losanna nel 1831"],
        "de": ["Kataster von Lausanne im Jahr 1831"],
        "nl": ["Kadaster van Lausanne in 1831"],
    }
)

pages = []
page_by_id: dict[str, Page] = {}
page_to_canvas: dict[str, str] = {}
img_loc_prefix = "lausanne/berney"
for idx, row in df_pages.iterrows():
    page = Page(
        id=uuid_mgr._generate_uuid(f"{DS_SLUG}_{manifest_uid}_{idx}"),
        label=MultiLingualValue({"fr": [f"pg. {row['page_num']}"]}),
        format=row["media_type"],
        range_idx=int(idx),
        height=int(row["height"]),
        width=int(row["width"]),
        object_ref=f"{img_loc_prefix}{row['filename']}",
    )
    pages.append(page)
    page_by_id[page.id] = page
    page_to_canvas[row["filename"]] = page.id

canvas_to_hr_list: dict[str, list[str]] = {}
for hr_uuid, page_filename in hr_uuid_to_page_filename.items():
    canvas_id = page_to_canvas.get(page_filename)
    if canvas_id is None:
        continue
    canvas_to_hr_list.setdefault(canvas_id, []).append(hr_uuid)

for canvas_id, hr_ids in canvas_to_hr_list.items():
    page = page_by_id[canvas_id]
    page.annotations = [
        Annotation(
            id=uuid_mgr._generate_uuid(f"annotation_{canvas_id}_{hr_uuid}"),
            hr_id=hr_uuid,
        )
        for hr_uuid in hr_ids
    ]

document = Document(id=manifest_uid, label=registry_label, items=pages)
collection_uid = uuid_mgr._generate_uuid(f"collection_{DS_SLUG}")
collection = Collection(id=collection_uid, label=registry_label, items=[document])

os.makedirs("iiif/manifests", exist_ok=True)
os.makedirs("iiif/collections", exist_ok=True)
with open(f"iiif/manifests/{manifest_uid}.json", "w", encoding="utf-8") as f:
    json.dump(document.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)
with open(f"iiif/collections/{collection_uid}.json", "w", encoding="utf-8") as f:
    json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)


# 6. Dataset RDE
labels_order = list(DATA_CONFIG["DATASET_CONFIGURATION"]["labels"].keys())
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    "dataproduction_config.json",
    df[[col for col in labels_order if col in df.columns]],
    sources=[collection_uid],
    ds_id=DS_UUID,
)
dataset.version = "1.0"
for field_config in dataset.configuration.metadata_field_config:
    if field_config.id in {"use", "area"}:
        field_config.type = MetadataType.STRING


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
