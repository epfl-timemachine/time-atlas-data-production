"""
Produce RDE and IIIF data for dublin-transkribathon-maps.

Each CSV row is modeled as one HistoricalRecord and one single-canvas IIIF
manifest. Images are downloaded locally to ./img and their dimensions are read
from the downloaded files before manifests are generated.
"""

import ast
import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests
from PIL import Image
from shapely.geometry import Point
from tqdm import tqdm

# Library path bootstrap. This script is expected to be run from its dataset dir.
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
from timeatlas.helpers import _clean_metadata, _datetime_from_int


IIIF_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"
IIIF_OBJECT_REF_PREFIX = "lausanne/3Dbuilding/dublin"
CSV_PATH = Path("src/dublin_map_items.csv")
IMG_DIR = Path("img")
IMG_METADATA_PATH = Path("src/img_width_height_format.csv")
PLACES_CACHE_PATH = Path("src/dublin_map_item_places.csv")
PLACES_URL = (
    "https://europeana.fresenia-dev.man.poznan.pl/dev/wp-content/themes/"
    "transcribathon/requests/api.php/projects/11/places/"
    "?limit=3000&orderBy=PlaceId&orderDir=desc&page={page}"
)
DUBLIN_BBOX = ((-7.012024, 53.138533), (-5.841980, 53.608803))


with open("dataproduction_config.json", encoding="utf-8") as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG["UUID_NAMESPACE"])
DS_SLUG = DATA_CONFIG["DATASET_CONFIGURATION"]["slug"]
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)
DATASET_TR = RDETimeRange(
    _datetime_from_int(DATA_CONFIG["TIMERANGE_MINIMUM"]),
    _datetime_from_int(DATA_CONFIG["TIMERANGE_MAXIMUM"], match_to_end=True),
)


def _parse_literal(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value


def _as_clean_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    value = str(value).strip()
    return value or None


def _slugify_filename(value: str) -> str:
    value = value.replace(":", "_").replace("/", "_")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._")
    return value or "image"


def _image_info_from_row(row: pd.Series) -> dict[str, Any]:
    image_link = _parse_literal(row.get("ImageLink")) or {}
    if not isinstance(image_link, dict):
        image_link = {}

    image_url = (
        image_link.get("@id")
        or image_link.get("id")
        or image_link.get("url")
        or _as_clean_str(row.get("ImageLink"))
    )
    if not image_url:
        raise ValueError(f"Missing image URL for ItemId {row['ItemId']}")

    format_ = image_link.get("format") or mimetypes.guess_type(image_url)[0] or "image/jpeg"
    loris_id = None
    service = image_link.get("service")
    if isinstance(service, dict):
        loris_id = service.get("@id") or service.get("id")

    parsed_path = urlparse(loris_id or image_url).path.rstrip("/")
    base = parsed_path.split("/")[-1]
    if not base or base == "default.jpg":
        base = str(row["ItemId"])

    ext = mimetypes.guess_extension(format_) or Path(urlparse(image_url).path).suffix or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"

    filename = f"{int(row['ItemId'])}_{_slugify_filename(base)}{ext}"
    return {
        "image_url": image_url,
        "media_type": format_,
        "filename": filename,
    }


def _download_image(url: str, output_path: Path, timeout: int = 60) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        try:
            with Image.open(output_path) as img:
                img.verify()
            return
        except Exception:
            output_path.unlink()

    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    f.write(chunk)


def _read_local_image_metadata(path: Path, fallback_media_type: str) -> dict[str, Any]:
    with Image.open(path) as img:
        format_map = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "GIF": "image/gif",
            "TIFF": "image/tiff",
            "BMP": "image/bmp",
            "WEBP": "image/webp",
        }
        return {
            "width": int(img.width),
            "height": int(img.height),
            "media_type": format_map.get(img.format, fallback_media_type),
        }


def _date_to_time_range(start_value: Any, end_value: Any) -> RDETimeRange:
    start = pd.to_datetime(start_value, errors="coerce")
    end = pd.to_datetime(end_value, errors="coerce")

    if pd.isna(start) and pd.isna(end):
        return DATASET_TR
    if pd.isna(start):
        start = end
    if pd.isna(end):
        end = start

    if start > end:
        start, end = end, start

    start_dt = start.to_pydatetime().replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = end.to_pydatetime().replace(hour=23, minute=59, second=59, microsecond=0)
    return RDETimeRange(start_dt.isoformat(), end_dt.isoformat())


