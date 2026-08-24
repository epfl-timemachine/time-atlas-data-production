"""Produce the Europeana postcard TimeAtlas dataset from Web Annotations.

The source corpus is a paginated W3C Web Annotation collection.  Each
Annotation represents one postcard record and contains structured claims for
places, dates, landmarks, web-matched locations, classifications, text, and
provenance.  This producer deliberately reads one AnnotationPage at a time so
the 1.5 GB corpus is never materialised as a single Python object.

Identity compatibility is a hard requirement.  Historical-record UUIDs use the
legacy CSV seed (``record_id + "\\n"``), and every generated UUID is checked
against the TimeAtlas HR URL already embedded in the source Annotation.

Before the regular generation pass, ``--rebuild-image-index`` can derive the
compact ``src/selected_postcard_images.csv`` intermediate from the Europeana
pipeline repository.  Once that intermediate exists, normal generation is
self-contained in this repository.
"""

from __future__ import annotations

import argparse
import calendar
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import quote_plus, unquote, urlparse
import uuid

import pandas as pd
from shapely import Point
from tqdm import tqdm


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[2]
SRC_DIR = BASE_DIR / "src"
ANNOTATION_SOURCE_DIR = (
    SRC_DIR / "enriched_europeana_postcards_geospatial_metadata_corpus_paginated"
)
IMAGE_INDEX_PATH = SRC_DIR / "selected_postcard_images.csv"
CITY_COORDINATES_PATH = SRC_DIR / "cached_city_country_loc.json"
CITY_ALIASES_PATH = SRC_DIR / "city_country_old_to_new.json"
CONFIG_PATH = BASE_DIR / "dataproduction_config.json"

TIMEATLAS_DIR = REPO_ROOT / "time-atlas-python"
for import_path in (REPO_ROOT, TIMEATLAS_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from europeana_uuid_generator import generate_hr_uuid
from timeatlas.DocumentModel import Annotation, Document, Page
from timeatlas.production import ProductionContext, get_area_uuids
from timeatlas.RDEModel import (
    Area,
    Dataset,
    DatasetConfiguration,
    FreeFormMetadata,
    HistoricalRecord,
    MetadataFieldConfig,
    MultiLingualValue,
    Observation,
    RDETimeRange,
)
from timeatlas.TAEnums import (
    MetadataTag,
    MetadataType,
    ParadataValues,
    RDEType,
)
from timeatlas.TimeAtlas import RDECollection, RDEEnvelopeWriter


IIIF_BASE_URL = "https://image-timemachine.epfl.ch/iiif/3"
IIIF_OBJECT_PREFIX = "europeana/postcards"
# Keep each uploadable manifest batch strictly below 100 MB.  The envelope
# writer measures UTF-8 bytes and writes one JSON object per JSONL line.
MAX_MANIFEST_JSONL_BYTES = 100_000_000 - 1
SUPPORTED_IMAGE_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
}

COUNTRY_LEVEL = "ta:CountryLevel"
CITY_LEVEL = "ta:CityLevel"
PLACE_LEVEL = "ta:PlaceLevel"
LANDMARK_LEVEL = "ta:LandmarkLevel"
GEOLOCATED_PLACE_LEVEL = "ta:GeolocatedPlaceLevel"

# A selected Lens result remains a useful spatial observation even when its
# evidence is too broad or uncertain to mint a shared Point of Interest.  PoI
# promotion is intentionally conservative and uses the qualifiers embedded by
# web_annotation_mapping.py instead of treating every coordinate alike.
LENS_POI_COORDINATE_PRECISIONS = {
    "point",
    "object",
    "object_or_place",
    "catalogued_point",
}
LENS_POI_CONTEXT_ASSESSMENTS = {
    "consistent_with_existing_city",
    "broadly_consistent_with_existing_city",
    "regional_difference",
    "source_text_supports_alternate_coordinates",
    "reference_or_unavailable",
}


@dataclass(frozen=True)
class ImageInfo:
    """Selected analysis image and IIIF dimensions for one postcard."""

    filename: str
    width: int
    height: int
    media_type: str
    selection_source: str


@dataclass(frozen=True)
class CoordinateEvidence:
    """One WGS84 point and the claim family that supplied it."""

    latitude: float
    longitude: float
    source: str
    label: str | None = None
    precise: bool = True

    @property
    def legacy_seed_coordinates(self) -> list[float]:
        """Return latitude-first coordinates used by the legacy Obs seed."""

        return [self.latitude, self.longitude]


@dataclass(frozen=True)
class LensGeolocation:
    """Selected web-match location and its decision/provenance qualifiers."""

    label: str | None
    resource_url: str | None
    evidence_url: str | None
    confidence_score: float | None
    source_confidence: float | None
    confidence_level: str | None
    geolocation_source: str | None
    source_domain: str | None
    extraction_method: str | None
    coordinate_precision: str | None
    location_role: str | None
    match_type: str | None
    selection_policy: str | None
    evidence: str | None
    context_consistency: str | None
    context_distance_km: float | None
    context_city_text_match: bool | None
    context_score_adjustment: float | None

    @property
    def poi_eligible(self) -> bool:
        """Whether this AI location is strong/specific enough to share a PoI."""

        return (
            self.coordinate_precision in LENS_POI_COORDINATE_PRECISIONS
            and self.confidence_score is not None
            and self.confidence_score >= 0.65
            and self.context_consistency in LENS_POI_CONTEXT_ASSESSMENTS
        )


@dataclass
class PostcardRecord:
    """The subset of one Web Annotation mapped into TimeAtlas RDEs."""

    record_id: str
    annotation_id: str
    hr_uuid: str
    description: str
    transcription: str | None
    country: str | None
    city: str | None
    place: str | None
    date_label: str | None
    temporal_precision: str | None
    time_range: RDETimeRange
    assessment: str
    postcard_reverse: bool | None
    city_view: bool | None
    scene_categories: list[str]
    landmarks: list[str]
    geolocated_places: list[str]
    lens_geolocation: LensGeolocation | None
    exact_visual_matches: list[str]
    image_source: str
    selected_image_iiif: str
    europeana_url: str | None
    rights_attribution: str | None
    coordinates: list[CoordinateEvidence] = field(default_factory=list)


@dataclass
class ProductionStats:
    """Counts collected by the full-corpus preflight audit."""

    records: int = 0
    observations: int = 0
    poi_grade_records: int = 0
    spatial_only_records: int = 0
    city_centroid_records: int = 0
    records_without_observations: int = 0
    records_without_dates: int = 0
    landmark_observations: int = 0
    lens_observations: int = 0
    poi_grade_observations: int = 0
    spatial_only_observations: int = 0
    earliest_year: int | None = None
    latest_year: int | None = None
    min_latitude: float | None = None
    max_latitude: float | None = None
    min_longitude: float | None = None
    max_longitude: float | None = None

    def observe_coordinate(self, coordinate: CoordinateEvidence) -> None:
        self.min_latitude = (
            coordinate.latitude
            if self.min_latitude is None
            else min(self.min_latitude, coordinate.latitude)
        )
        self.max_latitude = (
            coordinate.latitude
            if self.max_latitude is None
            else max(self.max_latitude, coordinate.latitude)
        )
        self.min_longitude = (
            coordinate.longitude
            if self.min_longitude is None
            else min(self.min_longitude, coordinate.longitude)
        )
        self.max_longitude = (
            coordinate.longitude
            if self.max_longitude is None
            else max(self.max_longitude, coordinate.longitude)
        )

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _types(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, str)]
    return []


