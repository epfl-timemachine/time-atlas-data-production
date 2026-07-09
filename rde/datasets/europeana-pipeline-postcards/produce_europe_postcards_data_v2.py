"""
produce_europe_postcards_data_v2.py

Rewrite of produce_europe_postcards_data.py using the timeatlas library classes
directly for RDE and IIIF object construction.

The parsing and filtering steps intentionally mirror the legacy script. UUID
seeds are kept compatible with the old CSV-serialization strategy so the raw
RDE objects can be compared byte-for-byte by identity and payload.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from datetime import datetime as dt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely
from shapely import Point
from shapely.geometry.base import BaseGeometry
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TIMEATLAS_DIR = REPO_ROOT / "time-atlas-python"
if str(TIMEATLAS_DIR) not in sys.path:
    sys.path.insert(0, str(TIMEATLAS_DIR))

from timeatlas.DocumentModel import Annotation, Collection, Document, Page
from timeatlas.RDEModel import (
    Dataset,
    HistoricalRecord,
    MultiLingualValue,
    Observation,
    RDETimeRange,
    UUIDManager,
)
from timeatlas.TAEnums import RDEType
from timeatlas.TimeAtlas import RDECollection


IIIF_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"
DATA_FOLDER = BASE_DIR
SRC_DIR = BASE_DIR / "src"


def flatten(li: list) -> list:
    return [item for sublist in li for item in sublist]


def seed_from_row(row: pd.Series, cols: list[str], suffix: str = "") -> str:
    string_buffer = io.StringIO()
    row[cols].to_csv(string_buffer, index=False, header=False)
    return string_buffer.getvalue() + suffix


def extract_value_from_textual_body_with_semantic_prefix(purpose, value, sample):
    bodies = sample["body"]
    for body in bodies:
        if (
            body.get("purpose") == purpose
            and body.get("type") == "TextualBody"
            and body.get("value", "").startswith(f"{value}:")
        ):
            return body.get("value", "").replace(f"{value}: ", "")
    return None


def extract_value_from_type_with_purpose(tpe, purpose, sample, str_cont=None):
    bodies = sample["body"]
    for body in bodies:
        if (
            body.get("type") == tpe
            and body.get("purpose") == purpose
            and (str_cont is None or str_cont in body.get("value", ""))
        ):
            return body.get("value", "")
    return None


def extract_value_from_textual_body_with_purpose(purpose, sample):
    return extract_value_from_type_with_purpose("TextualBody", purpose, sample)


def extract_target_img(sample):
    if sample.get("target", {}).get("type") == "Image":
        return sample.get("target", {}).get("id")
    return None


def extract_google_search_results(sample):
    bodies = sample["body"]
    res = []
    for body in bodies:
        if body.get("type") == "Dataset" and body.get("purpose") == "linking":
            for entry in body.get("value", []):
                if "Partial match" in entry.get("type", ""):
                    res.append(f"Partial match: {entry.get('value', '')} - {entry.get('source', '')}")
                elif "Full match" in entry.get("type", ""):
                    res.append(f"Full match: {entry.get('value', '')} - {entry.get('source', '')}")
    return res


def extract_google_coordinates(sample):
    bodies = sample["body"]
    res = []
    for body in bodies:
        if body.get("type") == "Dataset" and body.get("purpose") == "linking":
            for entry in body.get("value", []):
                if coords := entry.get("object_coordinates"):
                    if isinstance(coords[0], list) and isinstance(coords[0][0], list):
                        res.append(flatten(coords))
                    else:
                        res.append(coords)
    return res if len(res) >= 1 else None


def extract_landmark_information(sample):
    bodies = sample["body"]
    res = []
    for body in bodies:
        if body.get("type") == "Dataset" and body.get("purpose") == "identifying":
            for entry in body.get("value", []):
                if "Landmark" in entry.get("type", ""):
                    val_str = entry.get("value", "")
                    if wd_id := entry.get("wikidata_id"):
                        val_str += f" (https://www.wikidata.org/wiki/{wd_id})"
                    res.append(val_str)
    return res


def extract_landmark_coordinates(sample):
    bodies = sample["body"]
    res = []
    for body in bodies:
        if body.get("type") == "Dataset" and body.get("purpose") == "identifying":
            for entry in body.get("value", []):
                if coords := entry.get("coordinates"):
                    res.append(coords)
    return res if len(res) >= 1 else None


JSON_PATH_PARSE_DICT = {
    "is_postcard": lambda s: extract_value_from_textual_body_with_semantic_prefix("classifying", "postcard", s),
    "back_postcard": lambda s: extract_value_from_textual_body_with_semantic_prefix("classifying", "postcard's back", s),
    "final_place": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "final_place", s),
    "final_country": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "final_country", s),
    "final_city": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "final_city", s),
    "filename": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "filename", s),
    "record_id": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "record_id", s),
    "description": lambda s: extract_value_from_textual_body_with_purpose("describing", s),
    "transcription": lambda s: extract_value_from_textual_body_with_purpose("transcribing", s),
    "date": lambda s: extract_value_from_textual_body_with_purpose("dating", s),
    "europeana_link": lambda s: extract_value_from_type_with_purpose("SpecificResource", "linking", s, "europeana.eu"),
    "rights_attribution": lambda s: extract_value_from_type_with_purpose("SpecificResource", "tagging", s),
    "reason": lambda s: extract_value_from_textual_body_with_purpose("commenting", s),
    "img_src": extract_target_img,
    "google_search": extract_google_search_results,
    "google_coordinates": extract_google_coordinates,
    "landmarks_identified": extract_landmark_information,
    "landmarks_coordinates": extract_landmark_coordinates,
}


def format_single_date_elem(date_elem):
    if pd.isna(date_elem):
        return None
    year = int(date_elem.replace("s", ""))
    begin = dt(year, 1, 1)
    end = dt(year + 10, 12, 31, 23, 59, 59)
    return begin.isoformat(), end.isoformat()


def resolve_area_loc_for_constructor(loc: str) -> str:
    path = Path(loc)
    if path.is_absolute():
        return str(path)
    candidates = [
        BASE_DIR / path,
        REPO_ROOT / "rde" / "areas" / "data" / path,
        REPO_ROOT / "rde" / "areas" / "data" / f"{loc}.json",
    ]
    return str(next((candidate for candidate in candidates if candidate.exists()), candidates[0]))


def is_array_like(value) -> bool:
    return isinstance(value, (list, tuple, np.ndarray, pd.Series))


def clean_hr_metadata(metadata: dict) -> dict:
    cleaned = {}
    for key, value in metadata.items():
        if str(value).lower() != "nan" and (is_array_like(value) or pd.notna(value)):
            cleaned[key] = value.tolist() if isinstance(value, (np.ndarray, pd.Series)) else list(value) if isinstance(value, tuple) else value
        else:
            cleaned[key] = None
    return cleaned


class ShapelyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, BaseGeometry):
            return json.loads(shapely.to_geojson(obj))
        return super().default(obj)


def decoded_rde_dict(obj) -> dict:
    return json.loads(json.dumps(obj.to_dict(), cls=ShapelyEncoder, ensure_ascii=False))


def save_batch(filename: str, objects: list[dict], name: str, rde_type: str) -> None:
    envelope = {
        "name": name,
        "type_in_file": [rde_type],
        "creation_time": dt.now().isoformat(),
        "rde_objects": objects,
    }
    with open(DATA_FOLDER / f"{filename}.json", "w", encoding="utf-8") as f:
        json.dump(envelope, f, indent=1, ensure_ascii=False)


def load_source_dataframe() -> tuple[pd.DataFrame, pd.DataFrame]:
    with open(SRC_DIR / "WebAnnotationModel-2500-sample-results.json", "r", encoding="utf-8") as f:
        cont25 = json.load(f)
    with open(SRC_DIR / "wam_full_results_internal.json", "r", encoding="utf-8") as f:
        cont22k = json.load(f)

    sampled_values = []
    for sample in tqdm(cont25 + cont22k, desc="Parsing WAM annotations"):
        sampled_values.append({key: parser(sample) for key, parser in JSON_PATH_PARSE_DICT.items()})

    exclude_record_ids = {
        "https___1914_1918_europeana_eu_contributions_19257_attachments_217301",
        "URN_NBN_SI_IMG_FF0770PS",
        "Culturalia_00199ba9_22f6_49a8_a623_faad8ee61ce6",
        "Culturalia_36fd4fc0_b88a_47cb_b443_24ed18570e83",
        "item_LWYGFYKNRSOET7CEVYNMZEDFBYR4VZOT",
        "https___www_esbirky_cz_detail_31569485",
    }

    df = pd.DataFrame(sampled_values)
    df = df[df["final_country"].notna() & df["final_city"].notna()]
    df = df[~df["record_id"].isin(exclude_record_ids)]

    with open(SRC_DIR / "cached_city_country_loc.json", "r", encoding="utf-8") as f:
        city_country_loc = json.load(f)
    with open(SRC_DIR / "city_country_old_to_new.json", "r", encoding="utf-8") as f:
        city_country_old_to_new = json.load(f)

    df["country_city"] = df["final_country"] + ", " + df["final_city"]
    df["country_city"].to_csv(SRC_DIR / "country_city_all_postcards.csv", index=False)
    df["country_city_coordinates"] = df["country_city"].apply(
        lambda value: city_country_loc.get(value if value not in city_country_old_to_new else city_country_old_to_new[value], None)
    )
    df = df[
        (df["landmarks_coordinates"].notna() | df["google_coordinates"].notna() | df["country_city_coordinates"].notna())
        & df["date"].notna()
    ]
    df = df[~df["record_id"].str.contains("S_TEK_photo_TEKA0221776")]

    df_wh_25 = pd.read_csv(SRC_DIR / "2500_imgs_width_height.csv")
    df_wh_22k = pd.read_csv(SRC_DIR / "27k_image_width_height_format.csv")
    df_wh = pd.read_csv(SRC_DIR / "all_imgs_wh_final_batch_europeana.csv")
    df_wh = pd.concat([df_wh, df_wh_25, df_wh_22k], ignore_index=True).drop_duplicates(subset=["filename"], keep="last")
    df_wh["filename"] = df_wh["filename"].apply(lambda value: value.split("/")[-1])
    df_wh["width"] = df_wh["width"].astype(int)
    df_wh["height"] = df_wh["height"].astype(int)

    all_coordinates = flatten(df["landmarks_coordinates"].dropna().tolist() + [flatten(value) for value in df["google_coordinates"].dropna().tolist()])
    max_lat = max(coord[1] for coord in all_coordinates)
    min_lat = min(coord[1] for coord in all_coordinates)
    max_lon = max(coord[0] for coord in all_coordinates)
    min_lon = min(coord[0] for coord in all_coordinates)
    print("Max point:", (max_lon, max_lat))
    print("Min point:", (min_lon, min_lat))

    return df, df_wh


def merge_duplicate_postcards(df: pd.DataFrame) -> pd.DataFrame:
    df_dup = df[df.duplicated(subset=["record_id"], keep=False)].sort_values(by=["record_id"]).copy()
    back_postcard_df = pd.read_csv(SRC_DIR / "back_of_postcard_detector_results.csv")
    back_postcard_df["answer"] = back_postcard_df["answer"].apply(lambda value: value.strip().lower().replace(".", ""))
    back_postcard_dict = back_postcard_df.set_index("filename")["answer"].to_dict()
    df_dup["back_postcard"] = df_dup.apply(
        lambda row: back_postcard_dict[row["filename"]] if row["filename"] in back_postcard_dict else row["back_postcard"],
        axis=1,
    )

    df_no_dup = df[~df["record_id"].isin(df_dup["record_id"].unique())].copy()

    def generate_single_row_from_postcard_group(group_key: str, rows: pd.DataFrame) -> pd.Series:
        try:
            first_entry = rows[rows["back_postcard"] == "no"].iloc[0].copy()
        except Exception:
            first_entry = rows.iloc[0].copy()

        country_city_coords = first_entry["country_city_coordinates"]
        if country_city_coords is None:
            for _, row in rows.iterrows():
                if row["country_city_coordinates"] is not None:
                    country_city_coords = row["country_city_coordinates"]
                    break
        first_entry["landmarks_coordinates"] = flatten(rows["landmarks_coordinates"].dropna().tolist())
        first_entry["google_coordinates"] = flatten(rows["google_coordinates"].dropna().tolist())
        first_entry["country_city_coordinates"] = country_city_coords
        first_entry["filename"] = rows.sort_values(by=["back_postcard"])["filename"].unique().tolist()
        first_entry["record_id"] = group_key
        return first_entry

    grouped_rows = [
        generate_single_row_from_postcard_group(group_key, rows)
        for group_key, rows in df_dup.groupby("record_id")
    ]
    df_dup_processed = pd.DataFrame(grouped_rows).reset_index(drop=True)
    df_no_dup["filename"] = df_no_dup["filename"].apply(lambda value: [value])
    return pd.concat([df_no_dup, df_dup_processed], ignore_index=True)


def get_all_coordinates_from_row(row):
    coords = []
    if isinstance(row["landmarks_coordinates"], list):
        coords.extend(row["landmarks_coordinates"])
    if isinstance(row["google_coordinates"], list):
        coords.extend(flatten(row["google_coordinates"]))
    return coords


def build_observations(df: pd.DataFrame, uuid_mgr: UUIDManager) -> tuple[list[Observation], list[dict]]:
    def quick_uuid(hr_uuid: str, coords: Any) -> str:
        return uuid_mgr._generate_uuid(f"{hr_uuid}-{coords}")

    df["coordinates"] = df.apply(get_all_coordinates_from_row, axis=1)
    df["coordinates"] = df["coordinates"].apply(lambda value: pd.Series(value).drop_duplicates().tolist())

    df_precise_coords = df[df["coordinates"].apply(len) > 0].copy()
    df_no_precise_coords = df[df["coordinates"].apply(len) == 0].copy()
    df_no_precise_coords["coordinates"] = df_no_precise_coords["country_city_coordinates"].apply(lambda value: [value])

    observations: list[Observation] = []
    observation_dicts: list[dict] = []

    def append_observations(rows: pd.DataFrame, need_poi: bool) -> None:
        rows = rows.copy()
        rows["obs_data"] = rows.apply(
            lambda row: [(coord, quick_uuid(row["hr_uuid"], coord)) for coord in row["coordinates"]],
            axis=1,
        )
        df_obs = rows[["obs_data", "hr_uuid"]].copy().explode("obs_data")
        df_obs["lat_lon"] = df_obs["obs_data"].apply(lambda value: value[0])
        df_obs["obs_uuid"] = df_obs["obs_data"].apply(lambda value: value[1])
        for _, row in tqdm(df_obs.iterrows(), total=len(df_obs), desc=f"Observations poi={need_poi}"):
            obs = Observation(
                id=row["obs_uuid"],
                historical_record=row["hr_uuid"],
                geometry=Point(row["lat_lon"][1], row["lat_lon"][0]),
                has_geometries=[],
                part_of_point_of_interest=need_poi,
            )
            observations.append(obs)
            obs_dict = decoded_rde_dict(obs)
            obs_dict["has_geometries"] = None
            observation_dicts.append(obs_dict)

    append_observations(df_precise_coords, True)
    append_observations(df_no_precise_coords, False)
    return observations, observation_dicts


def build_iiif(df: pd.DataFrame, df_wh: pd.DataFrame, uuid_mgr: UUIDManager, ds_uuid: str, ds_slug: str) -> str:
    filename_to_wh_infos = {
        row["filename"]: {
            "width": row["width"],
            "height": row["height"],
            "format": row["format"] if "format" in row else "media/jpeg",
        }
        for _, row in df_wh.iterrows()
    }

    manifests_dir = DATA_FOLDER / "iiif" / "manifests"
    collections_dir = DATA_FOLDER / "iiif" / "collections"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    collections_dir.mkdir(parents=True, exist_ok=True)

    documents: dict[str, Document] = {}
    df["image_fp"] = df["filename"].apply(lambda value: f"europeana/postcards/{value}")

    for _, row in tqdm(df.iterrows(), total=len(df), desc="IIIF manifests"):
        manifest_uuid = uuid_mgr._generate_uuid(seed_from_row(row, ["record_id"], "postcard_manifest"))
        description = row["description"]
        pages = []
        if len(row["filename"]) == 0:
            continue
        for page_idx, fname in enumerate(row["filename"]):
            try:
                if fname.endswith(".webp"):
                    fname = fname.replace(".webp", ".jpg")
                wh_info = filename_to_wh_infos.get(fname)
                if wh_info is None:
                    print(f"Warning: no width/height info for file {fname}")
                    continue
                canvas_uuid = uuid_mgr._generate_uuid(f"{ds_uuid}_{manifest_uuid}_{page_idx}")
                pages.append(
                    Page(
                        id=canvas_uuid,
                        label=MultiLingualValue({"en": [description]}),
                        format=wh_info["format"],
                        range_idx=page_idx,
                        height=int(wh_info["height"]),
                        width=int(wh_info["width"]),
                        object_ref=f"europeana/postcards/{fname}",
                        annotations=[
                            Annotation(
                                id=uuid_mgr._generate_uuid(f"annotation_{canvas_uuid}_{row['hr_uuid']}"),
                                lang="en" if description else None,
                                value=description,
                                hr_id=row["hr_uuid"],
                                external_resource=row["europeana_link"],
                            )
                        ],
                    )
                )
            except AttributeError:
                print(f"Error processing file {fname} for record {row['record_id']}. Skipping this file. Error details: {sys.exc_info()}")
        if not pages:
            continue
        doc = Document(
            id=manifest_uuid,
            label=MultiLingualValue({"en": [description]}),
            items=pages,
        )
        with open(manifests_dir / f"{manifest_uuid}.json", "w", encoding="utf-8") as f:
            json.dump(doc.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)
        documents[manifest_uuid] = doc

    collection_uuid = uuid_mgr._generate_uuid(f"{ds_slug}_collection")
    collection = Collection(
        id=collection_uuid,
        label=MultiLingualValue(
            {
                "en": [
                    f"{len(documents)} geolocated postcards from Europeana. Data retrieved from Europeana. Geolocation process done at EPFL."
                ]
            }
        ),
        items=list(documents.values()),
    )
    with open(collections_dir / f"{collection_uuid}.json", "w", encoding="utf-8") as f:
        json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

    return collection_uuid


def build_historical_records(
    df: pd.DataFrame,
    observations: list[Observation],
    ds_uuid: str,
) -> tuple[list[HistoricalRecord], list[dict], pd.DataFrame]:
    hr_uuid_to_obs_uuid: dict[str, list[str]] = {}
    for obs in observations:
        hr_uuid_to_obs_uuid.setdefault(obs.historical_record, []).append(obs.id)

    remove_cols_from_hr = [
        "back_postcard",
        "europeana_link",
        "google_coordinates",
        "landmarks_coordinates",
        "filename",
        "is_postcard",
        "country_city",
        "country_city_coordinates",
        "coordinates",
        "image_fp",
    ]
    df_hr = df.copy().drop(columns=remove_cols_from_hr)
    df_hr["obs_uuid"] = df_hr["hr_uuid"].map(hr_uuid_to_obs_uuid)
    df_hr = df_hr.replace({np.nan: None})

    hrs: list[HistoricalRecord] = []
    hr_dicts: list[dict] = []
    for _, row in tqdm(df_hr.iterrows(), total=len(df_hr), desc="Historical records"):
        metadata = row.drop(labels=["hr_uuid", "obs_uuid", "start_time", "end_time", "rights_attribution"]).to_dict()
        hr = HistoricalRecord(
            id=row["hr_uuid"],
            dataset=ds_uuid,
            time_range=RDETimeRange(row["start_time"], row["end_time"]),
            paradata="a",
            has_observations=row["obs_uuid"],
            metadata=clean_hr_metadata(metadata),
            rights_attribution=row["rights_attribution"],
        )
        hrs.append(hr)
        hr_dicts.append(decoded_rde_dict(hr))

    return hrs, hr_dicts, df_hr


def build_dataset(data_config: dict, df_hr: pd.DataFrame, ds_uuid: str, collection_uuid: str) -> dict:
    filtered_df = df_hr.drop(columns=["hr_uuid", "obs_uuid"])
    constructor_df = filtered_df.copy()
    # Preserve the v1 metadata configuration while still using the Dataset constructor.
    for col in ["google_search", "landmarks_identified"]:
        if col in constructor_df.columns:
            constructor_df[col] = constructor_df[col].apply(lambda value: None if value is None else str(value))
    constructor_config = dict(data_config)
    constructor_config["AREA_LOCS"] = [
        resolve_area_loc_for_constructor(loc)
        for loc in constructor_config.get("AREA_LOCS", [])
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as tmp_file:
        json.dump(constructor_config, tmp_file)
        tmp_file_path = tmp_file.name
    try:
        dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
            tmp_file_path,
            constructor_df,
            sources=[collection_uuid],
            ds_id=ds_uuid,
        )
    finally:
        os.unlink(tmp_file_path)
    return decoded_rde_dict(dataset)


def main() -> None:
    with open(BASE_DIR / "dataproduction_config.json", "r", encoding="utf-8") as f:
        data_config = json.load(f)

    uuid_mgr = UUIDManager(data_config["UUID_NAMESPACE"])
    ds_slug = data_config["DATASET_CONFIGURATION"]["slug"]
    ds_uuid = uuid_mgr._generate_uuid(ds_slug)

    df, df_wh = load_source_dataframe()
    df["start_time"], df["end_time"] = zip(*df["date"].apply(format_single_date_elem))
    df = merge_duplicate_postcards(df)
    df["hr_uuid"] = df.apply(lambda row: uuid_mgr._generate_uuid(seed_from_row(row, ["record_id"])), axis=1)
    df = df[
        ~df["record_id"].isin(
            [
                "bib_rnod_278752",
                "PMRMaeyaert_8321bdedf13106db26fe67c243765281938d1eb3",
            ]
        )
    ]

    observations, observation_dicts = build_observations(df, uuid_mgr)
    print(f"Total number of observations generated: {len(observation_dicts)}")
    save_batch("observations", observation_dicts, "europeana_postcards_obs", RDEType.OBS.value)

    collection_uuid = build_iiif(df, df_wh, uuid_mgr, ds_uuid, ds_slug)
    hrs, hr_dicts, df_hr = build_historical_records(df, observations, ds_uuid)
    save_batch("historical_records", hr_dicts, "europeana_postcards_hrs", RDEType.HR.value)

    dataset_dict = build_dataset(data_config, df_hr, ds_uuid, collection_uuid)
    save_batch("datasets", [dataset_dict], "europeana_postcards_dataset", RDEType.DATASET.value)

    validation_observations = [
        Observation(
            id=obs.id,
            historical_record=obs.historical_record,
            geometry=obs.geometry,
            has_geometries=[],
            part_of_point_of_interest=obs.part_of_point_of_interest,
        )
        for obs in observations
    ]
    validation_dataset = Dataset.constructor_from_json_obj(dataset_dict)
    RDECollection(hrs + validation_observations + [validation_dataset]).validate_data()
    print("Validation passed.")


if __name__ == "__main__":
    main()
