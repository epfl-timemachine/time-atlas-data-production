"""
produce_catastici_data_v2.py

Rewrite of produce_catastici_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling or utils/iiif.

UUID seeds for HR / Observation replicate the CSV-serialisation strategy of
the legacy script so all RDE object UUIDs are byte-for-byte identical between
the two versions.  IIIF document UUIDs (canvas, annotation, manifest) may
differ; their structure and ordering are consistent.
"""

import json, os, re, sys
from collections import OrderedDict
from functools import reduce
from pathlib import Path

import geopandas as gpd
import pandas as pd
from tqdm import tqdm

# ── Library path bootstrap ─────────────────────────────────────────────────────
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
timeatlas_dir = os.path.join(parent_dir, 'time-atlas-python')
if timeatlas_dir not in sys.path:
    sys.path.insert(0, timeatlas_dir)

from timeatlas.RDEModel import (
    UUIDManager, RDETimeRange, HistoricalRecord, Observation, Dataset, MultiLingualValue,
)
from timeatlas.production import datetime_from_int, normalize_to_epsg4326, csv_seed
from timeatlas.TimeAtlas import RDECollection
from timeatlas.DocumentModel import (
    Page, Annotation, Document, Collection,
    ordered_dict_to_iiif_toc_structure, multiindex_to_nested_dict,
)

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

CATASTICI_DATA_PATH = Path(os.path.join(parent_dir, 'data-venice/1740_Catastici/'))

# Boolean flag: True = use tif manifests, False = use jpeg manifests (legacy)
is_man_tif = True
gpd.options.io_engine = 'pyogrio'

# ── 1. Load and prepare source data ───────────────────────────────────────────
old_df = pd.read_json(list(CATASTICI_DATA_PATH.rglob('catastici_text_data_*.json'))[-1])
df = gpd.read_file(list(Path('src').rglob('1740_Catastici_*.geojson'))[-1])
df = df.drop(columns=['tif_path_img'])

# Patch tif_path_img and path_img from the old json (preserving order-independent uid mapping)
old_uid_to_tif_path_img = old_df.set_index('uid')['tif_path_img'].to_dict()
old_uid_to_path_img     = old_df.set_index('uid')['path_img'].to_dict()
df['tif_path_img'] = df['uid'].map(old_uid_to_tif_path_img)
df['path_img']     = df['uid'].map(old_uid_to_path_img)

# Replace "nan" strings with None (mirrors v1)
for col in ('quantity_income', 'quality_income', 'id_napo', 'ten_name',
            'an_rendi', 'function', 'owner_name', 'place'):
    df[col] = df[col].replace({'nan': None})

# CRS conversion: obs geometry will come from gdf (EPSG:4326)
gdf = normalize_to_epsg4326(
    gpd.GeoDataFrame(df, geometry='geometry'),
    source_crs='EPSG:32633',
)