def _purpose_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        purpose_id = value.get("id")
        return str(purpose_id) if purpose_id is not None else None
    return None


def _resource_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        resource_id = value.get("id")
        return str(resource_id) if resource_id is not None else None
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return str(value)


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text is not None:
            return text
    return None


def _unique_strings(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _boolean_label(value: bool | None) -> str | None:
    if value is None:
        return None
    return "Yes" if value else "No"


def _normalise_bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    normalised = str(value).strip().lower().rstrip(".")
    if normalised in {"yes", "true", "1"}:
        return True
    if normalised in {"no", "false", "0"}:
        return False
    return None


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _selected_image_iiif_url(image_info: ImageInfo) -> str:
    object_ref = f"{IIIF_OBJECT_PREFIX}/{image_info.filename}"
    return f"{IIIF_BASE_URL}/{quote_plus(object_ref)}/full/max/0/default.jpg"


def _record_id_from_annotation_id(annotation_id: str) -> str:
    parsed = urlparse(annotation_id)
    encoded_record_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    record_id = unquote(encoded_record_id)
    if not record_id:
        raise ValueError(f"Cannot extract record_id from Annotation ID {annotation_id!r}")
    return record_id


def _source_of(body: Mapping[str, Any]) -> Mapping[str, Any]:
    source = body.get("source")
    return source if isinstance(source, Mapping) else {}


def _body_list(annotation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bodies = annotation.get("body")
    if isinstance(bodies, Mapping):
        return [bodies]
    if isinstance(bodies, list):
        return [body for body in bodies if isinstance(body, Mapping)]
    return []


def _coordinate_from_place(value: Any) -> tuple[float, float] | None:
    """Return a validated ``(latitude, longitude)`` pair from an EDM place."""

    if not isinstance(value, Mapping):
        return None
    latitude = value.get("wgs84_pos:lat")
    longitude = value.get("wgs84_pos:long")
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return None
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        raise ValueError(f"Invalid WGS84 coordinate: {(latitude, longitude)}")
    return latitude, longitude


def _literal(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, Mapping):
        literal_value = _text(value.get("@value"))
        literal_type = _text(value.get("@type"))
        return literal_value, literal_type
    return _text(value), None


def _datetime_boundary(value: Any, *, at_end: bool) -> str | None:
    """Convert an EDM temporal literal into one ISO interval boundary."""

    text, literal_type = _literal(value)
    if text is None:
        return None

    year_match = re.fullmatch(r"(\d{4})", text)
    month_match = re.fullmatch(r"(\d{4})-(\d{2})", text)
    day_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)

    if year_match or literal_type == "xsd:gYear":
        year = int(year_match.group(1) if year_match else text)
        if not 1 <= year <= 9999:
            raise ValueError(f"Unsupported gYear value {text!r}")
        date = datetime(year, 12 if at_end else 1, 31 if at_end else 1)
    elif month_match or literal_type == "xsd:gYearMonth":
        if month_match is None:
            raise ValueError(f"Invalid gYearMonth value {text!r}")
        year, month = (int(part) for part in month_match.groups())
        day = calendar.monthrange(year, month)[1] if at_end else 1
        date = datetime(year, month, day)
    elif day_match or literal_type == "xsd:date":
        try:
            date = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"Invalid xsd:date value {text!r}") from exc
    else:
        try:
            date = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Unsupported temporal literal {text!r}") from exc

    if at_end:
        date = date.replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        date = date.replace(hour=0, minute=0, second=0, microsecond=0)
    return date.isoformat()


def _time_range_from_source(
    source: Mapping[str, Any],
    dataset_time_range: RDETimeRange,
) -> tuple[str | None, str | None, RDETimeRange]:
    label = _text(source.get("skos:prefLabel"))
    precision = _text(source.get("temporalPrecision"))
    if precision and precision.startswith("ta:"):
        precision = precision.removeprefix("ta:")

    start = _datetime_boundary(source.get("edm:begin"), at_end=False)
    end = _datetime_boundary(source.get("edm:end"), at_end=True)
    if start is None or end is None:
        return label, precision, dataset_time_range
    return label, precision, RDETimeRange(start, end)


def _rights_value(target_source: Mapping[str, Any]) -> str | None:
    for key in ("edm:rights", "dcterms:rights", "dc:rights"):
        value = target_source.get(key)
        if isinstance(value, Mapping):
            value = value.get("id") or value.get("value")
        text = _text(value)
        if text:
            return text
    return None


def _display_resource(label: str | None, resource_id: str | None) -> str | None:
    if label and resource_id and label not in resource_id:
        return f"{label} ({resource_id})"
    return label or resource_id


def _display_match(source: Mapping[str, Any]) -> str | None:
    candidate = _resource_id(source)
    page = _resource_id(source.get("dcterms:isPartOf"))
    if candidate and page and page != candidate:
        return f"{candidate} — {page}"
    return candidate or page


def _annotation_page_paths() -> list[Path]:
    if not ANNOTATION_SOURCE_DIR.is_dir():
        raise FileNotFoundError(f"Missing AnnotationPage directory: {ANNOTATION_SOURCE_DIR}")
    run_directories = sorted(
        path
        for path in ANNOTATION_SOURCE_DIR.iterdir()
        if path.is_dir() and any(path.glob("page-*.json"))
    )
    if len(run_directories) != 1:
        raise ValueError(
            f"Expected exactly one paginated corpus run under {ANNOTATION_SOURCE_DIR}, "
            f"found {len(run_directories)}: {run_directories}"
        )
    paths = sorted(run_directories[0].glob("page-*.json"))
    if not paths:
        raise FileNotFoundError(f"No page-*.json files under {run_directories[0]}")
    return paths


def iter_annotations(description: str) -> Iterator[Mapping[str, Any]]:
    """Yield source Annotations page by page with pagination checks."""

    running_index = 0
    collection_id: str | None = None
    for path in tqdm(_annotation_page_paths(), desc=description, unit="page"):
        with path.open(encoding="utf-8") as source_file:
            page = json.load(source_file)
        if page.get("type") != "AnnotationPage":
            raise ValueError(f"{path} is not an AnnotationPage")
        if page.get("startIndex") != running_index:
            raise ValueError(
                f"Unexpected startIndex in {path}: {page.get('startIndex')} != {running_index}"
            )
        current_collection = _resource_id(page.get("partOf"))
        if collection_id is None:
            collection_id = current_collection
        elif current_collection != collection_id:
            raise ValueError(
                f"AnnotationPage collection changed in {path}: "
                f"{current_collection!r} != {collection_id!r}"
            )
        items = page.get("items")
        if not isinstance(items, list):
            raise ValueError(f"AnnotationPage {path} has no items array")
        for annotation in items:
            if not isinstance(annotation, Mapping) or "Annotation" not in _types(
                annotation.get("type")
            ):
                raise ValueError(f"Invalid Annotation in {path}")
            yield annotation
        running_index += len(items)


