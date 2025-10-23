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

# some pictures could not be downloaded. Removing them from the dataset
with open('src/404_images.txt') as f:
    exclude_ids = f.read().splitlines()

df = pd.read_json('src/dresden_4d_data.json')
print(len(df))
df = df[~df['id'].isin(exclude_ids)]
print(len(df))

df.rename(columns={'date': 'date_obj'}, inplace=True)
df['geometry'] = df['camera'].apply(lambda v: Point(v['longitude'], v['latitude']))

# this line shows that there is date object only for 2452 objects, missing it on 1185 object. Defaulting to max and min date for now.
df['date_obj'].apply(lambda d: d.keys()).value_counts()
min_date = df['date_obj'].apply(lambda d: dt.strptime(d['from'], '%Y-%m-%d').isoformat() if 'from' in d else dt.now().isoformat()).min()
max_date = df['date_obj'].apply(lambda d: dt.strptime(d['to'], '%Y-%m-%d').isoformat() if 'to' in d else min_date).max()
df['start_time'] = df['date_obj'].apply(lambda d: dt.strptime(d['from'], '%Y-%m-%d').isoformat() if 'from' in d else min_date) 
df['end_time'] = df['date_obj'].apply(lambda d: dt.strptime(d['to'], '%Y-%m-%d').replace(hour=23, minute=59, second=59).isoformat() if 'to' in d else max_date)
gdf = gpd.GeoDataFrame(df).set_geometry('geometry')

tqdm.pandas(desc="Generating obs uuid")
gdf['obs_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['id'], ad_hoc_seed='obs'), axis=1)
tqdm.pandas(desc="Generating hr uuid")
gdf['hr_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['id'], ad_hoc_seed='hr'), axis=1)
tqdm.pandas(desc="Generating poi uuid")
gdf['poi_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['geometry']), axis=1)

# Generating Obs RDE
tpe='picture'

obs = [produce_obs_obj(
    v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, tpe, v.geometry, None, v.poi_uuid
) for _,v in gdf.iterrows()]

gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')

QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, "observations", gdf_obs, f'dresden_obs', RDE.OBS.value)

# Generate PoI RDE
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v.poi_uuid, v.geometry[0], v.obs_uuid) for _, v in gdf.groupby('poi_uuid').agg(list).reset_index().iterrows()])
gdf_poi = gdf_poi.set_geometry('coordinate').set_crs('EPSG:4326')

QA_check_uuid_are_unique(gdf_poi.reset_index())
QA_check_unique_uuid_in_uuid_array(gdf_poi, 'represents')
save_data_file_if_different(DATA_FOLDER, 'points_of_interest', gdf_poi, f'dresden_pois', RDE.POI.value)


# HR RDE Production
# 1 to 1 relationship 
hr_obs_df = gdf[['obs_uuid', 'hr_uuid']].groupby('hr_uuid').agg(list)
hr_df = gdf.drop(columns=['id', 'poi_uuid', 'geometry', 'obs_uuid']).set_index('hr_uuid')
hr_df['obs_uuid'] = hr_obs_df['obs_uuid']
hr_df = hr_df.reset_index()

tpe = 'picture'

drop_cols = [ 'file', 'restrictedAccess', 'date_obj', 'camera', 'spatialStatus',
             'vrcity_useAsTextureFrom', 'vrcity_useAsTextureTo', 'vrcity_projectionDistance',
              'annotationsAvailable', 'pending', 'needsValidation', 'declined', 
              'uploadedBy', 'editedBy']
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                   [[r.obs_uuid[0], 'title']],\
                       (r.start_time, r.end_time),\
                       tpe, \
                   r.drop(labels = ['hr_uuid', 'obs_uuid', 'start_time', 'end_time'] + drop_cols).to_dict(),
                   None,
                   'm'
                   ) \
                   for _, r in hr_df.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'dresden_hrs', RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)

QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')


from utils.iiif import *