# Path fixes for jpeg-version IIIF (path_img) — applied to gdf only so that
# HR metadata (from df) retains the original unfixed path_img values, matching v1.
smarco_replace_dict = {
    '434_SMarco/2_SBasso/SBasso_0_1.png':         '434_SMarco/2_SBasso/SBasso_0_01.png',
    '434_SMarco/3_SZiminian/SZiminian_0_1.png':    '434_SMarco/3_SZiminian/SZiminian_0_01.png',
    '434_SMarco/3_SZiminian/SZiminian_1_9.png':    '434_SMarco/3_SZiminian/SZiminian_1_09.png',
    '434_SMarco/7_SBortolomio/SBortolomio_0_1.png':'434_SMarco/7_SBortolomio/SBortolomio_0_01.png',
    '434_SMarco/4_SMoise/SMoise_60_643.png':        '434_SMarco/4_SMoise/SMoise_60_693.png',
}
castello_replace_dict = {
    v: v.replace('Nuovo', 'Novo').replace('Pietro', 'Piero')
    for v in gdf[gdf['path_img'].str.contains('435_Castello', na=False)]['path_img'].unique()
}
canna_replace_dict = {
    '436_Cannaregio/11_SCancian/SCancian_0_1.png': '436_Cannaregio/11_SCancian/SCancian_0_01.png',
}
spolo_replace_dict = {
    v: v.replace('SGiovanniElmosinario', 'SGiovanniNovo')
    for v in gdf[gdf['path_img'].str.contains('437_SPolo', na=False)]['path_img'].unique()
}
spolo_replace_dict['437_SPolo/1_SPolo/SPolo_12_85.png'] = '437_SPolo/1_SPolo/SPolo_12_86.png'
scroce_replace_dict = {
    v: v.replace('SSimeonProfeta', 'SSimonProfeta')
        .replace('SSimeonApostolo', 'SSimonPiccolo')
        .replace('SGiovanniDecollato', 'SGiovannidecollato')
    for v in gdf[gdf['path_img'].str.contains('438_SCroce', na=False)]['path_img'].unique()
}
dorso_replace_dict = {
    v: v.replace('SNicolo', 'SanNicolo').replace('SRaffael', 'AngeloRaffael')
    for v in gdf[gdf['path_img'].str.contains('439_Dorsoduro', na=False)]['path_img'].unique()
}
dorso_replace_dict['439_Dorsoduro/5_SBarnaba/SBarnaba_11_103.png'] = '439_Dorsoduro/5_SBarnaba/SBarnaba__11_103.png'
dorso_replace_dict['439_Dorsoduro/9_SBaseggio/SBaseggio_0_1.png']  = '439_Dorsoduro/9_SBaseggio/SBaseggio_0_01.png'
manuals_leftovers = {
    '438_SCroce/2_SCassiano/SCassiano_0_1.png':          '438_SCroce/2_SCassiano/SCassiano_0_01.png',
    '439_Dorsoduro/9_SBaseggio/SBaseggio_0_1.png':       '439_Dorsoduro/9_SBaseggio/SBaseggio_0_01.png',
    '440_Ghetto/1_GhettoVecchio/57_407.png':             '440_Ghetto/1_GhettoVecchio/57_407.jpg',
}
replace_dict = {
    **smarco_replace_dict, **castello_replace_dict, **canna_replace_dict,
    **scroce_replace_dict, **spolo_replace_dict, **dorso_replace_dict,
    **manuals_leftovers,
}
gdf['path_img'] = gdf['path_img'].apply(
    lambda x: x.replace('Beneto', 'Benetto').replace('Basegio', 'Baseggio')
               if x is not None and not pd.isna(x) else None
)
gdf['path_img'] = gdf['path_img'].apply(lambda x: replace_dict.get(x, x))

# ── 2. IIIF helper functions ───────────────────────────────────────────────────
def technical_name_to_natural_name(t: str) -> str:
    all_vals = re.sub(r'([A-Z])', r' \1', t).split()
    prefix = ''
    if all_vals[0][0].isupper() and len(all_vals[0]) == 1:
        if all_vals[0] == 'S':
            prefix += 'San'
            if all_vals[1][-1] == 'a':
                prefix += 'ta'
    return ' '.join([prefix] + all_vals[1:] if prefix else all_vals)


def underscore_split(t: str) -> list[str]:
    return [l for l in [v.replace('_', '') for v in re.sub(r'(_)', r' \1', t).split()] if l]


def filename_to_label(filename: str) -> tuple:
    try:
        vol_, parish_, page_idx_ = [underscore_split(v) for v in filename.split('/')]
        vol_numb    = vol_[0]
        vol         = technical_name_to_natural_name(vol_[1])
        parish      = technical_name_to_natural_name(parish_[1])
        parish_numb = parish_[0]
        page_idx    = page_idx_[1] if 'ghetto' not in parish.lower() else page_idx_[0]
        page_idx    = page_idx.replace('.png', '').replace('.jpg', '')
        return int(vol_numb), vol, int(parish_numb), parish, int(page_idx)
    except Exception as e:
        print(e, filename)
        return filename, '', '', '', ''


