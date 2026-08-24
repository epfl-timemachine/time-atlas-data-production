"""Import, publish, and verify the Venice 1582 Catastici dataset locally."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests


DATASET_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATASET_DIR.parents[2]
TIMEATLAS_DIR = REPO_ROOT / "time-atlas-python"
if str(TIMEATLAS_DIR) not in sys.path:
    sys.path.insert(0, str(TIMEATLAS_DIR))

from timeatlas.RDEModel import Area  # noqa: E402
from timeatlas.TimeAtlas import RDECollection  # noqa: E402
from timeatlas.importing import TimeAtlasImportClient  # noqa: E402


API_URL = "http://localhost:8000/v1"
MAP_DIR = REPO_ROOT / "rde" / "maps" / "venice-1740-parish"
AREA_FILES = (
    REPO_ROOT / "rde" / "areas" / "data" / "city-venice-area.json",
    REPO_ROOT / "rde" / "areas" / "data" / "country-italy-area.json",
)


def read_area(path: Path) -> Area:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Area.constructor_from_json_obj(payload["rde_objects"][0])


def load_collection() -> RDECollection:
    dataset_rdes = RDECollection.read_rde_from_files(str(DATASET_DIR)).rdes
    map_rdes = RDECollection.read_rde_from_files(str(MAP_DIR)).rdes
    collection = RDECollection(dataset_rdes + map_rdes + [read_area(p) for p in AREA_FILES])
    collection.validate_data()
    return collection


def first_id(collection: RDECollection, class_name: str) -> str:
    model_class = collection._class_for_name(class_name)
    return next(item.id for item in collection.rdes if type(item) is model_class)


def public_json(session: requests.Session, path: str) -> dict:
    response = session.get(f"{API_URL}/{path}", timeout=60)
    response.raise_for_status()
    return response.json()


def nested_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from nested_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_strings(child)


def verify_publication(collection: RDECollection) -> dict:
    dataset_id = first_id(collection, "Dataset")
    hr_id = first_id(collection, "HistoricalRecord")
    observation_id = first_id(collection, "Observation")
    poi_id = first_id(collection, "PointOfInterest")
    map_id = first_id(collection, "Map")

    manifest_path = next((DATASET_DIR / "iiif" / "manifests").glob("*.json"))
    collection_path = next((DATASET_DIR / "iiif" / "collections").glob("*.json"))
    manifest_id = manifest_path.stem
    iiif_collection_id = collection_path.stem

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    dataset = public_json(session, f"datasets/{dataset_id}")
    hr = public_json(session, f"historical-records/{hr_id}")
    observation = public_json(session, f"observations/{observation_id}")
    poi = public_json(session, f"points-of-interest/{poi_id}")
    map_data = public_json(session, f"maps/{map_id}")
    manifest = public_json(session, f"iiif/3/manifest/{manifest_id}")
    iiif_collection = public_json(session, f"iiif/3/collection/{iiif_collection_id}")

    expected_image = (
        "https://image-timemachine.epfl.ch/iiif/3/"
        "venice%2Fcatastici_1582%2F001.jpeg/full/max/0/default.jpg"
    )
    manifest_strings = set(nested_strings(manifest))
    if expected_image not in manifest_strings:
        raise RuntimeError("Published IIIF manifest does not contain the expected first image URL")
    if len(manifest.get("items", [])) != 402:
        raise RuntimeError("Published IIIF manifest does not contain 402 canvases")
    if not any(manifest_id in value for value in nested_strings(iiif_collection)):
        raise RuntimeError("Published IIIF collection does not reference its manifest")

    return {
        "dataset_id": dataset_id,
        "dataset_slug": dataset.get("slug"),
        "historical_record_id": hr_id,
        "observation_id": observation_id,
        "point_of_interest_id": poi_id,
        "map_id": map_id,
        "manifest_id": manifest_id,
        "collection_id": iiif_collection_id,
        "manifest_canvases": len(manifest.get("items", [])),
        "first_image_url": expected_image,
        "public_resources_verified": all((dataset, hr, observation, poi, map_data)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    collection = load_collection()
    counts = {}
    for item in collection.rdes:
        counts[type(item).__name__] = counts.get(type(item).__name__, 0) + 1
    print("COLLECTION_COUNTS=" + json.dumps(counts, sort_keys=True), flush=True)

    client = TimeAtlasImportClient.from_credentials_file(
        API_URL,
        REPO_ROOT / "token_and_team_id.txt",
        timeout=120,
    )

    def report_event(event: dict) -> None:
        safe = {
            key: event.get(key)
            for key in ("id", "type", "level", "message", "created_at")
            if event.get(key) is not None
        }
        print("IMPORT_EVENT=" + json.dumps(safe, ensure_ascii=False), flush=True)

    dataset_folder = "datasets/venice-1582-catastici"
    result = client.run_collection_workflow(
        collection,
        args.output_dir,
        upload_folder=dataset_folder,
        upload_folders={
            "areas": "areas",
            "maps": "maps/venice-1740-parish",
            "layers": "maps/venice-1740-parish",
            "geometries": "maps/venice-1740-parish",
        },
        additional_files=(
            (
                next((DATASET_DIR / "iiif" / "manifests").glob("*.json")),
                f"{dataset_folder}/iiif/manifests",
            ),
            (
                next((DATASET_DIR / "iiif" / "collections").glob("*.json")),
                f"{dataset_folder}/iiif/collections",
            ),
        ),
        visibility="public",
        workflow_timeout=3600,
        poll_interval=2,
        on_event=report_event,
    )

    verification = verify_publication(collection)
    summary = {
        "import_id": result.import_data.get("uuid"),
        "import_status": result.import_data.get("status"),
        "validation_status": result.validation_report.get("status"),
        "validation_failures": len(result.validation_report.get("failures") or []),
        "uploaded_files": len(result.uploaded_files),
        "publication_requests": len(result.publications),
        **verification,
    }
    print("IMPORT_SUMMARY=" + json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
