"""
produce_sommarioni_data_v2.py

Rewrite of produce_sommarioni_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling or utils/iiif.

UUID seeds for Geometry / HR / Observation replicate the CSV-serialisation
strategy of the legacy script so all RDE object UUIDs are byte-for-byte
identical between the two versions.  IIIF document UUIDs (canvas, annotation,
manifest) may differ; their structure and ordering are consistent.
"""

import io, json, os, sys
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path

# ── Library path bootstrap ─────────────────────────────────────────────────────
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
timeatlas_dir = os.path.join(parent_dir, 'time-atlas-python')
if timeatlas_dir not in sys.path:
    sys.path.insert(0, timeatlas_dir)

from timeatlas.RDEModel import (
    UUIDManager, RDETimeRange,
    HistoricalRecord, Observation, Geometry, Dataset, MultiLingualValue,
)
from timeatlas.production import datetime_from_int, find_layer_uuid, find_latest_file, csv_seed
from timeatlas.TimeAtlas import RDECollection
from timeatlas.DocumentModel import Page, Annotation, Document, Collection

IIIF_BASE_URL = 'https://image-timemachine.epfl.ch/iiif/3'

# ── Configuration ──────────────────────────────────────────────────────────────
with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG  = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID  = uuid_mgr._generate_uuid(DS_SLUG)
TR       = RDETimeRange(
    datetime_from_int(DATA_CONFIG['TIMERANGE_MINIMUM']),
    datetime_from_int(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True),
)

DATA_SRC_PATH = Path(os.path.join(parent_dir, 'data-venice/1808_Sommarioni/'))
MAP_FOLDER    = '../../maps/venice-1808-sommarioni/'
cadaster_layer_uuid = find_layer_uuid(
    find_latest_file(MAP_FOLDER + 'layers', 'json'), 'cadaster'
)

def _iiif_display(md: dict) -> str:
    chk  = lambda x: x if isinstance(x, str) and x.lower() != 'nan' and x else ''
    vals = [chk(md.get(k, '')) for k in ('parcel_number', 'sub_parcel_number', 'owner', 'qualities')]
    return ' | '.join(v for v in vals if v)


# ── 1. IIIF – build Page objects per registry volume ──────────────────────────
df_imgs = pd.read_csv('src/imgs_width_height_format.csv')
df_imgs['volume'] = df_imgs['filename'].str.split('/').str[0]
df_imgs['label']  = df_imgs['filename'].str.replace('.jpg', '', regex=False)
df_imgs = df_imgs.reset_index()          # stable 'index' column for range_idx

documents: dict[str, Document] = {}   # manifest_uid → Document
canvas_id_by_label: dict[str, str] = {}  # label → page.id

for vol, sdf in df_imgs.groupby('volume'):
    manifest_uid = uuid_mgr._generate_uuid(f'manifest_{DS_SLUG}_{vol}')
    vol_label    = MultiLingualValue({lang: [f'Archivio di Stato di Venezia, Catasti, Censo Stabile, Sommarioni, {vol}']
                                      for lang in ('en', 'fr', 'it')})
    pages = []
    for _, row in sdf.iterrows():
        page = Page(
            id=uuid_mgr._generate_uuid(f'{DS_SLUG}_{manifest_uid}_{row["index"]}'),
            label=MultiLingualValue({'it': [row['label']]}),
            format=row['media_type'],
            range_idx=int(row['index']),
            height=int(row['height']),
            width=int(row['width']),
            object_ref='venice/sommarioni/registry/' + row['filename'],
        )
        pages.append(page)
        canvas_id_by_label[row['label']] = page.id
    documents[manifest_uid] = Document(id=manifest_uid, label=vol_label, items=pages)

page_by_id = {p.id: p for doc in documents.values() for p in doc.items}

# ── 2. Geometries ──────────────────────────────────────────────────────────────
geom_fp = find_latest_file(
    str(DATA_SRC_PATH / 'venice_1808_landregister_geometries_internal_version'), 'geojson'
)
gdf = gpd.read_file(geom_fp)
gdf['geometry_id'] = gdf['geometry_id'].fillna(0).astype(int)

txt_fp = find_latest_file(
    str(DATA_SRC_PATH / 'venice_1808_landregister_textual_entries_internal_version'), 'json'
)
dfs = pd.read_json(txt_fp)

gdf_star = gdf[gdf.geometry_id.isin(dfs['geometry_id'])].copy()
centre   = (
    gdf_star.dissolve(by='geometry_id')
            .reset_index()[['geometry_id', 'geometry', 'parish_standardised']]
)
centre['coordinate'] = centre['geometry'].apply(Geometry.representative_point_inside)
centre = centre.set_index('geometry_id')

gdf.rename(columns={'id': 'geom_id'}, inplace=True)

geometries = Geometry.geometries_from_gdf(
    gdf,
    ['geom_id'],
    cadaster_layer_uuid,
    uuid_manager=uuid_mgr,
    force_valid=True,
)

geom_uuids_by_geom_id = (
    gdf.assign(uuid=[g.id for g in geometries])
       .groupby('geometry_id')['uuid'].apply(list)
)