def tif_filename_to_subparts(tif_filename: str) -> tuple:
    """Extract (volume_number, parish_number, page_index) from a tif filename."""
    try:
        tif_filename = tif_filename.replace('/catastici/Catastici-', '').replace('.tif', '')
        vals = [v for v in tif_filename.split('/')]
        if len(vals) == 3:
            vol_numb, parish_numb, page_idx = vals
        elif len(vals) == 2:
            vol_numb, page_idx = vals
            parish_numb = 0
        else:
            raise ValueError('The filename does not have the correct number of parts.', tif_filename)
        return int(vol_numb), int(parish_numb), int(page_idx)
    except Exception as e:
        print(e, tif_filename)
        return tif_filename, '', ''


# ── 3. Build IIIF page table (jpeg version for ToC bootstrap) ─────────────────
df_wh = pd.read_csv('src/imgs_width_height_format.csv')
df_wh['filename'] = df_wh['filename'].apply(
    lambda x: x.replace('434_SanMarco', '434_SMarco') if x is not None and not pd.isna(x) else x
)
df_wh['volume_number'], df_wh['volume'], df_wh['parish_number'], df_wh['parish'], df_wh['page_index'] = \
    zip(*df_wh['filename'].apply(filename_to_label))

if is_man_tif:
    all_catasticis = Path('src/tif_img_wh/').rglob('catastici_1740_4*.csv')

    def read_csv_and_patch_folder_name(f: Path) -> pd.DataFrame:
        folder_name = str(f).split('_')[-1].replace('.csv', '')
        df_t = pd.read_csv(f)
        df_t['filename'] = df_t['filename'].apply(lambda x: f'/catastici/Catastici-{folder_name}/{x}')
        return df_t

    df_tifs = reduce(
        lambda x, y: pd.concat([x, y]),
        [read_csv_and_patch_folder_name(f) for f in all_catasticis],
        pd.DataFrame(),
    )

    sel_cols = ['volume_number', 'volume', 'parish_number', 'parish']
    toc_vals = (
        df_wh.sort_values(by=['page_index'])
             .groupby(sel_cols)
             .first()
             .reset_index()[sel_cols + ['filename']]
    )
    path_to_tif_path = (
        gdf[['path_img', 'tif_path_img']]
           .drop_duplicates()
           .set_index('path_img')['tif_path_img']
           .to_dict()
    )
    missing_matches = {
        '435_Castello/4_SMartin/SMartin_0_1.png':
            'Catastici-435/4/0565.tif',
        '436_Cannaregio/12_SGiovanniGrisostomo/SGiovanniGrisostomo_0_ni.png':
            'Catastici-436/11/1519.tif',
        '438_SCroce/10_SSalvadorMurano/SSalvadorMurano_0.png':
            'Catastici-438/10/1263.tif',
        '438_SCroce/11_SStefanoMurano/SStefanoMurano_0.png':
            'Catastici-438/11/1279.tif',
        '438_SCroce/12_SMartinMurano/SMartinMurano_0.png':
            'Catastici-438/12/1491.tif',
        '438_SCroce/13_SDonatoMurano/SDonatoMurano_0.png':
            'Catastici-438/13/1555.tif',
    }
    path_to_tif_path = {**path_to_tif_path, **missing_matches}
    toc_vals['path_tif'] = toc_vals['filename'].apply(lambda x: path_to_tif_path.get(x, None))

    df_tifs[['volume_number', 'parish_number', 'page_index']] = (
        df_tifs['filename']
               .apply(lambda x: tif_filename_to_subparts(x))
               .apply(pd.Series)
    )
    df_tifs = df_tifs.sort_values(by=['volume_number', 'page_index', 'parish_number'])

    filenames_of_interest = (
        toc_vals[toc_vals['path_tif'].notna()]
               .set_index('path_tif')[['volume_number', 'volume', 'parish_number', 'parish']]
               .to_dict(orient='index')
    )
    vol_first_pages = {
        '/catastici/Catastici-434/0000.tif': {'volume_number': 434, 'volume': 'San Marco',   'parish_number': 0, 'parish': 'index'},
        '/catastici/Catastici-435/0000.tif': {'volume_number': 435, 'volume': 'Castello',    'parish_number': 0, 'parish': 'index'},
        '/catastici/Catastici-436/0000.tif': {'volume_number': 436, 'volume': 'Cannaregio',  'parish_number': 0, 'parish': 'index'},
        '/catastici/Catastici-437/0000.tif': {'volume_number': 437, 'volume': 'San Polo',    'parish_number': 0, 'parish': 'index'},
        '/catastici/Catastici-438/0000.tif': {'volume_number': 438, 'volume': 'Santa Croce', 'parish_number': 0, 'parish': 'index'},
        '/catastici/Catastici-439/0000.tif': {'volume_number': 439, 'volume': 'Dorsoduro',   'parish_number': 0, 'parish': 'index'},
    }
    filenames_of_interest = {**filenames_of_interest, **vol_first_pages}

    df_tifs[['volume_number_toc', 'volume_toc', 'parish_number_toc', 'parish_toc']] = (
        df_tifs['filename']
               .apply(lambda x: filenames_of_interest.get(x, None))
               .apply(lambda v: pd.Series(v, dtype=str))
    )
    df_wh_tif = (
        df_tifs.ffill()
               .drop(columns=['volume_number', 'parish_number'])
               .rename(columns={
                   'volume_number_toc': 'volume_number',
                   'parish_number_toc': 'parish_number',
                   'volume_toc':        'volume',
                   'parish_toc':        'parish',
               })
    )
    # The Ghetto has no tif scans; use jpeg metadata instead.
    df_ghetto        = df_wh[df_wh['volume_number'] == 440]
    df_ghetto_sorted = df_ghetto.sort_values(by=['parish_number', 'page_index'])
    df_ghetto_index  = df_ghetto_sorted.iloc[:6].copy()
    df_ghetto_index['parish_number'] = 0
    df_ghetto_index['parish']        = 'index'
    df_ghetto_fixed  = pd.concat([df_ghetto_index, df_ghetto_sorted.iloc[6:]])

    df_wh_tif = pd.concat([df_wh_tif, df_ghetto_fixed])
    df_wh_tif['volume_number'] = df_wh_tif['volume_number'].astype(int)
    df_wh_tif['parish_number'] = df_wh_tif['parish_number'].astype(int)
    df_wh = df_wh_tif

