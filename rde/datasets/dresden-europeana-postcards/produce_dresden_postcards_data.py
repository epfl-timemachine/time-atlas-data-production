import uuid
import pandas as pd
import geopandas as gpd
from datetime import datetime as dt
import os
import sys
from tqdm import tqdm
from ast import literal_eval
from shapely import Point
# to have progress bar in the notebook
tqdm.pandas()

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from pathlib import Path

gpd.options.io_engine = "pyogrio"

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# arbitrary namespace, just to generate reproducible UUIDv5 from the data of this dataset.
TM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])

DATA_FOLDER = 'data'
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(TM_UUID5_NS, DS_SLUG))
DS_OBJ = (DS_SLUG, DS_UUID)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))

dresden_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

df = pd.read_csv('src/dresden_347_20250602.csv')
df['lat_lon'] = df['lat_lon'].apply(lambda v: literal_eval(v))
df['geometry'] = df['lat_lon'].apply(lambda v: Point(v[1], v[0]))
gdf = gpd.GeoDataFrame(df.drop('lat_lon', axis=1)).set_geometry('geometry')
gdf['date'] = gdf['date'].apply(lambda v: str(v)[:4]) # keep only the year
gdf = gdf.set_crs('EPSG:4326').reset_index()

tqdm.pandas(desc="Generating obs uuid")
gdf['obs_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['index']), axis=1)
tqdm.pandas(desc="Generating hr uuid")
gdf['hr_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['Image Name']), axis=1)

# Generating Obs RDE
gdf['dt_time'] = gdf['date'].apply(lambda v: dt.strptime(v, '%Y'))
gdf['start_time'], gdf['end_time']= gdf['dt_time'].apply(lambda v: v.isoformat()), gdf['dt_time'].apply(lambda v: v.replace(month=12, day=31, hour=23, minute=59, second=59).isoformat())
gdf.drop(columns=['dt_time'], inplace=True)
tpe='monument'

obs = [produce_obs_obj(
    v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, tpe, v.geometry, None
) for _,v in gdf.iterrows()]

gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')

QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, "observations", gdf_obs, f'dresden_obs', RDE.OBS.value)

from utils.iiif import *
# Generating the IIIF manifests
gdf['image_fp'] = df['image_path'].apply(lambda v: v.replace('to_iiif/dresden', 'dresden/europeana_postcards'))
man_list = {}
for i, row in tqdm(gdf.iterrows(), total=len(df), desc="Generating IIIF manifests"):
    manifest_uuid = make_uuid_from_row_selection(TM_UUID5_NS, row, ['Image Name'], ad_hoc_seed='postcard_manifest')
    width, height = literal_eval(row['image_size'])
    page_obj = generate_page_object(
        TM_UUID5_NS,
        DS_UUID,
        0,
        manifest_uuid,
        row['Image Name'],
        row['image_fp'],
        row['media_type'],
        height,
        width,
        'en',
        metadata=[[row['hr_uuid'], row['description']]],
        external_resource=row['landin_page'],)
    man = generate_manifest_object(TM_UUID5_NS, manifest_uuid, {'en':[row['description']]},'en', [page_obj])
    with open(f'data/iiif/manifests/{manifest_uuid}.json', 'w') as f:
        f.write(json.dumps(man, indent=2, ensure_ascii=False))
    man_list[manifest_uuid] = ({"en":[row['description']]}, page_obj)
    
# generating the collection
collection_uuid = str(uuid.uuid5(TM_UUID5_NS, f'{DS_SLUG}_collection'))
collection_obj = generate_collection_manifest(
    collection_uuid,
    {'en': ['Geolocated postcards from Dresden, Germany. Data retrieved from Europeana.']},
    man_list)
with open(f'data/iiif/collections/{collection_uuid}.json', 'w') as f:
    f.write(json.dumps(collection_obj, indent=2, ensure_ascii=False))
# HR RDE Production
# 1 to 1 relationship 
hr_obs_df = gdf[['obs_uuid', 'hr_uuid']].groupby('hr_uuid').agg(list)
hr_df = gdf.drop(columns=['index', 'geometry', 'obs_uuid']).set_index('hr_uuid')
hr_df['obs_uuid'] = hr_obs_df['obs_uuid']
hr_df = hr_df.reset_index()

tpe = 'postcard'

drop_cols = ['external_links', 'iiif_manifest', 'image', 'rights_attribution', 'thumbnail', 'landin_page', 'image_size', 'media_type', 'image_path', 'record', 'image_fp']
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                   [[r.obs_uuid[0], 'Monument']],\
                       (r.start_time, r.end_time),\
                       tpe, \
                   r.drop(labels = ['hr_uuid', 'obs_uuid', 'start_time', 'end_time'] + drop_cols).to_dict(),
                   r['rights_attribution'],
                   'a'
                   ) \
                   for _, r in hr_df.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'dresden_hrs', RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)

QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')

# Dataset RDE Object production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
filtered_df = hr_df.drop(columns=['hr_uuid', 'obs_uuid'])
labels = CONF['labels']
order = labels.keys()
ds_conf = produce_configuration_file_from_metadata_df(
    TM_UUID5_NS,
    filtered_df[order],
    CONF['indexed'],
    CONF['short_display'], 
    CONF['hidden'],
    {},
    CONF['tagged_fields'],
    labels,
    CONF['main_label'],
    CONF['sub_label'],
    True,
    True
)

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    "1.0",
    CONF['name'],
    CONF['description'],
    CONF['paradata'],
    [collection_uuid],
    TR_OBJ,
    0,
    ds_conf,
    [dresden_area_uuid],
    publish_obj=(CONF['doi'], CONF['github_link'])
)

save_data_file_if_different(DATA_FOLDER,'datasets',[ds], f'dresden_dataset', RDE.DATASET.value, is_dataset_obj=True)