def _ordered_corpus_record_ids() -> list[str]:
    return [
        _record_id_from_annotation_id(str(annotation["id"]))
        for annotation in iter_annotations("Reading corpus IDs")
    ]


def _selected_front(
    candidates: Sequence[Any],
    detector_by_filename: Mapping[str, bool | None],
) -> str | None:
    filenames = _unique_strings(
        Path(str(candidate)).name
        for candidate in candidates
        if candidate is not None and str(candidate).strip()
    )
    if not filenames:
        return None
    return next(
        (
            filename
            for filename in filenames
            if detector_by_filename.get(filename) is False
        ),
        filenames[0],
    )


def build_selected_image_index(europeana_root: Path, output_path: Path) -> None:
    """Derive the complete record-to-selected-image intermediate.

    The public Web Annotation representation intentionally omits operational
    filenames.  The selected filename is recovered from the exact intermediate
    inputs used by the source mapping notebook, then joined to the two image
    dimension caches.  The result is small enough to retain with this producer.
    """

    europeana_root = europeana_root.expanduser().resolve()
    base_sources = [
        (
            europeana_root
            / "22k_batch/27k_batch_results/results_filtered_for_monument_detection.csv",
            "base-27k",
        ),
        (
            europeana_root
            / "final_batch/results/results_filtered_for_monument_detection.csv",
            "base-final",
        ),
    ]
    filtered_images_path = (
        europeana_root / "final_batch/filtered_image_list_after_back_detector.json"
    )
    detector_path = (
        europeana_root
        / "cached_intermediate_results/back_of_postcard_detector_results.csv"
    )
    lens_geolocations_path = (
        europeana_root
        / "cached_intermediate_results/matching_geolocation/"
        "google_lens_link_geolocations_full.json"
    )
    dimension_paths = [
        europeana_root
        / "cached_intermediate_results/27k_image_width_height_format.csv",
        europeana_root
        / "cached_intermediate_results/all_imgs_wh_final_batch_europeana.csv",
    ]
    required_paths = [
        *(path for path, _ in base_sources),
        filtered_images_path,
        detector_path,
        lens_geolocations_path,
        *dimension_paths,
    ]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing Europeana image-index inputs: {missing}")

    with filtered_images_path.open(encoding="utf-8") as source_file:
        filtered_images = json.load(source_file)

    detector_df = pd.read_csv(
        detector_path,
        usecols=["filename", "is_back_of_postcard"],
    )
    detector_by_filename = {
        Path(str(row.filename)).name: _normalise_bool(row.is_back_of_postcard)
        for row in detector_df.itertuples(index=False)
    }

    base_frames: list[pd.DataFrame] = []
    for source_path, source_label in base_sources:
        frame = pd.read_csv(
            source_path,
            usecols=["record_id", "single_image_fp"],
            dtype={"record_id": str, "single_image_fp": str},
        )
        frame["selection_source"] = source_label
        base_frames.append(frame)

    final_frame = base_frames[1]
    for index in final_frame.index[final_frame["single_image_fp"].isna()]:
        record_id = str(final_frame.at[index, "record_id"])
        candidates = filtered_images.get(record_id, [])
        filename = _selected_front(candidates, detector_by_filename)
        if filename is None:
            raise ValueError(f"No selected image for base record {record_id}")
        final_frame.at[index, "single_image_fp"] = filename
        final_frame.at[index, "selection_source"] = "base-final-filtered-images"

    base_df = pd.concat(base_frames, ignore_index=True)
    if base_df["record_id"].duplicated().any():
        duplicates = base_df.loc[
            base_df["record_id"].duplicated(keep=False), "record_id"
        ].tolist()
        raise ValueError(f"Duplicate base record IDs: {duplicates[:20]}")
    if base_df["single_image_fp"].isna().any():
        raise ValueError("Base image mapping still contains null filenames")
    base_df["filename"] = base_df["single_image_fp"].map(
        lambda value: Path(str(value)).name
    )

    ordered_record_ids = _ordered_corpus_record_ids()
    base_record_ids = base_df["record_id"].astype(str).tolist()
    if ordered_record_ids[: len(base_record_ids)] != base_record_ids:
        raise ValueError(
            "The base source rows no longer match the Annotation corpus order; "
            "refusing to infer Lens-appended records by position."
        )

    with lens_geolocations_path.open(encoding="utf-8") as source_file:
        lens_payload = json.load(source_file)
    lens_by_record_id = {
        str(card["record_id"]): card
        for card in lens_payload.get("postcards", {}).values()
        if isinstance(card, Mapping) and card.get("record_id") is not None
    }

    selection_by_record_id: dict[str, tuple[str, str]] = {
        str(row.record_id): (str(row.filename), str(row.selection_source))
        for row in base_df[["record_id", "filename", "selection_source"]].itertuples(
            index=False
        )
    }
    for record_id in ordered_record_ids[len(base_record_ids) :]:
        filtered_candidates = filtered_images.get(record_id, [])
        filename = _selected_front(filtered_candidates, detector_by_filename)
        selection_source = "lens-filtered-images"
        if filename is None:
            card = lens_by_record_id.get(record_id)
            if card is None:
                raise ValueError(f"No Lens image metadata for appended record {record_id}")
            filename = _selected_front(card.get("image_ids", []), detector_by_filename)
            selection_source = "lens-geolocation-images"
        if filename is None:
            raise ValueError(f"No selected image for Lens-appended record {record_id}")
        selection_by_record_id[record_id] = (filename, selection_source)

    if set(selection_by_record_id) != set(ordered_record_ids):
        missing_record_ids = set(ordered_record_ids) - set(selection_by_record_id)
        extra_record_ids = set(selection_by_record_id) - set(ordered_record_ids)
        raise ValueError(
            f"Incomplete image selection; missing={len(missing_record_ids)}, "
            f"extra={len(extra_record_ids)}"
        )

    dimension_frames = [
        pd.read_csv(
            path,
            usecols=["filename", "width", "height", "media_type"],
            dtype={"filename": str, "media_type": str},
        )
        for path in dimension_paths
    ]
    dimensions = pd.concat(dimension_frames, ignore_index=True)
    dimensions["filename"] = dimensions["filename"].map(
        lambda value: Path(str(value)).name
    )
    dimensions["width"] = dimensions["width"].astype(int)
    dimensions["height"] = dimensions["height"].astype(int)
    conflicts = dimensions.groupby("filename").agg(
        width_count=("width", "nunique"),
        height_count=("height", "nunique"),
        media_type_count=("media_type", "nunique"),
    )
    conflicts = conflicts[
        (conflicts["width_count"] > 1)
        | (conflicts["height_count"] > 1)
        | (conflicts["media_type_count"] > 1)
    ]
    if not conflicts.empty:
        raise ValueError(
            f"Conflicting image dimensions/media types: {conflicts.head(20).index.tolist()}"
        )
    dimensions = dimensions.drop_duplicates("filename", keep="last").set_index(
        "filename"
    )

    output_rows: list[dict[str, Any]] = []
    for record_id in ordered_record_ids:
        filename, selection_source = selection_by_record_id[record_id]
        if filename not in dimensions.index:
            raise ValueError(f"No dimensions for selected image {filename} ({record_id})")
        dimension = dimensions.loc[filename]
        media_type = str(dimension["media_type"])
        if media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ValueError(f"Unsupported media type {media_type!r} for {filename}")
        output_rows.append(
            {
                "record_id": record_id,
                "filename": filename,
                "width": int(dimension["width"]),
                "height": int(dimension["height"]),
                "media_type": media_type,
                "selection_source": selection_source,
            }
        )

    output_df = pd.DataFrame(output_rows)
    if output_df["filename"].duplicated().any():
        duplicates = output_df.loc[
            output_df["filename"].duplicated(keep=False), "filename"
        ].tolist()
        raise ValueError(f"Selected filenames are not unique: {duplicates[:20]}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_csv(output_path, index=False)
    print(
        f"Wrote {len(output_df):,} selected images to {output_path}; "
        f"formats={output_df['media_type'].value_counts().to_dict()}"
    )


def load_image_index(path: Path) -> dict[str, ImageInfo]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run this producer with --rebuild-image-index "
            "--europeana-root /path/to/europeana first."
        )
    frame = pd.read_csv(
        path,
        dtype={"record_id": str, "filename": str, "media_type": str},
    )
    required_columns = {
        "record_id",
        "filename",
        "width",
        "height",
        "media_type",
        "selection_source",
    }
    if set(frame.columns) != required_columns:
        raise ValueError(
            f"Unexpected columns in {path}: {list(frame.columns)}; "
            f"expected {sorted(required_columns)}"
        )
    if frame["record_id"].duplicated().any():
        raise ValueError(f"Duplicate record_id values in {path}")
    image_index: dict[str, ImageInfo] = {}
    for row in frame.itertuples(index=False):
        width, height = int(row.width), int(row.height)
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid dimensions for {row.record_id}: {(width, height)}")
        if row.media_type not in SUPPORTED_IMAGE_MEDIA_TYPES:
            raise ValueError(
                f"Unsupported media type {row.media_type!r} for {row.record_id}"
            )
        image_index[str(row.record_id)] = ImageInfo(
            filename=str(row.filename),
            width=width,
            height=height,
            media_type=str(row.media_type),
            selection_source=str(row.selection_source),
        )
    return image_index