df_pages = (
    df_wh.sort_values(by=['volume_number', 'parish_number', 'page_index'])
         .reset_index(drop=True)
         .reset_index()  # adds 'index' column used for canvas UUID seeding
)

# ── 4. Archival citation lookup ────────────────────────────────────────────────
volume_number_to_cote = {
    '434': 'Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia, Catastico di San Marco, b. 434',
    '435': 'Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia, Catastico di Castello, b. 435',
    '436': 'Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia, Catastico di Castello, b. 436',
    '437': 'Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia, Catastico di San Polo, b. 437',
    '438': 'Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia, Catastico di Santa Croce, b. 438',
    '439': 'Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia, Catastico di Dorsoduro, b. 439',
    '440': 'Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia, Catastico di Ghetto, b. 440',
}

# ── 5. Build IIIF Page / Document objects ─────────────────────────────────────
# Fix a known typo before grouping
df_pages['volume'] = df_pages['volume'].replace('San Croce', 'Santa Croce')

documents: dict[str, Document]   = {}   # manifest_uid  → Document
page_by_id: dict[str, Page]       = {}   # page_id       → Page
filename_to_canvas_id: dict[str, str] = {}  # tif/jpg path → page_id

for (volume_number, volume_name), group_df in df_pages.groupby(['volume_number', 'volume']):
    volume_title = f'{volume_number}-{volume_name}'
    cote         = volume_number_to_cote.get(
        str(volume_number),
        f'Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, '
        f'Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia, b. {volume_number}',
    )
    manifest_uid = uuid_mgr._generate_uuid(f'manifest_{DS_SLUG}_{volume_title}')
    man_label    = MultiLingualValue({'it': [cote], 'fr': [cote], 'en': [cote]})

    pages: list[Page] = []
    canvas_ids_for_toc: list[str] = []

    for _, row in group_df.iterrows():
        # Canvas UUID mirrors the legacy formula:
        # uuid.uuid5(VTM_UUID5_NS, f"{DS_UUID}_{manifest_uid}_{x['index']}")
        page_id    = uuid_mgr._generate_uuid(f'{DS_UUID}_{manifest_uid}_{row["index"]}')
        page_label = f"{row['volume']}: {row['page_index']}"
        file_path  = 'venice/' + ('' if row['filename'].endswith('tif') else 'catastici_1740/') + row['filename']

        page = Page(
            id=page_id,
            label=MultiLingualValue({'it': [page_label]}),
            format=row['media_type'],
            range_idx=int(row['index']),
            height=int(row['height']),
            width=int(row['width']),
            object_ref=file_path,
        )
        pages.append(page)
        page_by_id[page_id]                = page
        filename_to_canvas_id[row['filename']] = page_id
        canvas_ids_for_toc.append(page_id)

    # Build per-volume Table-of-Contents structure (mirrors v1)
    toc_df = group_df.copy()
    toc_df['parish_order'] = toc_df['parish_number'].apply(lambda v: f'{v:02d}') + '-' + toc_df['parish']
    toc_df = toc_df.assign(canvas_id=canvas_ids_for_toc)
    toc_groups = toc_df[['parish_order', 'canvas_id']].groupby('parish_order').agg(list)
    structure  = ordered_dict_to_iiif_toc_structure(
        multiindex_to_nested_dict(toc_groups), 'it', 'Sommario', f'{manifest_uid}/range',
    )

    documents[manifest_uid] = Document(
        id=manifest_uid, label=man_label, items=pages, structures=structure,
    )

