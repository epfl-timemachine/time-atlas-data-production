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

paris_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

df = pd.read_csv('src/paris_98_20250602.csv')

def format_single_date_elem(date_elem):
    if len(date_elem.split('-')) == 2:
        # If the date is in the format 'YYYY-MM', we assume it is the first day of the month
        return dt.strptime(date_elem, '%Y-%m')
    elif len(date_elem.split('-')) == 3:
        # If the date is in the format 'YYYY-MM-DD', we convert it to a datetime object
        return dt.strptime(date_elem, '%Y-%m-%d')
    else:
        # If the date is not in a recognized format, we return None
        return dt.strptime(date_elem, '%Y') if date_elem.isdigit() else None

# ugly but i lack the time to make it better
def start_end_date_from_paris_postcards_date_value(date_value):
    if pd.isna(date_value):
        return TR_OBJ
    begin = None
    end = None
    if '~' in date_value:
        # if the date is in the format of a range, we assume it is a tuple
        date_value = date_value.replace('~', '')
        year = int(date_value.strip())
        end = year + 10
        date_value = f"{year}/{end}"        
    if '[' in date_value and ']' in date_value:
        date_value = literal_eval(date_value)
    if '/' in date_value:
        # if the date is in the format of a range, we assume it is a tuple
        begin, end = date_value.split('/')
        begin = format_single_date_elem(begin.strip())
        end = format_single_date_elem(end.strip())
    elif isinstance(date_value, tuple):
        begin = dt.strptime(date_value[0][0], '%Y-%m-%d')
        end = dt.strptime(date_value[1][0], '%Y-%m-%d')
    elif isinstance(date_value, str):
        if date_value.endswith('XX'):
            # if the date ends with XX, it means that the exact date is not known, so we assume the whole year
            year = int(date_value[:-2])*100
            begin = dt(year, 1, 1)
            end = dt(year+99, 12, 31, 23, 59, 59)
        elif date_value.startswith('0'):
            # if the date starts with 0, it means that the exact date is not known, so we assume the whole year
            year = int(date_value[1:])*10
            begin = dt(year, 1, 1)
            end = dt(year+99, 12, 31, 23, 59, 59)
        elif not '-' in date_value:
            # otherwise, we assume the date is a year
            year = int(date_value)
            begin = dt(year, 1, 1)
            end = dt(year, 12, 31, 23, 59, 59)
        else:
            begin = format_single_date_elem(date_value)
            end = begin.replace(hour=23, minute=59, second=59, microsecond=999999)
    return (begin.isoformat(), end.isoformat())


df['Monuments_lat_lon'] = df['Monuments_lat_lon'].apply(literal_eval)
df['Monuments_wd_id'] = df['Monuments_wd_id'].apply(literal_eval)
df['Monuments'] = df['Monuments'].apply(literal_eval)

df['start_time'], df['end_time']= zip(*df['date'].apply(start_end_date_from_paris_postcards_date_value))
tqdm.pandas(desc="Generating hr uuid")
df['hr_uuid'] = df.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['Image Name']), axis=1)

def quick_uuid(hr_uuid:str, monument:str) -> str: 
    return str(uuid.uuid5(TM_UUID5_NS, f'{hr_uuid}-{monument}'))  

tqdm.pandas(desc="Generating obs uuid")
df['obs_data'] = df.progress_apply(lambda r: [(m,c, quick_uuid(r['hr_uuid'], m)) for m,c in zip(r['Monuments'], r['Monuments_lat_lon'])], axis=1)
df_obs = df[['obs_data', 'hr_uuid', 'start_time', 'end_time']].copy().explode('obs_data')
df_obs['lat_lon'], df_obs['obs_uuid'] = df_obs['obs_data'].apply(lambda x: x[1]), df_obs['obs_data'].apply(lambda x: x[2])
df_obs = df_obs.drop(columns=['obs_data'])
df_obs['lat_lon'] = df_obs['lat_lon'].apply(lambda v: literal_eval(v))
df_obs['geometry'] = df_obs['lat_lon'].apply(lambda v: Point(v[1], v[0]))
gdf = gpd.GeoDataFrame(df_obs.drop('lat_lon', axis=1)).set_geometry('geometry')
gdf = gdf.set_crs('EPSG:4326').reset_index()

