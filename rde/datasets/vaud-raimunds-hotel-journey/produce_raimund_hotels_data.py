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

DATA_FOLDER = 'data'
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(TM_UUID5_NS, DS_SLUG))
DS_OBJ = (DS_SLUG, DS_UUID)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))

area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

gdf = gpd.read_file('src/hotels.geojson')
from datetime import datetime
def date_parser(date_field:str) -> tuple[str, str]:
    lines = date_field.split(',')
    fl = lines[0]
    first_date = datetime(year = 2000+int(fl[-2:]), month = int(fl.split('.')[1]), day = int(fl.split('.')[0]))
    lv = lines[-1].split('/')[-1]
    last_date = datetime.strptime(lv, '%d.%m.%y')
    return (first_date.isoformat(), last_date.replace(hour=23, minute=59, second=59).isoformat())


gdf['start_time'], gdf['end_time'] = zip(*gdf['dates'].apply(date_parser))
gdf['night_stays'] = gdf['dates'].apply(lambda dates: len(dates.split('/')) - 1)
tqdm.pandas(desc="Generating obs uuid")
gdf['obs_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['photo_name'], ad_hoc_seed='obs'), axis=1)
tqdm.pandas(desc="Generating hr uuid")
gdf['hr_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['photo_name'], ad_hoc_seed='hr'), axis=1)

tpe='hotel'

obs = [produce_obs_obj(
    v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, tpe, v.geometry, None
) for _,v in gdf.iterrows()]

gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')

QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, "observations", gdf_obs, f'raimund_hotels_obs', RDEType.OBS.value)
df_wh = pd.read_csv('src/images_width_height.csv')


from utils.iiif import *
# Generating the IIIF manifests
df_wh['image_fp'] = df_wh['filename'].apply(lambda v: 'lausanne/raimund_hotels/'+v)
df = gdf.merge(df_wh, left_on='photo_name', right_on='filename')
man_list = {}
for i, row in tqdm(df.iterrows(), total=len(df), desc="Generating IIIF manifests"):
    manifest_uuid = make_uuid_from_row_selection(TM_UUID5_NS, row, ['filename'], ad_hoc_seed='hotel_photo_manifest')
    width, height = row['width'], row['height']
    page_obj = generate_page_object(
        TM_UUID5_NS,
        DS_UUID,
        0,
        manifest_uuid,
        row['name'],
        row['image_fp'],
        row['media_type'],
        height,
        width,
        'en',
        metadata=[[row['hr_uuid'], row['photo_comment_en']]])
    man = generate_manifest_object(TM_UUID5_NS, manifest_uuid, {'en':[row['photo_comment_en']], 'de': [row['photo_comment_de']]}, 'fr', [page_obj])
    with open(f'data/iiif/manifests/{manifest_uuid}.json', 'w') as f:
        f.write(json.dumps(man, indent=2, ensure_ascii=False))
    man_list[manifest_uuid] = ({"en":[row['photo_comment_en']]}, page_obj)
    
# generating the collection
collection_uuid = str(uuid.uuid5(TM_UUID5_NS, f'{DS_SLUG}_collection'))
collection_obj = generate_collection_manifest(
    collection_uuid,
    {'en': ['Raimund Journey - Hotels'], "fr": ["Voyage de Raimund - Hôtels"], "de": ["Raimunds Reise - Hotels"], "it": ["Viaggio di Raimund - Hotel"]},
    man_list)
with open(f'data/iiif/collections/{collection_uuid}.json', 'w') as f:
    f.write(json.dumps(collection_obj, indent=2, ensure_ascii=False))
# HR RDE Production
# 1 to 1 relationship 
hr_obs_df = gdf[['obs_uuid', 'hr_uuid']].groupby('hr_uuid').agg(list)
hr_df = gdf.drop(columns=['geometry', 'obs_uuid']).set_index('hr_uuid')
hr_df['obs_uuid'] = hr_obs_df['obs_uuid']
hr_df = hr_df.reset_index()

tpe = 'hotel'


recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                   [[r.obs_uuid[0], 'Monument']],\
                       (r.start_time, r.end_time),\
                       tpe, \
                   r.drop(labels = ['hr_uuid', 'obs_uuid', 'start_time', 'end_time']).to_dict(),
                   None,
                   'm'
                   ).to_dict(flatten_metadata=False) \
                   for _, r in hr_df.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'raimund_hotels_hrs', RDEType.HR.value)

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
    area_uuids
)

save_data_file_if_different(DATA_FOLDER,'datasets',[ds], f'raimund_hotel_dataset', RDEType.DATASET.value, is_dataset_obj=True)