# ── 6. Historical Records, Observations, and IIIF annotations ─────────────────
# Add sequential index used as UUID seed (mirrors v1's df['uidx'] = df.index)
df['uidx'] = df.index

# Derive bibliographic_reference for each entry (mirrors v1)
df['volume_number'] = df['tif_path_img'].apply(
    lambda x: str(int(tif_filename_to_subparts(x)[0]))
               if x is not None and not pd.isna(x) else None
)
df['bibliographic_reference'] = df['volume_number'].map(volume_number_to_cote)

# Columns to exclude from HR metadata (mirrors v1's exclude_hr_labels)
EXCLUDE = {'geometry', 'obs_uuid', 'hr_uuid', 'uidx', 'uid', 'volume_number'}
hr_metadata_cols = [c for c in df.columns if c not in EXCLUDE]

df['hr_uuid'] = [uuid_mgr._generate_uuid(csv_seed(row, ['uidx'])) for _, row in df.iterrows()]
df['obs_uuid'] = [uuid_mgr._generate_uuid(csv_seed(row, ['uidx', 'uid'])) for _, row in df.iterrows()]
df['obs_geometry'] = [gdf.loc[row.name, 'geometry'] for _, row in df.iterrows()]
hr_uuid_by_row_idx: dict[int, str] = df.set_index('uidx')['hr_uuid'].to_dict()

