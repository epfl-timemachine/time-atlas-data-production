import uuid
import pandas as pd
import geopandas as gpd
import os
from os.path import join
import sys
from pathlib import Path
from tqdm import tqdm
import json
from functools import reduce
from shapely.geometry import Point

# to have progress bar in the notebook
tqdm.pandas()
with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from timeatlas.data_modeling import *
from timeatlas.RDEModel import RDEType

DATA_SRC_PATH = Path(join(parent_dir, 'data-lausanne/icono-data-processing'))
TM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DATA_FOLDER = ''
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(TM_UUID5_NS, DS_SLUG))
DS_OBJ = (DS_SLUG, DS_UUID)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))

lausanne_area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

gdf = pd.read_json(list(DATA_SRC_PATH.glob('matched_records.json'))[0])
gdf['geometry'] = gdf.apply(lambda x: Point(x['longitude'], x['latitude']), axis=1)
gdf = gpd.GeoDataFrame(gdf, geometry='geometry', crs='EPSG:4326').drop(columns=['latitude', 'longitude'])
# removing the 5-6 records that have incoherent dates 
gdf = gdf[gdf.start_year > 1500]
df_wh = pd.read_csv(list(DATA_SRC_PATH.glob('wh_image_dimensions.csv'))[0])
df_wh = df_wh[df_wh['image_url'].isin(gdf['image_url'])]

gdf['start_time'] = gdf['start_year'].apply(lambda y: datetime_obj_from_int_time(y*10000 + 101))
gdf['end_time'] = gdf['end_year'].apply(lambda y: datetime_obj_from_int_time(y*10000 + 1231, match_to_end=True))

df_wh['image_id'] = df_wh.image_url.apply(lambda x: f"image_{x.split('id=')[1]}.jpg")

tqdm.pandas(desc="Generating hr uuid")
gdf['hr_uuid'] = gdf.apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['id'], ad_hoc_seed='hr'), axis=1)
tqdm.pandas(desc="Generating obs uuid")
gdf['obs_uuid'] = gdf.apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['id'], ad_hoc_seed='obs'), axis=1)

tpe='photograph'

# Generating Obs RDE
obs = [produce_obs_obj(
    v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, tpe, v.geometry, None
) for _,v in gdf.iterrows()]

gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_index('id').set_crs('EPSG:4326')

QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, "observations", gdf_obs, f'lausanne_mhl_photographs_obs', RDEType.OBS.value)
df = gdf.merge(df_wh[['image_url', 'image_id', 'width', 'height', 'media_type']], on='image_url')
df['display_title'] = df.apply(lambda r: f"({r['file_reference']}) {r['titre']}", axis=1)


from utils.iiif import *
create_iiif_directory_if_not_exists()
# Generating the IIIF manifests
df['image_fp'] = df['image_id'].apply(lambda v: 'lausanne/mhl_iconographie/' + v)
man_list = {}
for i, row in tqdm(df.iterrows(), total=len(df), desc="Generating IIIF manifests"):
    manifest_uuid = make_uuid_from_row_selection(TM_UUID5_NS, row, ['id'], ad_hoc_seed='photograph_manifest')
    width, height = row.width, row.height
    description = row['description'] if pd.notna(row['description']) else 'No description available.'
    page_obj = generate_page_object(
        TM_UUID5_NS,
        DS_UUID,
        0,
        manifest_uuid,
        row['display_title'],
        row['image_fp'],
        row['media_type'],
        height,
        width,
        'en',
        metadata=[[row['hr_uuid'], row['display_title']]],
        external_resource=row['record_url']
    )
    man = generate_manifest_object(TM_UUID5_NS, manifest_uuid, {'en':[row['display_title'] + ' ' + row['description']]},'en', [page_obj])

    with open(f'iiif/manifests/{manifest_uuid}.json', 'w') as f:
        f.write(json.dumps(man, indent=2, ensure_ascii=False))
    man_list[manifest_uuid] = ({"en":[row['description']]}, page_obj)

# generating the collection
collection_uuid = str(uuid.uuid5(TM_UUID5_NS, f'{DS_SLUG}_collection'))
collection_obj = generate_collection_manifest(
    collection_uuid,
    {'en': ['Geolocated photographs from the MHL, Lausanne. Data retrieved from museris.lausanne.ch']},
    man_list)

with open(f'iiif/collections/{collection_uuid}.json', 'w') as f:
    f.write(json.dumps(collection_obj, indent=2, ensure_ascii=False))

drop_cols = ['image_id', 'width', 'height',
       'media_type', 'display_title', 'image_fp', 'geometry', 
        'start_year', 'end_year',
       ]
df_hr = df.copy().drop(columns=drop_cols)
df_hr = df_hr.replace({np.nan: None})
tpe = 'photograph'

recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                   [[r.obs_uuid, 'street']],\
                       (r.start_time, r.end_time),\
                       tpe, \
                   r.drop(labels = ['hr_uuid', 'obs_uuid', 'start_time', 'end_time']).to_dict(),
                   None,
                   'm'
                   ).to_dict(flatten_metadata=False) \
                   for _, r in df_hr.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'lausanne_mhl_photographs_hrs', RDEType.HR.value)

df_of_hr = pd.DataFrame(data = recs)

QA_check_uuid_are_unique(df_of_hr)

# Dataset RDE Object production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
filtered_df = df_hr.drop(columns=['hr_uuid', 'obs_uuid'])
labels = CONF['labels']
order = labels.keys()
ds_conf, md = produce_configuration_file_from_metadata_df(
    TM_UUID5_NS,
    filtered_df[order],
    CONF
)

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    "1.0",
    CONF['name'],
    [collection_uuid],
    TR_OBJ,
    0,
    ds_conf,
    md,
    lausanne_area_uuids
)

save_data_file_if_different(DATA_FOLDER,'datasets',[ds], f'lausanne_mhl_photographs_dataset', RDEType.DATASET.value, is_dataset_obj=True)