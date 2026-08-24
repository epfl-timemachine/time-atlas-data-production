"""
produce_raimund_hotels_data_v2.py

Rewrite of produce_raimund_hotels_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling or utils/iiif.

UUID seeds for HistoricalRecord and Observation replicate the legacy
make_uuid_from_row_selection CSV-serialisation strategy so object identifiers
stay identical between v1 and this version.
"""

import json
import os
import sys
from datetime import datetime

import geopandas as gpd
import pandas as pd
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
    HistoricalRecord,
    MultiLingualValue,
    Observation,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TAEnums import MetadataType  # noqa: E402
from timeatlas.TimeAtlas import RDECollection  # noqa: E402
from timeatlas.production import datetime_from_int, csv_seed  # noqa: E402


IIIF_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"

gpd.options.io_engine = "pyogrio"


def parse_stay_dates(date_field: str) -> tuple[str, str]:
    """Parse the compact date notation used by the source spreadsheet."""
    lines = date_field.split(",")
    first_stay = lines[0]
    first_date = datetime(
        year=2000 + int(first_stay[-2:]),
        month=int(first_stay.split(".")[1]),
        day=int(first_stay.split(".")[0]),
    )
    last_stay_end = lines[-1].split("/")[-1]
    last_date = datetime.strptime(last_stay_end, "%d.%m.%y")
    return (
        first_date.isoformat(),
        last_date.replace(hour=23, minute=59, second=59).isoformat(),
    )


def main() -> None:
    with open("dataproduction_config.json", encoding="utf-8") as f:
        data_config = json.load(f)

    uuid_mgr = UUIDManager(data_config["UUID_NAMESPACE"])
    ds_slug = data_config["DATASET_CONFIGURATION"]["slug"]
    ds_uuid = uuid_mgr._generate_uuid(ds_slug)

    # 1. Load and prepare source data
    gdf = gpd.read_file("src/hotels.geojson")
    gdf["start_time"], gdf["end_time"] = zip(*gdf["dates"].apply(parse_stay_dates))
    gdf["night_stays"] = gdf["dates"].apply(lambda dates: len(dates.split("/")) - 1)

    gdf["obs_uuid"] = gdf.apply(
        lambda row: uuid_mgr._generate_uuid(csv_seed(row, ["photo_name"], "obs")),
        axis=1,
    )
    gdf["hr_uuid"] = gdf.apply(
        lambda row: uuid_mgr._generate_uuid(csv_seed(row, ["photo_name"], "hr")),
        axis=1,
    )

    # 2. Observations
    observations = Observation.observations_from_df(
        gdf,
        id_col="obs_uuid",
        hr_col="hr_uuid",
        geometry_col="geometry",
    )

    # 3. IIIF manifests and collection
    df_wh = pd.read_csv("src/images_width_height.csv")
    df_wh["image_fp"] = df_wh["filename"].apply(lambda value: "lausanne/raimund_hotels/" + value)
    df = gdf.merge(df_wh, left_on="photo_name", right_on="filename")

    os.makedirs("iiif/manifests", exist_ok=True)
    os.makedirs("iiif/collections", exist_ok=True)

    documents: dict[str, Document] = {}
    for _, row in tqdm(df.iterrows(), total=len(df), desc="IIIF manifests"):
        manifest_uuid = uuid_mgr._generate_uuid(csv_seed(row, ["filename"], "hotel_photo_manifest"))
        canvas_uuid = uuid_mgr._generate_uuid(f"{ds_uuid}_{manifest_uuid}_0")
        annotation_value = row["photo_comment_en"]

        page = Page(
            id=canvas_uuid,
            label=MultiLingualValue({"en": [row["name"]]}),
            format=row["media_type"],
            range_idx=0,
            height=int(row["height"]),
            width=int(row["width"]),
            object_ref=row["image_fp"],
            annotations=[
                Annotation(
                    id=uuid_mgr._generate_uuid(f"annotation_{canvas_uuid}_{row['hr_uuid']}"),
                    lang="en",
                    value=annotation_value,
                    hr_id=row["hr_uuid"],
                )
            ],
        )
        document = Document(
            id=manifest_uuid,
            label=MultiLingualValue(
                {
                    "en": [row["photo_comment_en"]],
                    "de": [row["photo_comment_de"]],
                }
            ),
            items=[page],
        )
        documents[manifest_uuid] = document
        with open(f"iiif/manifests/{manifest_uuid}.json", "w", encoding="utf-8") as f:
            json.dump(document.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

    collection_uuid = uuid_mgr._generate_uuid(f"{ds_slug}_collection")
    collection = Collection(
        id=collection_uuid,
        label=MultiLingualValue(
            {
                "en": ["Raimund Journey - Hotels"],
                "fr": ["Voyage de Raimund - Hôtels"],
                "de": ["Raimunds Reise - Hotels"],
                "it": ["Viaggio di Raimund - Hotel"],
            }
        ),
        items=list(documents.values()),
    )
    with open(f"iiif/collections/{collection_uuid}.json", "w", encoding="utf-8") as f:
        json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

    # 4. Historical records
    hr_obs_df = gdf[["obs_uuid", "hr_uuid"]].groupby("hr_uuid").agg(list)
    hr_df = gdf.drop(columns=["geometry", "obs_uuid"]).set_index("hr_uuid")
    hr_df["obs_uuid"] = hr_obs_df["obs_uuid"]
    hr_df = hr_df.reset_index()

    metadata_cols = [
        col
        for col in hr_df.columns
        if col not in {"hr_uuid", "obs_uuid", "start_time", "end_time"}
    ]
    historical_records = HistoricalRecord.historical_records_from_df(
        hr_df,
        id_col="hr_uuid",
        obs_col="obs_uuid",
        dataset_id=ds_uuid,
        time_range=lambda row: RDETimeRange(row.start_time, row.end_time),
        metadata_cols=metadata_cols,
    )

    # 5. Dataset
    labels_order = list(data_config["DATASET_CONFIGURATION"]["labels"].keys())
    filtered_df = hr_df.drop(columns=["hr_uuid", "obs_uuid"])
    dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
        "dataproduction_config.json",
        filtered_df[[col for col in labels_order if col in filtered_df.columns]],
        sources=[collection_uuid],
        ds_id=ds_uuid,
    )
    dataset.version = "1.0"

    # The legacy configuration generator typed every metadata field here as STRING,
    # including integer-looking fields such as night_stays.
    for field_config in dataset.configuration.metadata_field_config:
        field_config.type = MetadataType.STRING

    # 6. Save
    full_collection = RDECollection(historical_records + observations + [dataset])
    if any(obs.has_geometries is None for obs in observations):
        full_collection.validate_data(mode="raw")
        print("Validation passed in raw mode: legacy output contains observations with null has_geometries.")
    else:
        full_collection.validate_data()
        print("Validation passed.")

    full_collection.save_rde_to_files(
        ".",
        overwrite=False,
        rde_types=[HistoricalRecord, Observation, Dataset],
    )
    print(f"Saved {len(historical_records)} HRs, {len(observations)} observations, and 1 dataset to current dir")


if __name__ == "__main__":
    main()