particles = [
    '_elb_',
    '_df_',
    '_tu_',
    '_b_'
]
def extract_image_name_from_id(image_id):
    '''
    Example: 
    
    rJ5Ttp3SM_df_bika100_0000745_motiv.jpg => df_bika100_0000745_motiv.jpg
    '''
    # pesky excpetion...
    if image_id == 'n4-AEV02P2_Frauenkirche_2.jpg':
        return 'Frauenkirche_2.jpg'
    if image_id == 'oZdXlelHb_pVAdwAEwV2F8Bq-Y79-EVw-0.jpg':
        return 'pVAdwAEwV2F8Bq-Y79-EVw-0.jpg'
    if image_id == 'GQY5WxrLD_pVAdwAEwV2F8Bq-Y79-EVw-120.jpg':
        return 'pVAdwAEwV2F8Bq-Y79-EVw-120.jpg'
    if image_id == '6GCTvlgxW_pVAdwAEwV2F8Bq-Y79-EVw-240.jpg':
        return 'pVAdwAEwV2F8Bq-Y79-EVw-240.jpg'
    if image_id == 'r4iVpFcBk_R01qJLpOaxBCEQxmW2fpMg-0.jpg':
        return 'R01qJLpOaxBCEQxmW2fpMg-0.jpg'
    if image_id == 'EbT8P3itT_R01qJLpOaxBCEQxmW2fpMg-120.jpg':
        return 'R01qJLpOaxBCEQxmW2fpMg-120.jpg'
    if image_id == 'vpJmmMwzq_R01qJLpOaxBCEQxmW2fpMg-240.jpg':
        return 'R01qJLpOaxBCEQxmW2fpMg-240.jpg'
    if image_id == 'ojq_Ygoa__Visualisierung_Kulturpalast_Au_enansicht__Copyright_gmp_Architekten.jpg':
        return 'Visualisierung_Kulturpalast_Au_enansicht__Copyright_gmp_Architekten.jpg'
    if image_id == 'RMAVEX-dv_photo.jpg':
        return 'photo.jpg'

    if 'YsvzEFUMgTI' in image_id:
        return image_id.split('_')[-1]
    
    if 'Vaak' in image_id:
        return 'Vaak_'+image_id.split('_')[-1]

    particle = None
    for p in particles:
        if p in image_id:
            particle = p
            break
    if particle is None:
        raise Exception(f"Unexpected image_id format: {image_id}")
    splits = image_id.split(particle)
    if len(splits) != 2:
        raise Exception(f"Unexpected image_id format: {image_id}")
    _, post = splits
    return particle[1:] + post

# Generating the IIIF manifests

img_base = 'dresden/4d_browser/{filename}'
man_list = {}
for i, row in tqdm(gdf.iterrows(), total=len(df), desc="Generating IIIF manifests"):
    file_obj = row['file']
    filename = extract_image_name_from_id(row['id'])
    img_path = img_base.format(filename=filename)
    manifest_uuid = make_uuid_from_row_selection(TM_UUID5_NS, row, ['id'], ad_hoc_seed='manifest')
    original_source = 'https://4dbrowser.org/data/' + file_obj['path'] + filename
    width, height = file_obj['width'], file_obj['height']
    page_obj = generate_page_object(
        TM_UUID5_NS,
        DS_UUID,
        0,
        manifest_uuid,
        row['title'],
        img_path,
        "image/jpeg",
        height,
        width,
        'en',
        metadata=[[row['hr_uuid'], row['title']]],
        external_resource=original_source)
    man = generate_manifest_object(TM_UUID5_NS, manifest_uuid, {'en':[row['title']]},'en', [page_obj])
    with open(f'data/iiif/manifests/{manifest_uuid}.json', 'w') as f:
        f.write(json.dumps(man, indent=2, ensure_ascii=False))
    man_list[manifest_uuid] = ({"en":[row['title']]}, page_obj)
    
# generating the collection
collection_uuid = str(uuid.uuid5(TM_UUID5_NS, f'{DS_SLUG}_collection'))
collection_obj = generate_collection_manifest(
    collection_uuid,
    {'en': ['Geolocated pictures of Dresden, Germany. Data retrieved from 4dbrowser.org.']},
    man_list)
with open(f'data/iiif/collections/{collection_uuid}.json', 'w') as f:
    f.write(json.dumps(collection_obj, indent=2, ensure_ascii=False))

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
    (min_date, max_date),
    0,
    ds_conf,
    [dresden_area_uuid],
    publish_obj=(CONF['doi'], CONF['github_link'])
)

save_data_file_if_different(DATA_FOLDER,'datasets',[ds], f'dresden_dataset', RDE.DATASET.value, is_dataset_obj=True)