class PostcardParser:
    """Map record-level Web Annotations into typed production records."""

    def __init__(
        self,
        context: ProductionContext,
        image_index: Mapping[str, ImageInfo],
    ) -> None:
        self.context = context
        self.image_index = image_index
        with CITY_COORDINATES_PATH.open(encoding="utf-8") as source_file:
            self.city_coordinates = json.load(source_file)
        with CITY_ALIASES_PATH.open(encoding="utf-8") as source_file:
            self.city_aliases = json.load(source_file)

    def _city_centroid(
        self,
        country: str | None,
        city: str | None,
    ) -> CoordinateEvidence | None:
        if not country or not city:
            return None
        original_key = f"{country}, {city}"
        lookup_key = self.city_aliases.get(original_key, original_key)
        value = self.city_coordinates.get(lookup_key)
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return None
        try:
            latitude, longitude = float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            raise ValueError(
                f"Invalid cached city coordinate for {lookup_key}: {(latitude, longitude)}"
            )
        return CoordinateEvidence(
            latitude=latitude,
            longitude=longitude,
            source="city_centroid",
            label=original_key,
            precise=False,
        )

    def parse(self, annotation: Mapping[str, Any]) -> PostcardRecord:
        annotation_id = str(annotation.get("id", ""))
        record_id = _record_id_from_annotation_id(annotation_id)
        if record_id not in self.image_index:
            raise ValueError(f"No selected image mapping for record {record_id}")

        bodies = _body_list(annotation)
        description: str | None = None
        transcription: str | None = None
        assessment: str | None = None
        country: str | None = None
        city: str | None = None
        place: str | None = None
        time_source: Mapping[str, Any] | None = None
        postcard_reverse: bool | None = None
        city_view: bool | None = None
        scene_categories: list[str] = []
        landmarks: list[str] = []
        geolocated_places: list[str] = []
        lens_geolocation: LensGeolocation | None = None
        exact_visual_matches: list[str] = []
        precise_coordinates: list[CoordinateEvidence] = []
        europeana_urls: list[str] = []
        prebaked_hr_uuids: list[str] = []

        for body in bodies:
            purpose = _purpose_id(body.get("purpose"))
            body_types = _types(body.get("type"))
            source = _source_of(body)
            source_types = _types(source.get("type"))
            source_id = _resource_id(source)

            if "TextualBody" in body_types:
                value = _text(body.get("value"))
                if purpose == "describing" and value is not None:
                    description = description or value
                elif purpose == "transcribing" and value is not None:
                    transcription = transcription or value
                elif purpose == "assessing" and value is not None:
                    assessment = assessment or value

            if purpose == "linking" and source_id:
                parsed_source_id = urlparse(source_id)
                if (
                    parsed_source_id.hostname in {"europeana.eu", "www.europeana.eu"}
                    and parsed_source_id.path.startswith("/item/")
                    and isinstance(source.get("schema:about"), Mapping)
                ):
                    europeana_urls.append(source_id)
                if "/historical-record/" in parsed_source_id.path:
                    prebaked_hr_uuids.append(source_id.rstrip("/").rsplit("/", 1)[-1])
                if body.get("matchType") == "ta:ExactVisualMatch":
                    exact_visual_matches.append(_display_match(source) or source_id)

            identification_level = _text(source.get("identificationLevel"))
            source_label = _first_text(
                source.get("skos:prefLabel"),
                source.get("schema:name"),
                source.get("gn:name"),
            )
            if identification_level == COUNTRY_LEVEL:
                country = country or source_label
            elif identification_level == CITY_LEVEL:
                city = city or source_label
            elif identification_level == PLACE_LEVEL:
                place = place or source_label
            elif identification_level == LANDMARK_LEVEL:
                landmark_label = _display_resource(source_label, source_id)
                if landmark_label:
                    landmarks.append(landmark_label)
                spatial = source.get("dcterms:spatial")
                spatial_values = spatial if isinstance(spatial, list) else [spatial]
                for spatial_value in spatial_values:
                    coordinate = _coordinate_from_place(spatial_value)
                    if coordinate is not None:
                        precise_coordinates.append(
                            CoordinateEvidence(
                                latitude=coordinate[0],
                                longitude=coordinate[1],
                                source="landmark",
                                label=landmark_label,
                            )
                        )
            elif identification_level == GEOLOCATED_PLACE_LEVEL:
                if lens_geolocation is not None:
                    raise ValueError(
                        f"Multiple selected Lens geolocations for {record_id}"
                    )
                supporting_page = _resource_id(source.get("dcterms:source"))
                geolocated_label = _display_resource(
                    source_label,
                    source_id or supporting_page,
                )
                if geolocated_label:
                    geolocated_places.append(geolocated_label)
                lens_geolocation = LensGeolocation(
                    label=source_label,
                    resource_url=source_id,
                    evidence_url=supporting_page,
                    confidence_score=_finite_float(body.get("confidenceScore")),
                    source_confidence=_finite_float(body.get("sourceConfidence")),
                    confidence_level=_text(body.get("confidenceLevel")),
                    geolocation_source=_text(body.get("geolocationSource")),
                    source_domain=_text(body.get("sourceDomain")),
                    extraction_method=_text(body.get("extractionMethod")),
                    coordinate_precision=_text(body.get("coordinatePrecision")),
                    location_role=_resource_id(body.get("locationRole")),
                    match_type=_resource_id(body.get("matchType")),
                    selection_policy=_text(body.get("selectionPolicy")),
                    evidence=_text(body.get("evidence")),
                    context_consistency=_text(body.get("contextConsistency")),
                    context_distance_km=_finite_float(body.get("contextDistanceKm")),
                    context_city_text_match=_normalise_bool(
                        body.get("contextCityTextMatch")
                    ),
                    context_score_adjustment=_finite_float(
                        body.get("contextScoreAdjustment")
                    ),
                )
                coordinate = _coordinate_from_place(source)
                if coordinate is not None:
                    precise_coordinates.append(
                        CoordinateEvidence(
                            latitude=coordinate[0],
                            longitude=coordinate[1],
                            source="google_lens",
                            label=geolocated_label,
                            precise=lens_geolocation.poi_eligible,
                        )
                    )

            if "edm:TimeSpan" in source_types:
                if time_source is not None:
                    raise ValueError(f"Multiple dating claims for {record_id}")
                time_source = source

            classified_as = source.get("classifiedAs")
            classification_id = _resource_id(classified_as)
            if "ta:Classification" in source_types and classification_id:
                classification = _normalise_bool(source.get("value"))
                if classification_id.endswith("/classification/postcard-reverse"):
                    postcard_reverse = classification
                elif classification_id.endswith("/classification/city-view"):
                    city_view = classification
                elif "/scene-category/" in classification_id and classification is True:
                    category_label = _first_text(
                        classified_as.get("skos:prefLabel")
                        if isinstance(classified_as, Mapping)
                        else None,
                        classification_id.rsplit("/", 1)[-1].replace("-", " ").title(),
                    )
                    if category_label:
                        scene_categories.append(category_label)

        if description is None:
            raise ValueError(f"Missing visual description for {record_id}")
        if assessment is None:
            raise ValueError(f"Missing pipeline assessment for {record_id}")
        if len(prebaked_hr_uuids) != 1:
            raise ValueError(
                f"Expected one prebaked TimeAtlas HR link for {record_id}, "
                f"found {prebaked_hr_uuids}"
            )
        expected_hr_uuid = generate_hr_uuid(record_id)
        manager_hr_uuid = self.context.uuid_manager._generate_uuid(f"{record_id}\n")
        if expected_hr_uuid != manager_hr_uuid:
            raise ValueError(
                f"Standalone and library UUID generators disagree for {record_id}: "
                f"{expected_hr_uuid} != {manager_hr_uuid}"
            )
        if prebaked_hr_uuids[0] != expected_hr_uuid:
            raise ValueError(
                f"Prebaked HR UUID mismatch for {record_id}: "
                f"{prebaked_hr_uuids[0]} != {expected_hr_uuid}"
            )

        target = annotation.get("target")
        if not isinstance(target, Mapping):
            raise ValueError(f"Missing SpecificResource target for {record_id}")
        target_source = target.get("source")
        if not isinstance(target_source, Mapping):
            raise ValueError(f"Missing image target source for {record_id}")
        image_source = _resource_id(target_source)
        if image_source is None:
            raise ValueError(f"Missing target image URL for {record_id}")

        if time_source is None:
            date_label = None
            temporal_precision = None
            time_range = self.context.time_range
        else:
            date_label, temporal_precision, time_range = _time_range_from_source(
                time_source,
                self.context.time_range,
            )

        coordinates: list[CoordinateEvidence] = []
        coordinate_indexes: dict[tuple[float, float], int] = {}
        for coordinate in precise_coordinates:
            key = (coordinate.latitude, coordinate.longitude)
            existing_index = coordinate_indexes.get(key)
            if existing_index is not None:
                # The same point can be supported independently by a landmark
                # and by Lens.  Keep one observation UUID but never let a
                # weaker claim downgrade PoI eligibility supplied by stronger
                # evidence.
                if coordinate.precise and not coordinates[existing_index].precise:
                    coordinates[existing_index] = coordinate
                continue
            coordinate_indexes[key] = len(coordinates)
            coordinates.append(coordinate)
        if not coordinates:
            city_centroid = self._city_centroid(country, city)
            if city_centroid is not None:
                coordinates.append(city_centroid)

        europeana_url = _unique_strings(europeana_urls)
        if not europeana_url:
            scope_id = _resource_id(target.get("scope"))
            if scope_id and scope_id.startswith("http://data.europeana.eu/item/"):
                europeana_url = [
                    "https://www.europeana.eu/item/"
                    + scope_id.split("/item/", 1)[1]
                ]

        return PostcardRecord(
            record_id=record_id,
            annotation_id=annotation_id,
            hr_uuid=expected_hr_uuid,
            description=description,
            transcription=transcription,
            country=country,
            city=city,
            place=place,
            date_label=date_label,
            temporal_precision=temporal_precision,
            time_range=time_range,
            assessment=assessment,
            postcard_reverse=postcard_reverse,
            city_view=city_view,
            scene_categories=_unique_strings(scene_categories),
            landmarks=_unique_strings(landmarks),
            geolocated_places=_unique_strings(geolocated_places),
            lens_geolocation=lens_geolocation,
            exact_visual_matches=_unique_strings(exact_visual_matches),
            image_source=image_source,
            selected_image_iiif=_selected_image_iiif_url(
                self.image_index[record_id]
            ),
            europeana_url=europeana_url[0] if europeana_url else None,
            rights_attribution=_rights_value(target_source),
            coordinates=coordinates,
        )


