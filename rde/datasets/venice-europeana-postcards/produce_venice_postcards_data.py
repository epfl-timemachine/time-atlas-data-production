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
from timeatlas.data_modeling import *
from timeatlas.RDEModel import RDEType
from pathlib import Path

gpd.options.io_engine = "pyogrio"

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# arbitrary namespace, just to generate reproducible UUIDv5 from the data of this dataset.
TM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])

DATA_FOLDER = ''
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(TM_UUID5_NS, DS_SLUG))
DS_OBJ = (DS_SLUG, DS_UUID)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))

venice_area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

df = pd.read_csv('src/venice_67_20250602.csv')
df['lat_lon'] = df['lat_lon'].apply(lambda v: literal_eval(v))
df['geometry'] = df['lat_lon'].apply(lambda v: Point(v[1], v[0]))

def start_end_date_from_venice_postcards_date_value(date_value):
    if pd.isna(date_value):
        return TR_OBJ
    begin = None
    end = None
    if '[' in date_value and ']' in date_value:
        date_value = literal_eval(date_value)
    if isinstance(date_value, tuple):
        begin = dt.strptime(date_value[0][0], '%Y-%m-%d')
        end = dt.strptime(date_value[1][0], '%Y-%m-%d')
    elif isinstance(date_value, str):
        if date_value.endswith('XX'):
            # if the date ends with XX, it means that the exact date is not known, so we assume the whole year
            year = int(date_value[:-2])*100
            begin = dt(year, 1, 1)
            end = dt(year+99, 12, 31, 23, 59, 59)
        else:
            # otherwise, we assume the date is a year
            year = int(date_value)
            begin = dt(year, 1, 1)
            end = dt(year, 12, 31, 23, 59, 59)

    return (begin.isoformat(), end.isoformat())

df['start_time'], df['end_time']= zip(*df['date'].apply(start_end_date_from_venice_postcards_date_value))

gdf = gpd.GeoDataFrame(df.drop('lat_lon', axis=1)).set_geometry('geometry')
gdf = gdf.set_crs('EPSG:4326').reset_index()

tqdm.pandas(desc="Generating obs uuid")
gdf['obs_uuid'] = gdf.apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['index']), axis=1)
tqdm.pandas(desc="Generating hr uuid")
gdf['hr_uuid'] = gdf.apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['Image Name']), axis=1)

tpe='monument'

# Generating Obs RDE
obs = [produce_obs_obj(
    v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, tpe, v.geometry, None
) for _,v in gdf.iterrows()]

gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_index('id').set_crs('EPSG:4326')

QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, "observations", gdf_obs, f'venice_postcards_obs', RDEType.OBS.value)

from utils.iiif import *
# Generating the IIIF manifests
gdf['image_fp'] = df['image_path'].apply(lambda v: v.replace('to_iiif/venice', 'venice/europeana_postcards'))
man_list = {}
create_iiif_directory_if_not_exists()
for i, row in tqdm(gdf.iterrows(), total=len(df), desc="Generating IIIF manifests"):
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
    with open(f'iiif/manifests/{manifest_uuid}.json', 'w') as f:
        f.write(json.dumps(man, indent=2, ensure_ascii=False))
    man_list[manifest_uuid] = ({"en":[description]}, page_obj)
    
# generating the collection
collection_uuid = str(uuid.uuid5(TM_UUID5_NS, f'{DS_SLUG}_collection'))
collection_obj = generate_collection_manifest(
    collection_uuid,
    {'en': ['Geolocated postcards from Venice, Italy. Data retrieved from Europeana.']},
    man_list)
with open(f'iiif/collections/{collection_uuid}.json', 'w') as f:
    f.write(json.dumps(collection_obj, indent=2, ensure_ascii=False))
# HR RDE Production
# 1 to 1 relationship 
hr_obs_df = gdf[['obs_uuid', 'hr_uuid']].groupby('hr_uuid').agg(list)
hr_df = gdf.drop(columns=['index', 'geometry', 'obs_uuid']).set_index('hr_uuid')
hr_df = hr_df.replace({np.nan: None})
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
                   ).to_dict(flatten_metadata=False) \
                   for _, r in hr_df.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'venice_postcards_hrs', RDEType.HR.value)

df_of_hr = pd.DataFrame(data = recs)

QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'has_observations')

# Dataset RDE Object production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
filtered_df = hr_df.drop(columns=['hr_uuid', 'obs_uuid'])
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
    venice_area_uuids
)

save_data_file_if_different(DATA_FOLDER,'datasets',[ds], f'venice_postcards_dataset', RDEType.DATASET.value, is_dataset_obj=True)