tqdm.pandas(desc="Generating poi uuid")
gdf['poi_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['geometry']), axis=1)

tpe='monument'

# Generating Obs RDE
obs = [produce_obs_obj(
    v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, tpe, v.geometry, None, v.poi_uuid
) for _,v in gdf.iterrows()]

gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')

QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, "observations", gdf_obs, f'paris_postcards_obs', RDE.OBS.value)

# Generate PoI RDE
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v.poi_uuid, v.geometry[0], v.obs_uuid) for _, v in gdf.groupby('poi_uuid').agg(list).reset_index().iterrows()])
gdf_poi = gdf_poi.set_geometry('coordinate').set_crs('EPSG:4326')

QA_check_uuid_are_unique(gdf_poi.reset_index())
QA_check_unique_uuid_in_uuid_array(gdf_poi, 'represents')
save_data_file_if_different(DATA_FOLDER, 'pois', gdf_poi, f'paris_postcards_pois', RDE.POI.value)

from utils.iiif import *
# Generating the IIIF manifests
df['image_fp'] = df['image_path'].apply(lambda v: v.replace('to_iiif/paris', 'paris/europeana_postcards'))
man_list = {}
for i, row in tqdm(df.iterrows(), total=len(df), desc="Generating IIIF manifests"):
    manifest_uuid = make_uuid_from_row_selection(TM_UUID5_NS, row, ['Image Name'], ad_hoc_seed='postcard_manifest')
    width, height = literal_eval(row['image_size'])
    description = row['description'] if not pd.isna(row['description']) else row['Image Name'].replace('.jpg', '').replace('.jpeg', '')
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
        metadata=[[row['hr_uuid'], description]],
        external_resource=row['landin_page'],)
    man = generate_manifest_object(TM_UUID5_NS, manifest_uuid, {'en':[description]},'en', [page_obj])
    with open(f'data/iiif/manifests/{manifest_uuid}.json', 'w') as f:
        f.write(json.dumps(man, indent=2, ensure_ascii=False))
    man_list[manifest_uuid] = {"en":[description]}
    
# generating the collection
collection_uuid = str(uuid.uuid5(TM_UUID5_NS, f'{DS_SLUG}_collection'))
collection_obj = generate_collection_manifest(
    collection_uuid,
    {'en': ['Geolocated postcards from Paris, France. Data retrieved from Europeana.']},
    man_list)
with open(f'data/iiif/collections/{collection_uuid}.json', 'w') as f:
    f.write(json.dumps(collection_obj, indent=2, ensure_ascii=False))


drop_cols = ['external_links', 'iiif_manifest', 'image', 'thumbnail', 'landin_page', 'image_size', 'media_type', 'image_path', 'record', 'image_fp']
df_hr = df.copy().drop(columns=drop_cols)
df_hr['Monuments'] = df_hr.apply(lambda r: [f'{m}, ({wd})' for m, wd in zip(r['Monuments'], r['Monuments_wd_id'])], axis=1)
df_hr['obs_uuid'] = df_hr['obs_data'].apply(lambda x: [o[2] for o in x])
df_hr = df_hr.drop(columns=['obs_data', 'Monuments_wd_id', 'Monuments_lat_lon'])

df_hr = df_hr.replace({np.nan: None})
tpe = 'postcard'

recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                   [[v, 'Monuments'] for v in r.obs_uuid] ,\
                       (r.start_time, r.end_time),\
                       tpe, \
                   r.drop(labels = ['hr_uuid', 'obs_uuid', 'start_time', 'end_time', 'rights_attribution']).to_dict(),
                   r['rights_attribution'],
                   'a'
                   ) \
                   for _, r in df_hr.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'paris_postcards_hrs', RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)

QA_check_uuid_are_unique(df_of_hr)
# QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents') # disabled because of "Monuments" being the same field of origin for both obs uuuid.

# Dataset RDE Object production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
filtered_df = df_hr.drop(columns=['hr_uuid', 'obs_uuid'])
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
    [paris_area_uuid],
    publish_obj=(CONF['doi'], CONF['github_link'])
)

save_data_file_if_different(DATA_FOLDER,'datasets',[ds], f'paris_postcards_dataset', RDE.DATASET.value, is_dataset_obj=True)