hrs = HistoricalRecord.historical_records_from_df(
    df,
    id_col='hr_uuid',
    obs_col='obs_uuid',
    dataset_id=DS_UUID,
    time_range=TR,
    metadata_cols=hr_metadata_cols,
)
obs_list = Observation.observations_from_df(
    df,
    id_col='obs_uuid',
    hr_col='hr_uuid',
    geometry_col='obs_geometry',
)

# ── 7. Attach IIIF annotations (HR ↔ canvas links) ────────────────────────────
def catastici_metadata_to_display_string(metadata: dict) -> str:
    def qc(x):
        if x is None:
            return ''
        if isinstance(x, (int, float)):
            return str(x) if not pd.isna(x) else ''
        if isinstance(x, str):
            return x if x.lower() != 'nan' and len(x) > 0 else ''
        return ''
    vals = [qc(metadata.get(k, '')) for k in ('place', 'function', 'ten_name', 'owner_name')]
    rendi = qc(metadata.get('an_rendi', ''))
    return ' | '.join(v for v in vals + [rendi] if v)


# Build hr_uuid → (canvas_id, display_string) mapping for annotation injection
for hr in tqdm(hrs, desc='IIIF annotations'):
    meta = hr.metadata
    filename = meta.get('tif_path_img') if is_man_tif else meta.get('path_img')
    if not filename or pd.isna(filename):
        continue
    canvas_id = filename_to_canvas_id.get(filename, '')
    if not canvas_id:
        continue
    page = page_by_id.get(canvas_id)
    if page is None:
        continue
    display = catastici_metadata_to_display_string(meta)
    annotation = Annotation(
        id=uuid_mgr._generate_uuid(f'annotation_{canvas_id}_{hr.id}'),
        lang='it' if display else None,
        value=display if display else None,
        hr_id=hr.id,
    )
    if page.annotations is None:
        page.annotations = []
    page.annotations.append(annotation)

# ── 8. Write IIIF manifests and collection ─────────────────────────────────────
os.makedirs('iiif/manifests',   exist_ok=True)
os.makedirs('iiif/collections', exist_ok=True)

for manifest_uid, doc in tqdm(documents.items(), desc='Writing manifests'):
    with open(f'iiif/manifests/{manifest_uid}.json', 'w', encoding='utf-8') as f:
        json.dump(doc.to_iiif(uuid_mgr, IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

coll_label = MultiLingualValue({
    lang: ['Archivio di Stato di Venezia, Dieci Savi alle Decime di Rialto, '
           'Deputazioni Unite, Commisurazione delle imposte, Catastici di Venezia']
    for lang in ('en', 'fr', 'it')
})
collection_uid = uuid_mgr._generate_uuid(f'collection_{DS_SLUG}')
collection = Collection(
    id=collection_uid,
    label=coll_label,
    items=list(documents.values()),
)
with open(f'iiif/collections/{collection_uid}.json', 'w', encoding='utf-8') as f:
    json.dump(collection.to_iiif(IIIF_BASE_URL), f, indent=2, ensure_ascii=False)

# ── 9. Dataset ─────────────────────────────────────────────────────────────────
labels_order = list(DATA_CONFIG['DATASET_CONFIGURATION']['labels'].keys())
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    'dataproduction_config.json',
    df[[col for col in labels_order if col in df.columns]],
    sources=[collection_uid],
    ds_id=DS_UUID,
)
dataset.version = '1.1'

# ── 10. Validate and save ──────────────────────────────────────────────────────
full_collection = RDECollection(hrs + obs_list + [dataset])
if any(obs.has_geometries is None for obs in obs_list):
    full_collection.validate_data(mode='raw')
    print('Validation passed in raw mode: legacy output contains observations with null has_geometries.')
else:
    full_collection.validate_data()
    print('Validation passed.')

full_collection.save_rde_to_files('.', overwrite=False, rde_types=[HistoricalRecord, Observation, Dataset])
print(f'Saved {len(hrs)} HRs, {len(obs_list)} observations, 1 dataset → current dir')