# ── 3. Historical Records and Observations ─────────────────────────────────────
EXCLUDE = {
    # structural / derived columns
    'id', 'has_geometries', 'geometry_id', 'has_geometry', 'coordinate',
    'obs_uuid', 'hr_uuid', 'parcel_id',
    # dropped columns
    'llm_guess', 'is_people', 'new_transcription', 'area',
    # bilingual / redundant columns
    'old_religious_entity_type', 'qualities',
    'old_owner_right_of_use_owner_right_of_use',  # note: Python string-literal concat in legacy
    'ownership_types',
}

dfs['parcel_id'] = dfs[['parcel_number', 'sub_parcel_number']].apply(
    lambda v: ', '.join(e for e in v if e and not pd.isna(e)), axis=1
)
dfs = dfs.join(geom_uuids_by_geom_id.rename('has_geometries'), on='geometry_id')
dfs = dfs.join(centre[['coordinate', 'parish_standardised']], on='geometry_id')
dfs['owner_transcription'] = dfs['owner_transcription'].fillna('Unknown owner')
dfs = dfs.replace({np.nan: None})
dfs.at[dfs[dfs.unique_id == 23647].index[0], 'parish_standardised'] = None

hr_metadata_cols = [c for c in dfs.columns if c not in EXCLUDE]

dfs['hr_uuid'] = [uuid_mgr._generate_uuid(csv_seed(row, ['unique_id'])) for _, row in dfs.iterrows()]


def _observation_uuid_from_row(row: pd.Series) -> str:
    _buf = io.StringIO()
    pd.Series([row['parcel_id'], row['place'], row['hr_uuid']]).to_csv(_buf, index=False, header=False)
    return uuid_mgr._generate_uuid(_buf.getvalue())


dfs['obs_uuid'] = dfs.apply(_observation_uuid_from_row, axis=1)
hr_uuid_by_unique_id: dict[int, str] = dfs.set_index('unique_id')['hr_uuid'].to_dict()

hrs = HistoricalRecord.historical_records_from_df(
    dfs,
    id_col='hr_uuid',
    obs_col='obs_uuid',
    dataset_id=DS_UUID,
    time_range=TR,
    metadata_cols=hr_metadata_cols,
)
obs_list = Observation.observations_from_df(
    dfs,
    id_col='obs_uuid',
    hr_col='hr_uuid',
    geometry_col='coordinate',
    has_geometries_col='has_geometries',
)

# ── 4. IIIF – attach Annotation objects to pages ──────────────────────────────
hr_with_page = (
    dfs[dfs['page_number'].notnull()]
    .copy()
    .sort_values(['parcel_number', 'sub_parcel_number'])
)
hr_with_page['hr_uuid']   = hr_with_page['unique_id'].map(hr_uuid_by_unique_id)
hr_with_page['canvas_id'] = hr_with_page['page_number'].map(canvas_id_by_label)
hr_with_page['display']   = hr_with_page[hr_metadata_cols].apply(
    lambda r: _iiif_display(dict(r)), axis=1
)

for canvas_id, grp in hr_with_page.groupby('canvas_id', sort=False):
    page = page_by_id.get(canvas_id)
    if page is None:
        continue
    page.annotations = [
        Annotation(
            id=uuid_mgr._generate_uuid(f'annotation_{canvas_id}_{row["hr_uuid"]}'),
            lang='it' if row['display'] else None,
            value=row['display'] or None,
            hr_id=row['hr_uuid'],
        )
        for _, row in grp.iterrows()
    ]

# ── 5. Write IIIF manifests and collection ─────────────────────────────────────
os.makedirs('iiif/manifests',   exist_ok=True)
os.makedirs('iiif/collections', exist_ok=True)

for manifest_uid, doc in documents.items():
    with open(f'iiif/manifests/{manifest_uid}.json', 'w', encoding='utf-8') as f:
        json.dump(doc.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

collection_uid = uuid_mgr._generate_uuid(f'collection_{DS_SLUG}')
collection = Collection(
    id=collection_uid,
    label=MultiLingualValue({lang: ['Archivio di Stato di Venezia, Catasti, Censo Stabile, Sommarioni']
                              for lang in ('en', 'fr', 'it')}),
    items=list(documents.values()),
)
with open(f'iiif/collections/{collection_uid}.json', 'w', encoding='utf-8') as f:
    json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

# ── 6. Dataset ─────────────────────────────────────────────────────────────────
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    'dataproduction_config.json',
    dfs[hr_metadata_cols],
    sources=[collection_uid],
    ds_id=DS_UUID,
)
dataset.version = '1.1'

# ── 7. Validate and save ───────────────────────────────────────────────────────
full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
full_collection.validate_data()
print('Validation passed.')

full_collection.save_rde_to_files(MAP_FOLDER, overwrite=False, rde_types=[Geometry])
print(f'Saved {len(geometries)} geometries → {MAP_FOLDER}')

full_collection.save_rde_to_files('.', overwrite=False, rde_types=[HistoricalRecord, Observation, Dataset])
print(f'Saved {len(hrs)} HRs, {len(obs_list)} observations, 1 dataset → current dir')