def observation_uuid(record: PostcardRecord, coordinate: CoordinateEvidence, context: ProductionContext) -> str:
    """Preserve the legacy observation UUID seed for a HR/coordinate pair."""

    return context.uuid_manager._generate_uuid(
        f"{record.hr_uuid}-{coordinate.legacy_seed_coordinates}"
    )


def record_metadata(record: PostcardRecord) -> dict[str, Any]:
    lens = record.lens_geolocation
    return {
        "final_place": record.place,
        "final_country": record.country,
        "final_city": record.city,
        "description": record.description,
        "transcription": record.transcription,
        "date": record.date_label,
        "temporal_precision": record.temporal_precision,
        "reason": record.assessment,
        "postcard_reverse": _boolean_label(record.postcard_reverse),
        "city_view": _boolean_label(record.city_view),
        "scene_categories": record.scene_categories,
        "landmarks_identified": record.landmarks,
        "geolocated_places": record.geolocated_places,
        "lens_resource_url": lens.resource_url if lens else None,
        "lens_evidence_url": lens.evidence_url if lens else None,
        "lens_confidence_score": lens.confidence_score if lens else None,
        "lens_source_confidence": lens.source_confidence if lens else None,
        "lens_confidence_level": lens.confidence_level if lens else None,
        "lens_geolocation_source": lens.geolocation_source if lens else None,
        "lens_source_domain": lens.source_domain if lens else None,
        "lens_extraction_method": lens.extraction_method if lens else None,
        "lens_coordinate_precision": lens.coordinate_precision if lens else None,
        "lens_location_role": lens.location_role if lens else None,
        "lens_match_type": lens.match_type if lens else None,
        "lens_selection_policy": lens.selection_policy if lens else None,
        "lens_evidence": lens.evidence if lens else None,
        "lens_context_consistency": lens.context_consistency if lens else None,
        "lens_context_distance_km": lens.context_distance_km if lens else None,
        "lens_context_city_text_match": (
            _boolean_label(lens.context_city_text_match) if lens else None
        ),
        "lens_context_score_adjustment": (
            lens.context_score_adjustment if lens else None
        ),
        "lens_spatial_tier": (
            "poi_grade" if lens and lens.poi_eligible else "explicit_spatial"
            if lens
            else None
        ),
        "exact_visual_matches": record.exact_visual_matches,
        "img_src": record.selected_image_iiif,
        "source_image_claim": record.image_source,
        "europeana_url": record.europeana_url,
        "annotation_id": record.annotation_id,
        "record_id": record.record_id,
    }


