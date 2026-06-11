"""
produce_cini_data_v2.py

Rewrite of produce_cini_data.py using the timeatlas library classes
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
from functools import reduce
from pathlib import Path
from tqdm import tqdm

# ── Library path bootstrap ─────────────────────────────────────────────────────
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
from timeatlas.helpers import _datetime_from_int, _get_layer_uuid, _clean_metadata
from timeatlas.TimeAtlas import RDECollection
from timeatlas.DocumentModel import Page, Annotation, Document, Collection

IIIF_BASE_URL = 'https://image-timemachine.epfl.ch/iiif/3'

# ── Configuration ──────────────────────────────────────────────────────────────
with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG  = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID  = uuid_mgr._generate_uuid(DS_SLUG)


def _seed(row: pd.Series, cols: list[str], suffix: str = '') -> str:
    """Replicate the CSV-seed produced by legacy make_uuid_from_row_selection."""
    buf = io.StringIO()
    row[cols].to_csv(buf, index=False, header=False)
    return buf.getvalue() + suffix


# ── 1. Load and prepare source data ───────────────────────────────────────────
DATA_VENICE_FOLDER = os.path.join(parent_dir, 'data-venice')
MAP_FOLDER = '../../maps/venice-2024-contemporary/'
edifici_layer_uuid = _get_layer_uuid(MAP_FOLDER + 'layers.json', 'venice-2024-contemporary-map-edifici')

df_raw = pd.read_json('src/sample_3_edifici.json').replace({np.nan: None})

min_time = _datetime_from_int(int(df_raw['BeginDate'].dropna().min()))
max_time = _datetime_from_int(int(df_raw['EndDate'].dropna().max()), match_to_end=True)

df_raw['start_time']             = df_raw['BeginDate'].apply(lambda x: _datetime_from_int(int(x))                    if x is not None else min_time)
df_raw['end_time']               = df_raw['EndDate'].apply(lambda x: _datetime_from_int(int(x), match_to_end=True)   if x is not None else max_time)
df_raw['author_birth_date_time'] = df_raw['AuthorBirth'].apply(lambda x: _datetime_from_int(int(x)) if x is not None else None)
df_raw['author_death_date_time'] = df_raw['AuthorDeath'].apply(lambda x: _datetime_from_int(int(x)) if x is not None else None)
df_raw['type'] = 'photograph'

# ── 2. Geometries (all edifici, matching v1 scope) ────────────────────────────
gdf_all_edifici = (
    gpd.read_file(os.path.join(DATA_VENICE_FOLDER, 'contemporary_maps/2024_Edifici_EPSG32633.geojson'))
       .to_crs('EPSG:4326')
       .explode()
)
# One geometry per EDIFI_ID (first polygon after explode)
gdf_edifici = gdf_all_edifici[['geometry', 'EDIFI_ID']].groupby('EDIFI_ID').first().reset_index()

# UUID seed is prefixed with "geometry_" to avoid any collision with HR/Obs seeds
# derived from plain integer ImageNumbers (Geometry.__post_init__ does not call
# super(), so the UUIDEntity tuple form must be replicated explicitly here).
geometries = [
    Geometry(id=uuid_mgr._generate_uuid(f'geometry_{row["EDIFI_ID"]}'), geometry=row.geometry, part_of_layer=edifici_layer_uuid, force_valid=True)
    for _, row in tqdm(gdf_edifici.iterrows(), total=len(gdf_edifici), desc='Geometries')
]

# Build EDIFI_ID → UUID lookup from the created objects
edifi_to_uuid = {row['EDIFI_ID']: geom.id for (_, row), geom in zip(gdf_edifici.iterrows(), geometries)}

# Write cross-dataset reference file
with open('edifici_id_to_geom_uuid.json', 'w+') as f:
    json.dump(edifi_to_uuid, f)

# Merge photo data with edifice geometry (one polygon per photo's EDIFI_ID)
gdf = gpd.GeoDataFrame(
    df_raw.merge(gdf_edifici[['geometry', 'EDIFI_ID']].set_index('EDIFI_ID'), on='EDIFI_ID'),
    geometry='geometry',
).set_crs('EPSG:4326')

# ── 3. Historical Records and Observations ─────────────────────────────────────
# Columns to exclude from HR metadata (mirrors v1's cols_of_non_interest + structural cols)
EXCLUDE = {
    'geometry', 'centroid', 'hr_uuid', 'obs_uuid', 'has_geometries',
    'FondoStamp', 'Country', 'ImageNumber', 'EDIFI_ID',
    'AuthorNeighbour', 'CiniTime', 'AuthorComplemented',
    'AuthorDeathLat', 'AuthorDeathLong', 'AuthorBirthLat', 'AuthorBirthLong',
    'AuthorDeath', 'AuthorBirth', 'AuthorNeighbourhood', 'AutorNeighbour',
    'AuthorComplement', 'PhysicalID',
    'City', 'Reference', 'archiType', 'AuthorGender', 'AuthorNationality',
    'uid', 'CardboardURL', 'ImageURL', 'archiComment', 'archiLikelyType',
    'AuthorULAN', 'AuthorULANLabel', 'CiniNumber', 'BeginDate', 'EndDate', 'uidMorph',
}
hr_metadata_cols = [c for c in gdf.columns if c not in EXCLUDE]

hrs, obs_list = [], []
hr_uuid_by_image = {}

for _, row in tqdm(gdf.iterrows(), total=len(gdf), desc='HRs & Obs'):
    hr_uuid  = uuid_mgr._generate_uuid(_seed(row, ['ImageNumber']))
    obs_uuid = uuid_mgr._generate_uuid(_seed(row, ['ImageNumber'], suffix='obs'))
    has_geom = [edifi_to_uuid[row['EDIFI_ID']]]
    time_range = RDETimeRange(row['start_time'], row['end_time'])
    metadata = _clean_metadata({k: row[k] for k in hr_metadata_cols})

    hrs.append(HistoricalRecord(
        id=hr_uuid,
        dataset=DS_UUID,
        time_range=time_range,
        paradata='m',
        has_observations=[obs_uuid],
        metadata=metadata,
    ))
    obs_list.append(Observation(
        id=obs_uuid,
        historical_record=hr_uuid,
        geometry=row.geometry.centroid,
        has_geometries=has_geom,
        part_of_point_of_interest=True,
    ))
    hr_uuid_by_image[row['ImageNumber']] = hr_uuid

# ── 4. IIIF – build Page objects per Drawer ────────────────────────────────────
def _read_wh_csv(f: Path) -> pd.DataFrame:
    folder_name = str(f).split('_')[-1].replace('.csv', '')
    df = pd.read_csv(f)
    df['filename'] = df['filename'].apply(lambda x: f'/{folder_name}/{x}')
    return df

df_wh = reduce(
    lambda a, b: pd.concat([a, b]),
    [_read_wh_csv(f) for f in Path('src/img_wh/').rglob('*.csv')],
    pd.DataFrame(),
)

gdf['filename']       = gdf.apply(lambda r: f'/{r["Drawer"]}/{r["CINI_ID"]}.jpg', axis=1)
gdf['annotation_txt'] = gdf.apply(lambda s: f"{s['BUILDING_NAME']} | {s['CiniNumber']}", axis=1)
gdf['hr_uuid']        = gdf['ImageNumber'].map(hr_uuid_by_image)

df_wh = df_wh.merge(
    gdf[['filename', 'hr_uuid', 'Drawer', 'annotation_txt']].set_index('filename'),
    on='filename',
)

documents: dict[str, Document] = {}
for drawer, sdf in df_wh.groupby('Drawer'):
    # manifest UUID matches v1: uuid.uuid5(VTM_UUID5_NS, drawer)
    manifest_uid = uuid_mgr._generate_uuid(drawer)
    pages = []
    for num, row in sdf.reset_index().iterrows():
        # canvas UUID matches v1: uuid.uuid5(NS, f"{DS_UUID}_{manifest_uid}_{num}")
        canvas_uid = uuid_mgr._generate_uuid(f'{DS_UUID}_{manifest_uid}_{num}')
        pages.append(Page(
            id=canvas_uid,
            label=MultiLingualValue({'en': [row['annotation_txt']]}),
            format=row['media_type'],
            range_idx=num,
            height=int(row['height']),
            width=int(row['width']),
            object_ref='venice/cini/cardboards' + row['filename'],
            annotations=[Annotation(
                id=uuid_mgr._generate_uuid(f'annotation_{canvas_uid}_{row["hr_uuid"]}'),
                lang='en',
                value=row['annotation_txt'],
                hr_id=row['hr_uuid'],
            )],
        ))
    documents[manifest_uid] = Document(
        id=manifest_uid,
        label=MultiLingualValue({'en': [f"Cardboards Photographs from Cini's Foundation: {drawer}"]}),
        items=pages,
    )

# ── 5. Write IIIF manifests and collection ─────────────────────────────────────
os.makedirs('iiif/manifests',   exist_ok=True)
os.makedirs('iiif/collections', exist_ok=True)

for manifest_uid, doc in documents.items():
    with open(f'iiif/manifests/{manifest_uid}.json', 'w', encoding='utf-8') as f:
        json.dump(doc.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

# collection UUID matches v1: uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}')
collection_uid = uuid_mgr._generate_uuid(f'collection_{DS_SLUG}')
collection = Collection(
    id=collection_uid,
    label=MultiLingualValue({'en': ["Cini's Foundation: Photographs of 3 Venetian Buildings (test sample)"]}),
    items=list(documents.values()),
)
with open(f'iiif/collections/{collection_uid}.json', 'w', encoding='utf-8') as f:
    json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

# ── 6. Dataset ─────────────────────────────────────────────────────────────────
cols_of_interest_ordered = [
    'BUILDING_NAME', 'Author', 'Description',
    'AuthorBirthCity', 'AuthorDeathCity', 'AuthorOriginal',
    'AuthorURL', 'BiographyLabel', 'CINI_ID',
    'CiniCollection', 'Drawer', 'Institution',
    'SimpleCollection', 'author_birth_date_time', 'author_death_date_time',
]
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    'dataproduction_config.json',
    df_raw[cols_of_interest_ordered],
    sources=[collection_uid],
    ds_id=DS_UUID,
)

# ── 7. Validate and save ───────────────────────────────────────────────────────
full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
full_collection.validate_data()
print('Validation passed.')

full_collection.save_rde_to_files(MAP_FOLDER, overwrite=True, rde_types=[Geometry])
print(f'Saved {len(geometries)} geometries → {MAP_FOLDER}')

full_collection.save_rde_to_files('.', overwrite=True, rde_types=[HistoricalRecord, Observation, Dataset])
print(f'Saved {len(hrs)} HRs, {len(obs_list)} observations, 1 dataset → current dir')
