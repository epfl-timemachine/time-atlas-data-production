"""
produce_lausanne_qbuildings_data_v2.py

Rewrite of produce_lausanne_qbuildings_data.py using the timeatlas library
classes directly, without procedural helpers from utils/data_modeling.

UUID seeds for Geometry / HR / Observation replicate the CSV-serialisation
strategy of the legacy script so all RDE object UUIDs are byte-for-byte
identical between the two versions.

IIIF manifest / collection UUIDs derived from the same namespace + seeds are
also identical. Internal canvas annotation-page IDs (generated inside
Page.to_iiif()) differ from the legacy iiif.py utilities but the IIIF
structure and ordering are consistent.
"""

import io, json, os, sys, time
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
from tqdm import tqdm

# ── Library bootstrap ─────────────────────────────────────────────────────────
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
timeatlas_dir = os.path.join(parent_dir, 'time-atlas-python')
if timeatlas_dir not in sys.path:
    sys.path.insert(0, timeatlas_dir)

from timeatlas.RDEModel import (
    UUIDManager, RDETimeRange, HistoricalRecord, Observation, Geometry,
    Dataset, MultiLingualValue,
)
from timeatlas.production import (
    datetime_from_int,
    find_layer_uuid,
    normalize_to_epsg4326,
    csv_seed,
)
from timeatlas.TimeAtlas import RDECollection
from timeatlas.DocumentModel import Page, Annotation, Document, Model, Collection

IIIF_BASE_URL = 'https://image-timemachine.epfl.ch/iiif/3'

# ── Configuration ──────────────────────────────────────────────────────────────
t0 = time.perf_counter()

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG  = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID  = uuid_mgr._generate_uuid(DS_SLUG)


# ── 1. Load source data ────────────────────────────────────────────────────────
MAP_FOLDER = '../../maps/lausanne-qbuildings/'
cadaster_layer_uuid = find_layer_uuid(MAP_FOLDER + 'layers.json', 'buildings')

gdf = normalize_to_epsg4326(
    gpd.read_file(Path('src') / 'qbuildings-lausanne.geojson')
)

TR_START   = datetime_from_int(DATA_CONFIG['TIMERANGE_MINIMUM'])
TR_END     = datetime_from_int(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True)
time_range = RDETimeRange(TR_START, TR_END)

gdf['start_time'] = TR_START
gdf['end_time']   = TR_END
gdf['center']     = gdf['geometry'].apply(lambda g: g.centroid)

# ── 2. Geometries ──────────────────────────────────────────────────────────────
# Generate UUIDs from original (possibly invalid) geometries, then repair
# inside Geometry if needed.
geometries = Geometry.geometries_from_gdf(
    gdf,
    ['geometry'],
    cadaster_layer_uuid,
    uuid_manager=uuid_mgr,
    force_valid=True,
)

# ── 3. Historical Records & Observations ──────────────────────────────────────
EXCLUDE = {
    'geometry_id', 'has_geometry', 'obs_uuid', 'hr_uuid',
    'geometry', 'center', 'end_time', 'start_time',
    'index', 'rde_type', 'layer_uuid', 'uuid', 'status',
}

# Replicate: df = gdf.drop(columns=['geometry']).copy().reset_index()
df = gdf.drop(columns=['geometry']).copy().reset_index()
df['has_geometry'] = [geometry.id for geometry in geometries]
hr_metadata_cols = [c for c in df.columns if c not in EXCLUDE]

df['hr_uuid'] = [uuid_mgr._generate_uuid(csv_seed(row, ['index'], 'hr')) for _, row in df.iterrows()]
df['obs_uuid'] = [uuid_mgr._generate_uuid(csv_seed(row, ['center'], 'obs')) for _, row in df.iterrows()]
hrs = HistoricalRecord.historical_records_from_df(
    df,
    id_col='hr_uuid',
    obs_col='obs_uuid',
    dataset_id=DS_UUID,
    time_range=time_range,
    metadata_cols=hr_metadata_cols,
)
obs_list = Observation.observations_from_df(
    df,
    id_col='obs_uuid',
    hr_col='hr_uuid',
    geometry_col='center',
    has_geometries_col='has_geometry',
)