def iter_parsed_records(parser: PostcardParser, description: str) -> Iterator[PostcardRecord]:
    for annotation in iter_annotations(description):
        yield parser.parse(annotation)


def iter_historical_records(
    parser: PostcardParser,
    context: ProductionContext,
) -> Iterator[HistoricalRecord]:
    for record in iter_parsed_records(parser, "Writing historical records"):
        yield HistoricalRecord(
            id=record.hr_uuid,
            dataset=context.dataset_id,
            time_range=record.time_range,
            paradata=ParadataValues.AI,
            has_observations=[
                observation_uuid(record, coordinate, context)
                for coordinate in record.coordinates
            ],
            metadata=record_metadata(record),
            rights_attribution=record.rights_attribution,
        )


def iter_observations(
    parser: PostcardParser,
    context: ProductionContext,
) -> Iterator[Observation]:
    for record in iter_parsed_records(parser, "Writing observations"):
        for coordinate in record.coordinates:
            yield Observation(
                id=observation_uuid(record, coordinate, context),
                historical_record=record.hr_uuid,
                geometry=Point(coordinate.longitude, coordinate.latitude),
                has_geometries=[],
                part_of_point_of_interest=coordinate.precise,
            )


def _year_from_iso(value: str) -> int:
    return int(value[:4])


def run_preflight(
    parser: PostcardParser,
    context: ProductionContext,
    config: Mapping[str, Any],
) -> ProductionStats:
    """Audit every source record and all deterministic identities before writes."""

    expected_metadata_fields = set(config["DATASET_CONFIGURATION"]["labels"])
    mapped_record_ids: set[str] = set()
    hr_ids: set[str] = set()
    observation_ids: set[str] = set()
    stats = ProductionStats()

    for record in iter_parsed_records(parser, "Preflight audit"):
        if record.record_id in mapped_record_ids:
            raise ValueError(f"Duplicate record_id in corpus: {record.record_id}")
        if record.hr_uuid in hr_ids:
            raise ValueError(f"Duplicate HR UUID in corpus: {record.hr_uuid}")
        mapped_record_ids.add(record.record_id)
        hr_ids.add(record.hr_uuid)

        metadata_fields = set(record_metadata(record))
        if metadata_fields != expected_metadata_fields:
            raise ValueError(
                f"Metadata/config mismatch: metadata-only={metadata_fields - expected_metadata_fields}, "
                f"config-only={expected_metadata_fields - metadata_fields}"
            )

        stats.records += 1
        stats.observations += len(record.coordinates)
        if record.date_label is None:
            stats.records_without_dates += 1
        else:
            start_year = _year_from_iso(record.time_range.start_time)
            end_year = _year_from_iso(record.time_range.end_time)
            stats.earliest_year = (
                start_year
                if stats.earliest_year is None
                else min(stats.earliest_year, start_year)
            )
            stats.latest_year = (
                end_year
                if stats.latest_year is None
                else max(stats.latest_year, end_year)
            )

        if not record.coordinates:
            stats.records_without_observations += 1
        elif any(coordinate.precise for coordinate in record.coordinates):
            stats.poi_grade_records += 1
        else:
            stats.spatial_only_records += 1

        if any(
            coordinate.source == "city_centroid"
            for coordinate in record.coordinates
        ):
            stats.city_centroid_records += 1

        for coordinate in record.coordinates:
            obs_uuid = observation_uuid(record, coordinate, context)
            if obs_uuid in observation_ids:
                raise ValueError(f"Duplicate observation UUID: {obs_uuid}")
            observation_ids.add(obs_uuid)
            stats.observe_coordinate(coordinate)
            if coordinate.precise:
                stats.poi_grade_observations += 1
            else:
                stats.spatial_only_observations += 1
            if coordinate.source == "landmark":
                stats.landmark_observations += 1
            elif coordinate.source == "google_lens":
                stats.lens_observations += 1

    image_record_ids = set(parser.image_index)
    if mapped_record_ids != image_record_ids:
        raise ValueError(
            f"Corpus/image-index mismatch: corpus-only={len(mapped_record_ids - image_record_ids)}, "
            f"image-only={len(image_record_ids - mapped_record_ids)}"
        )
    if context.dataset_id in hr_ids or context.dataset_id in observation_ids:
        raise ValueError("Dataset UUID collides with a generated entity UUID")

    print("Preflight passed:")
    print(json.dumps(stats.to_dict(), indent=2))
    return stats


def _field_paradata(field_id: str, configuration: Mapping[str, Any]) -> ParadataValues | None:
    if field_id in configuration.get("automatic_fields", []):
        return ParadataValues.AUTOMATIC
    if field_id in configuration.get("semi_automatic_fields", []):
        return ParadataValues.SEMIAUTOMATIC
    if field_id in configuration.get("manual_fields", []):
        return ParadataValues.MANUAL
    if field_id in configuration.get("ai_fields", []):
        return ParadataValues.AI
    return None


def _area_locations(config: Mapping[str, Any]) -> list[Path]:
    result: list[Path] = []
    for raw_location in config.get("AREA_LOCS", []):
        location = Path(raw_location)
        candidates = (
            [location]
            if location.is_absolute()
            else [
                BASE_DIR / location,
                REPO_ROOT / "rde" / "areas" / "data" / location,
            ]
        )
        resolved = next((candidate for candidate in candidates if candidate.exists()), None)
        if resolved is None:
            raise FileNotFoundError(
                f"Cannot resolve area location {raw_location!r}; tried {candidates}"
            )
        result.append(resolved)
    return result