def _list_property_values(properties: Any, property_type: str) -> list[str]:
    parsed = _parse_literal(properties)
    if not isinstance(parsed, list):
        return []
    values = []
    for prop in parsed:
        if not isinstance(prop, dict):
            continue
        if prop.get("PropertyTypeName") == property_type and prop.get("Value"):
            values.append(str(prop["Value"]))
    return values


def _transcription_text(transcription: Any) -> str | None:
    parsed = _parse_literal(transcription)
    if isinstance(parsed, dict):
        return _as_clean_str(parsed.get("TranscriptionText")) or _as_clean_str(parsed.get("Text"))
    return _as_clean_str(transcription)


def _prepare_dataframe() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH).replace({np.nan: None})
    image_info = df.apply(_image_info_from_row, axis=1, result_type="expand")
    df = pd.concat([df, image_info], axis=1)

    df["item_id"] = df["ItemId"].astype(str)
    df["title"] = df["Title"].apply(_as_clean_str)
    df["description"] = df["Description"].apply(_as_clean_str)
    df["transcription_text"] = df["Transcription"].apply(_transcription_text)
    df["categories"] = df["Properties"].apply(lambda v: _list_property_values(v, "Category"))
    df["keywords"] = df["Properties"].apply(lambda v: _list_property_values(v, "Keyword"))
    df["manifest"] = df["Manifest"].apply(_as_clean_str)
    df["date_start_display"] = df["DateStartDisplay"].apply(_as_clean_str)
    df["date_end_display"] = df["DateEndDisplay"].apply(_as_clean_str)
    df["story_id"] = df["StoryId"].astype(str)
    df["order_index"] = df["OrderIndex"]

    return df