# ── 4. IIIF – 2D thumbnail manifests (one per building) ───────────────────────
os.makedirs('iiif/manifests',   exist_ok=True)
os.makedirs('iiif/collections', exist_ok=True)

for hr in tqdm(hrs, desc='2D IIIF manifests'):
    md          = hr.metadata
    man_label   = f"{md['id_building']} - {md['class']}, {md['system_hotwater']}, {md['system_heating']}"
    man_uuid    = uuid_mgr._generate_uuid(man_label)
    building_id = md['id_building']
    canvas_uuid = uuid_mgr._generate_uuid(f'{DS_UUID}_{man_uuid}_0')

    page = Page(
        id=canvas_uuid,
        label=MultiLingualValue({'en': ['Thumbnail of the cloudpoint model']}),
        format='image/png',
        range_idx=0,
        height=512,
        width=1024,
        object_ref=f'lausanne/3Dbuilding/thumbnails/qbuilding_{int(building_id)}.png',
        annotations=[Annotation(
            id=uuid_mgr._generate_uuid(f'annotation_{canvas_uuid}_{hr.id}'),
            lang='en',
            value=man_label,
            hr_id=hr.id,
        )],
    )
    doc = Document(
        id=man_uuid,
        label=MultiLingualValue({'en': [man_label]}),
        items=[page],
    )
    with open(f'iiif/manifests/{man_uuid}.json', 'w', encoding='utf-8') as f:
        json.dump(doc.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

# ── 5. IIIF – 3D LAS manifests (one per building) ─────────────────────────────
man_3d_docs: dict[str, Document] = {}
for hr in tqdm(hrs, desc='3D IIIF manifests'):
    md         = hr.metadata
    label      = f"{md['id_building']} - {md['class']}, {md['system_hotwater']}, {md['system_heating']}"
    fname      = f"qbuilding_{md['id_building']}.las"
    man_id     = uuid_mgr._generate_uuid(fname)
    scene_id   = uuid_mgr._generate_uuid(man_id + '/scene/1')

    doc = Document(
        id=man_id,
        label=MultiLingualValue({'en': [label]}),
        items=[Model(
            id=scene_id,
            label=MultiLingualValue({'en': [label]}),
            format='application/vnd.las',
            object_ref=f"http://timeatlas.eu/assets/las/{fname}",
            annotations = [Annotation(
                id=uuid_mgr._generate_uuid(f'{scene_id}_{hr.id}'),
                lang='en',
                value=label,
                hr_id=hr.id,
            )]
        )],
    )
    manifest = doc.to_iiif(uuid_mgr, IIIF_BASE_URL, presentation_version='4')
    man_3d_docs[man_id] = doc
    with open(f'iiif/manifests/{man_id}.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

# ── 6. IIIF – 3D collection ────────────────────────────────────────────────────
collection_uid = uuid_mgr._generate_uuid(f'collection_3d_{DS_SLUG}')
collection = Collection(
    id=collection_uid,
    label=MultiLingualValue({'en': ['Cloudpoints models in LAS format from all lausanne buildings from contemporary LIDAR data acquisition']}),
    items=list(man_3d_docs.values()),
)
with open(f'iiif/collections/{collection_uid}.json', 'w', encoding='utf-8') as f:
    json.dump(collection.to_iiif(IIIF_BASE_URL, with_thumbnails=False), f, indent=2, ensure_ascii=False)

# ── 7. Dataset ─────────────────────────────────────────────────────────────────
labels_order = list(DATA_CONFIG['DATASET_CONFIGURATION']['labels'].keys())
hr_df        = pd.DataFrame([hr.metadata for hr in hrs])
dataset      = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    'dataproduction_config.json',
    hr_df[[c for c in labels_order if c in hr_df.columns]],
    sources=[collection_uid],
    ds_id=DS_UUID,
)

# ── 8. Validate and save ───────────────────────────────────────────────────────
full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
full_collection.validate_data()
print('Validation passed.')

full_collection.save_rde_to_files(MAP_FOLDER, overwrite=True, rde_types=[Geometry])
print(f'Saved {len(geometries)} geometries → {MAP_FOLDER}')

full_collection.save_rde_to_files('.', overwrite=True, rde_types=[HistoricalRecord, Observation, Dataset])
print(f'Saved {len(hrs)} HRs, {len(obs_list)} Obs, 1 Dataset → .')