def build_dataset(
    context: ProductionContext,
    collection_uuid: str,
    creation_time: str,
) -> Dataset:
    config = context.config
    dataset_config = config["DATASET_CONFIGURATION"]
    labels = dataset_config["labels"]
    field_types = dataset_config["types"]
    nullable_fields = set(dataset_config.get("nullable", []))
    indexed_fields = set(dataset_config.get("indexed", []))
    short_display_fields = set(dataset_config.get("short_display", []))
    hidden_fields = set(dataset_config.get("hidden", []))
    tagged_fields = dataset_config.get("tagged_fields", {})

    if set(labels) != set(field_types):
        raise ValueError(
            f"Dataset labels/types differ: labels-only={set(labels) - set(field_types)}, "
            f"types-only={set(field_types) - set(labels)}"
        )

    metadata_field_config = [
        MetadataFieldConfig(
            id=field_id,
            type=MetadataType(field_types[field_id]),
            display_label=MultiLingualValue(labels[field_id]),
            nullable=field_id in nullable_fields,
            indexable=field_id in indexed_fields,
            short_display=field_id in short_display_fields,
            hidden=field_id in hidden_fields,
            tag=(
                MetadataTag(tagged_fields[field_id])
                if field_id in tagged_fields
                else None
            ),
            paradata=_field_paradata(field_id, dataset_config),
        )
        for field_id in labels
    ]

    dataset_metadata = [
        FreeFormMetadata(
            type=MetadataType(metadata["type"]),
            label=MultiLingualValue(metadata["display_label"]),
            value=MultiLingualValue(metadata["value"]),
        )
        for metadata in dataset_config["dataset_metadata_config"].values()
    ]

    return Dataset(
        id=context.dataset_id,
        slug=context.dataset_slug,
        name=MultiLingualValue(dataset_config["name"]),
        time_range=context.time_range,
        creation_time=creation_time,
        version=str(config["VERSION"]),
        sources=[collection_uuid],
        has_areas=get_area_uuids(_area_locations(config)),
        configuration=DatasetConfiguration(
            metadata_field_config=metadata_field_config,
            main_label=dataset_config["main_label"],
            sub_label=dataset_config["sub_label"],
            display_thumbnail=bool(dataset_config.get("display_thumbnail", False)),
            external_source=bool(dataset_config.get("external_source", False)),
        ),
        metadata=dataset_metadata,
    )


def _manifest_uuid(record_id: str, context: ProductionContext) -> str:
    return context.uuid_manager._generate_uuid(f"{record_id}\npostcard_manifest")


def build_iiif(
    parser: PostcardParser,
    context: ProductionContext,
    iiif_dir: Path,
) -> tuple[str, int]:
    """Write size-limited JSONL IIIF manifest batches and a compact Collection."""

    manifests_dir = iiif_dir / "manifests"
    collections_dir = iiif_dir / "collections"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    collections_dir.mkdir(parents=True, exist_ok=True)

    manifest_items: list[dict[str, Any]] = []

    def iter_manifests() -> Iterator[dict[str, Any]]:
        for record in iter_parsed_records(parser, "Writing IIIF manifests"):
            image_info = parser.image_index[record.record_id]
            manifest_uuid = _manifest_uuid(record.record_id, context)
            canvas_uuid = context.uuid_manager._generate_uuid(
                f"{context.dataset_id}_{manifest_uuid}_0"
            )
            label = MultiLingualValue({"en": [record.description]})
            page = Page(
                id=canvas_uuid,
                label=label,
                # The TimeAtlas IIIF image service always renders the requested
                # ``/default.jpg`` representation, independently of the selected
                # source file's MIME type.  The painting body must describe that
                # JPEG representation rather than the stored source media type.
                format="image/jpeg",
                range_idx=0,
                height=image_info.height,
                width=image_info.width,
                object_ref=f"{IIIF_OBJECT_PREFIX}/{image_info.filename}",
                annotations=[
                    Annotation(
                        id=context.uuid_manager._generate_uuid(
                            f"annotation_{canvas_uuid}_{record.hr_uuid}"
                        ),
                        lang="en",
                        value=record.description,
                        hr_id=record.hr_uuid,
                        external_resource=record.europeana_url,
                    )
                ],
            )
            document = Document(
                id=manifest_uuid,
                label=label,
                items=[page],
            )
            manifest_items.append(document.to_iiif_manifest_item(IIIF_BASE_URL))
            yield document.to_iiif(context.uuid_manager, IIIF_BASE_URL)

    manifest_paths = RDEEnvelopeWriter(
        iiif_dir, overwrite=True
    ).write_jsonl_batches_by_size(
        "manifests/manifests", iter_manifests(), MAX_MANIFEST_JSONL_BYTES
    )
    if any(path.stat().st_size > MAX_MANIFEST_JSONL_BYTES for path in manifest_paths):
        raise ValueError("IIIF manifest JSONL batch exceeds the 100 MiB limit")

    collection_uuid = context.uuid_manager._generate_uuid(
        f"{context.dataset_slug}_collection"
    )
    collection = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": collection_uuid,
        "type": "Collection",
        "label": {
            "en": [
                f"{len(manifest_items):,} postcards from Europeana, "
                "enriched by TimeAtlas."
            ]
        },
        "items": manifest_items,
        "total": len(manifest_items),
        "metadata": [],
    }
    with (collections_dir / f"{collection_uuid}.json").open(
        "w", encoding="utf-8"
    ) as output_file:
        json.dump(collection, output_file, indent=2, ensure_ascii=False)
    return collection_uuid, len(manifest_items)


def _promote_staging(staging_dir: Path) -> None:
    """Transactionally replace only this dataset's generated artifacts."""

    generated_names = [
        "historical_records.json",
        "observations.json",
        "datasets.json",
        "points_of_interest.json",
        "iiif",
    ]
    backup_dir = BASE_DIR / f".generation-backup-{uuid.uuid4()}"
    backup_dir.mkdir()
    moved_old: list[str] = []
    moved_new: list[str] = []
    try:
        for name in generated_names:
            target = BASE_DIR / name
            if target.exists():
                target.replace(backup_dir / name)
                moved_old.append(name)
        for name in generated_names:
            staged = staging_dir / name
            if staged.exists():
                staged.replace(BASE_DIR / name)
                moved_new.append(name)
    except Exception:
        failed_dir = BASE_DIR / f".generation-failed-{uuid.uuid4()}"
        failed_dir.mkdir()
        for name in moved_new:
            target = BASE_DIR / name
            if target.exists():
                target.replace(failed_dir / name)
        for name in moved_old:
            backup = backup_dir / name
            if backup.exists():
                backup.replace(BASE_DIR / name)
        raise
    else:
        shutil.rmtree(backup_dir)