def _download_images_and_measure(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Images"):
        local_path = IMG_DIR / row["filename"]
        _download_image(row["image_url"], local_path)
        metadata = _read_local_image_metadata(local_path, row["media_type"])
        records.append(
            {
                "item_id": row["item_id"],
                "filename": row["filename"],
                "path": str(local_path),
                "image_url": row["image_url"],
                **metadata,
            }
        )

    img_df = pd.DataFrame(records)
    img_df.to_csv(IMG_METADATA_PATH, index=False)
    return img_df


def _unpack_transkribathon_response(response: requests.Response) -> list[dict[str, Any]]:
    payload = response.json()
    if payload.get("success"):
        return payload["data"]
    raise RuntimeError(f"Unsuccessful Transkribathon API call: {payload}")


def _fetch_transkribathon_places() -> pd.DataFrame:
    records = []
    for page in range(1, 100):
        response = requests.get(PLACES_URL.format(page=page), timeout=60)
        response.raise_for_status()
        data = _unpack_transkribathon_response(response)
        if not data:
            break
        records.extend(data)
    return pd.DataFrame(records)


def _load_places_for_items(item_ids: pd.Series) -> pd.DataFrame:
    item_ids = set(item_ids.astype(int))

    if PLACES_CACHE_PATH.exists():
        places = pd.read_csv(PLACES_CACHE_PATH)
    else:
        places = _fetch_transkribathon_places()
        places["Latitude"] = pd.to_numeric(places["Latitude"], errors="coerce")
        places["Longitude"] = pd.to_numeric(places["Longitude"], errors="coerce")

        (min_lon, min_lat), (max_lon, max_lat) = DUBLIN_BBOX
        places = places[
            places["Longitude"].between(min_lon, max_lon)
            & places["Latitude"].between(min_lat, max_lat)
        ].copy()
        places = places[places["ItemId"].isin(item_ids)].copy()

        keep_cols = [
            "ItemId",
            "PlaceId",
            "Name",
            "Latitude",
            "Longitude",
            "Zoom",
            "Comment",
            "UserGenerated",
            "UserId",
            "WikidataName",
            "WikidataId",
            "PlaceRole",
            "ItemTitle",
        ]
        places = places[[col for col in keep_cols if col in places.columns]]
        places.sort_values(["ItemId", "PlaceId"], inplace=True)
        places.to_csv(PLACES_CACHE_PATH, index=False)

    places["ItemId"] = places["ItemId"].astype(int)
    places["PlaceId"] = places["PlaceId"].astype(int)
    places["Latitude"] = pd.to_numeric(places["Latitude"], errors="coerce")
    places["Longitude"] = pd.to_numeric(places["Longitude"], errors="coerce")
    places = places[places["ItemId"].isin(item_ids)]
    return places.dropna(subset=["Latitude", "Longitude"])


def _annotation_text(row: pd.Series) -> str:
    parts = [
        _as_clean_str(row.get("title")),
        _as_clean_str(row.get("date_start_display")) or _as_clean_str(row.get("date_end_display")),
    ]
    return " | ".join(part for part in parts if part)


def main() -> None:
    df = _prepare_dataframe()
    img_df = _download_images_and_measure(df)
    df = df.merge(img_df, on=["item_id", "filename", "image_url", "media_type"], how="left")
    places_df = _load_places_for_items(df["ItemId"])

    hr_metadata_cols = [
        "item_id",
        "title",
        "description",
        "transcription_text",
        "categories",
        "keywords",
        "manifest",
        "image_url",
        "date_start_display",
        "date_end_display",
        "story_id",
        "order_index",
    ]

    documents: dict[str, Document] = {}
    hrs: list[HistoricalRecord] = []
    obs_list: list[Observation] = []
    places_by_item = {
        item_id: sdf.sort_values("PlaceId")
        for item_id, sdf in places_df.groupby("ItemId", sort=False)
    }

    for _, row in tqdm(df.iterrows(), total=len(df), desc="HRs and manifests"):
        item_id = row["item_id"]
        numeric_item_id = int(row["ItemId"])
        hr_uuid = uuid_mgr._generate_uuid(f"historical_record_{DS_SLUG}_{item_id}")
        manifest_uid = uuid_mgr._generate_uuid(f"manifest_{DS_SLUG}_{item_id}")
        canvas_uid = uuid_mgr._generate_uuid(f"{DS_UUID}_{manifest_uid}_0")
        annotation_value = _annotation_text(row)
        title = row["title"] or f"Dublin Transkribathon map {item_id}"
        object_ref = f"{IIIF_OBJECT_REF_PREFIX}/{row['filename']}"

        documents[manifest_uid] = Document(
            id=manifest_uid,
            label=MultiLingualValue({"en": [title]}),
            items=[
                Page(
                    id=canvas_uid,
                    label=MultiLingualValue({"en": [title]}),
                    format=row["media_type"],
                    range_idx=0,
                    height=int(row["height"]),
                    width=int(row["width"]),
                    object_ref=object_ref,
                    annotations=[
                        Annotation(
                            id=uuid_mgr._generate_uuid(f"annotation_{canvas_uid}_{hr_uuid}"),
                            lang="en",
                            value=annotation_value,
                            hr_id=hr_uuid,
                        )
                    ],
                )
            ],
        )

        obs_uuids = []
        for _, place in places_by_item.get(numeric_item_id, pd.DataFrame()).iterrows():
            place_id = int(place["PlaceId"])
            obs_uuid = uuid_mgr._generate_uuid(f"observation_{DS_SLUG}_{item_id}_{place_id}")
            obs_uuids.append(obs_uuid)
            obs_list.append(
                Observation(
                    id=obs_uuid,
                    historical_record=hr_uuid,
                    geometry=Point(float(place["Longitude"]), float(place["Latitude"])),
                    has_geometries=[],
                    part_of_point_of_interest=None,
                )
            )

        metadata = _clean_metadata({col: row[col] for col in hr_metadata_cols})
        hrs.append(
            HistoricalRecord(
                id=hr_uuid,
                dataset=DS_UUID,
                time_range=_date_to_time_range(row["DateStart"], row["DateEnd"]),
                paradata="m",
                has_observations=obs_uuids,
                metadata=metadata,
                rights_attribution="Dublin City Library and Archive; Digital Repository of Ireland",
            )
        )

    os.makedirs("iiif/manifests", exist_ok=True)
    os.makedirs("iiif/collections", exist_ok=True)

    for manifest_uid, doc in documents.items():
        with open(f"iiif/manifests/{manifest_uid}.json", "w", encoding="utf-8") as f:
            json.dump(doc.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

    collection_uid = uuid_mgr._generate_uuid(f"collection_{DS_SLUG}")
    collection = Collection(
        id=collection_uid,
        label=MultiLingualValue({"en": ["Dublin Transkribathon Maps"]}),
        items=list(documents.values()),
    )
    with open(f"iiif/collections/{collection_uid}.json", "w", encoding="utf-8") as f:
        json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

    dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
        "dataproduction_config.json",
        df[hr_metadata_cols],
        sources=[collection_uid],
        ds_id=DS_UUID,
    )

    full_collection = RDECollection(hrs + obs_list + [dataset])
    full_collection.validate_data()
    print("Validation passed.")

    full_collection.save_rde_to_files(".", overwrite=True, rde_types=[HistoricalRecord, Observation, Dataset])
    print(f"Saved {len(hrs)} HRs, {len(obs_list)} observations, 1 dataset, {len(documents)} manifests.")


if __name__ == "__main__":
    main()