def generate_dataset(
    parser: PostcardParser,
    context: ProductionContext,
    stats: ProductionStats,
) -> None:
    creation_time = datetime.now().isoformat()
    collection_uuid = context.uuid_manager._generate_uuid(
        f"{context.dataset_slug}_collection"
    )

    with tempfile.TemporaryDirectory(
        prefix=".europeana-postcards-build-",
        dir=BASE_DIR,
    ) as temporary_directory:
        staging_dir = Path(temporary_directory)
        writer = RDEEnvelopeWriter(staging_dir, overwrite=True, indent=1)
        related_dataset_slugs = [context.dataset_slug]

        writer.write_stream(
            "historical_records",
            iter_historical_records(parser, context),
            "europeana_postcards_hrs",
            RDEType.HR.value,
            creation_time=creation_time,
            related_dataset_slugs=related_dataset_slugs,
        )
        writer.write_stream(
            "observations",
            iter_observations(parser, context),
            "europeana_postcards_observations",
            RDEType.OBS.value,
            creation_time=creation_time,
            related_dataset_slugs=related_dataset_slugs,
        )

        actual_collection_uuid, manifest_count = build_iiif(
            parser,
            context,
            staging_dir / "iiif",
        )
        if actual_collection_uuid != collection_uuid:
            raise ValueError(
                f"IIIF collection UUID changed unexpectedly: "
                f"{actual_collection_uuid} != {collection_uuid}"
            )
        if manifest_count != stats.records:
            raise ValueError(
                f"Manifest/record count mismatch: {manifest_count} != {stats.records}"
            )

        dataset = build_dataset(context, collection_uuid, creation_time)
        writer.write(
            "datasets",
            [dataset],
            "europeana_postcards_dataset",
            RDEType.DATASET.value,
            creation_time=creation_time,
            related_dataset_slugs=related_dataset_slugs,
        )

        _promote_staging(staging_dir)

    print(
        f"Generated {stats.records:,} historical records, "
        f"{stats.observations:,} raw observations, and {manifest_count:,} IIIF manifests."
    )
    print(
        "Run the post-production observation aggregation before schema/strict validation."
    )


def refresh_iiif_manifests(parser: PostcardParser, context: ProductionContext) -> None:
    """Transactionally rebuild only IIIF artifacts from current producer logic."""

    with tempfile.TemporaryDirectory(
        prefix=".europeana-postcards-iiif-build-",
        dir=BASE_DIR,
    ) as temporary_directory:
        staging_root = Path(temporary_directory)
        _, manifest_count = build_iiif(parser, context, staging_root / "iiif")
        old_iiif = BASE_DIR / "iiif"
        backup_iiif = BASE_DIR / f".iiif-backup-{uuid.uuid4()}"
        had_existing_iiif = old_iiif.exists()
        if had_existing_iiif:
            old_iiif.replace(backup_iiif)
        try:
            (staging_root / "iiif").replace(old_iiif)
        except Exception:
            if had_existing_iiif and not old_iiif.exists() and backup_iiif.exists():
                backup_iiif.replace(old_iiif)
            raise
        else:
            if backup_iiif.exists():
                shutil.rmtree(backup_iiif)
    print(f"Refreshed {manifest_count:,} IIIF manifests transactionally.")


def refresh_dataset_envelope(context: ProductionContext) -> None:
    """Rewrite only the dataset envelope after configuration metadata changes."""

    collection_uuid = context.uuid_manager._generate_uuid(
        f"{context.dataset_slug}_collection"
    )
    creation_time = datetime.now().isoformat()
    with tempfile.TemporaryDirectory(
        prefix=".europeana-postcards-dataset-build-",
        dir=BASE_DIR,
    ) as temporary_directory:
        staging_dir = Path(temporary_directory)
        RDEEnvelopeWriter(staging_dir, overwrite=True, indent=1).write(
            "datasets",
            [build_dataset(context, collection_uuid, creation_time)],
            "europeana_postcards_dataset",
            RDEType.DATASET.value,
            creation_time=creation_time,
            related_dataset_slugs=[context.dataset_slug],
        )
        (staging_dir / "datasets.json").replace(BASE_DIR / "datasets.json")
    print("Refreshed the dataset envelope from the current configuration.")


def validate_generated_rdes() -> None:
    """Run strict in-memory relationship and UUID validation after aggregation."""

    required = [
        BASE_DIR / "datasets.json",
        BASE_DIR / "historical_records.json",
        BASE_DIR / "observations.json",
        BASE_DIR / "points_of_interest.json",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Strict validation requires post-production aggregation; missing "
            f"{missing}"
        )
    collection = RDECollection.read_rde_from_files(str(BASE_DIR))
    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        config = json.load(config_file)
    for area_path in _area_locations(config):
        with area_path.open(encoding="utf-8") as area_file:
            envelope = json.load(area_file)
        collection.add(
            [
                Area.constructor_from_json_obj(area)
                for area in envelope.get("rde_objects", [])
            ]
        )
    counts = Counter(type(rde).__name__ for rde in collection.rdes)
    collection.validate_data()
    print(f"Strict TimeAtlas RDE validation passed: {dict(counts)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild-image-index",
        action="store_true",
        help=(
            "Rebuild src/selected_postcard_images.csv from the Europeana pipeline "
            "repository before generating data."
        ),
    )
    parser.add_argument(
        "--europeana-root",
        type=Path,
        help="Path to the Europeana pipeline repository used with --rebuild-image-index.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Audit the entire source and identities without writing generated data.",
    )
    parser.add_argument(
        "--validate-rdes-only",
        action="store_true",
        help="Strictly validate already-generated and post-processed RDE files.",
    )
    parser.add_argument(
        "--iiif-only",
        action="store_true",
        help="Transactionally rebuild only IIIF manifests and their collection.",
    )
    parser.add_argument(
        "--dataset-only",
        action="store_true",
        help="Rewrite only datasets.json from the current configuration.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.validate_rdes_only:
        if args.rebuild_image_index or args.preflight_only or args.iiif_only or args.dataset_only:
            raise ValueError("--validate-rdes-only cannot be combined with generation flags")
        validate_generated_rdes()
        return

    if args.rebuild_image_index:
        if args.europeana_root is None:
            raise ValueError("--rebuild-image-index requires --europeana-root")
        build_selected_image_index(args.europeana_root, IMAGE_INDEX_PATH)

    selected_partial_refreshes = sum((args.preflight_only, args.iiif_only, args.dataset_only))
    if selected_partial_refreshes > 1:
        raise ValueError("Only one of --preflight-only, --iiif-only, or --dataset-only may be used")

    context = ProductionContext.from_config(CONFIG_PATH)
    if args.dataset_only:
        refresh_dataset_envelope(context)
        return
    image_index = load_image_index(IMAGE_INDEX_PATH)
    parser = PostcardParser(context, image_index)
    if args.iiif_only:
        refresh_iiif_manifests(parser, context)
        return
    stats = run_preflight(parser, context, context.config)
    if not args.preflight_only:
        generate_dataset(parser, context, stats)


if __name__ == "__main__":
    main()
