import uuid
import pandas as pd
import geopandas as gpd
from datetime import datetime as dt
import os
import sys
from tqdm import tqdm
from shapely import wkt
# to have progress bar in the notebook
tqdm.pandas()

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils import iiif
from utils.rde import RDE
from pathlib import Path

gpd.options.io_engine = "pyogrio"

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# arbitrary namespace, just to generate reproducible UUIDv5 from the data of this dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DATA_FOLDER = 'data'
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))
DS_OBJ = (DS_UUID, DS_SLUG)

formatted_begin = datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM'])
formatted_end = datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True)
TR_OBJ = (formatted_begin, formatted_end)
df = pd.read_csv(list(Path('src').rglob('1857_commercial_guide_with_pages_20*.csv'))[-1])
# removing points that could not be located
df = df[df.geometry.notna()]
# fix NaN being serialized as literal in JSON alongside "null"
df = df.replace({np.nan: None})

# creating ad-hoc full name field
df['name'] = df['FIRST_N'].str.replace(',', '') + ' ' + df['LAST_N']

venice_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])
df['geometry'] = df['geometry'].apply(wkt.loads)
gdf = gpd.GeoDataFrame(df).set_geometry('geometry')
gdf = gdf.set_crs('EPSG:4326')

tqdm.pandas(desc="Generating obs uuid")
gdf['obs_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['index'], ad_hoc_seed='obs'), axis=1)
tqdm.pandas(desc="Generating hr uuid")
gdf['hr_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['index'], ad_hoc_seed='hr'), axis=1)
tqdm.pandas(desc="Generating poi uuid")
gdf['poi_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['geometry']), axis=1)

# Produce HR RDE
tpe = 'commerce location'
obs = [produce_obs_obj(r.obs_uuid, TR_OBJ, DS_UUID, r.hr_uuid, tpe, r.geometry, None, r.poi_uuid) for _,r in gdf.iterrows()]
gdf_obs = gpd.GeoDataFrame(obs).set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')

QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, '1857_gc_obs', RDE.OBS.value)


# Produce PoI RDE
# for the one to many relationship with the obs 
df_poi = gdf[['poi_uuid', 'obs_uuid', 'geometry']].groupby('poi_uuid').agg(list)
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v.poi_uuid, v.geometry[0], v.obs_uuid) for _,v in df_poi.reset_index().iterrows()])
gdf_poi = gdf_poi.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')

QA_check_uuid_are_unique(gdf_poi.reset_index())
QA_check_unique_uuid_in_uuid_array(gdf_poi, 'represents')
save_data_file_if_different(DATA_FOLDER, 'points_of_interest', gdf_poi,  f'1857_gc_poi', RDE.POI.value)

# Produce HR RDE
exclude_hr_labels = {
    'geometry', 
    'poi_uuid',
    'obs_uuid',
    'hr_uuid',
    'geometry'
}
hr_metadata_cols = list(set(df.columns).difference(exclude_hr_labels))
tpe = 'commercial registry'
gdf['name'] = gdf['name'].fillna('No name registered')
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r.obs_uuid, 'place']],\
                       TR_OBJ,\
                       tpe,\
                   r[hr_metadata_cols].to_dict()) \
                   for _, r in gdf.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'1857_gc_hrs', RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)

QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')

IMG_LOC_PREFIX = 'venice/commercial_guides/1857/pages'

df_pages = pd.read_csv('src/1857_img_wh.csv')
df_pages['page_num'] = df_pages['filename'].apply(lambda x: int(x.replace('_', '').replace('.jpg', '').replace('/', '')))
df_pages.sort_values(by='page_num', inplace=True)

manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'manifest_{DS_SLUG}'))
df_pages['page_obj'] = None
for i, x in df_pages.iterrows():
    df_pages.at[i, 'page_obj'] = iiif.generate_page_object(VTM_UUID5_NS, DS_SLUG, x['page_num'], manifest_uid, \
                                                                'pg. '+str(x['page_num']), IMG_LOC_PREFIX+x['filename'],\
                                                                x['media_type'], x['width'], x['height'], 'it')
    
df_pages['canvas_id'] = df_pages['page_obj'].apply(lambda x: x['id'])
df_of_hr['page'] = df_of_hr['annotated_content'].apply(lambda v: v['PAGE_NUM'])
page_to_canvas = df_pages[['page_num', 'canvas_id']].set_index('page_num').to_dict()['canvas_id']
# preparing the data to insert in the canvas of the manifest.
df_iiif_links = df_of_hr[df_of_hr['page'].notnull()]


collection = {}
registry_label = {
                    "en": [f'Commercial guide of Venice from 1857'],
                    "it": [f'Guida commerciale di Venezia del 1857'],
                    "fr": [f'Annuaire commercial de Venise de 1857']
                }

collection[manifest_uid] = (registry_label, df_pages['page_obj'].tolist()[0])

collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
with open(f'data/iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest(collection_manifest_uid, registry_label, collection), f, indent=2, ensure_ascii=False)

col_in_order = ['LAST_N', 'FIRST_N', 'PER_GRP', 'PER_COMPL', 'LOC_PAR', 'LOC_STR', 'NUM', 'LOC_COMPL']

def cg_1857_metadata_object_to_string_representation(metadata: dict) -> str:
    quick_check = lambda x: str(x) if type(x) is int else x if type(x) is str and x.lower() != 'nan' and len(x) > 0 else ''
    vals = [quick_check(metadata.get(v, '')) for v in col_in_order]
    return ' '.join([v for v in vals if len(v) > 0])

df_iiif_links['iiif_display_string'] = df_iiif_links['annotated_content'].apply(cg_1857_metadata_object_to_string_representation)
df_iiif_links['iiif_metadata_obj'] = df_iiif_links.apply(lambda x: (x['uuid'], x['iiif_display_string']), axis=1)
# applying the page to canvas mapping.
df_iiif_links['canvas_id'] = df_iiif_links['page'].apply(lambda v: page_to_canvas.get(v, None))
# # the hr_uuid is missing. 
iiif_links = df_iiif_links[['canvas_id', 'iiif_metadata_obj']].groupby('canvas_id', sort=False).agg(list).reset_index().set_index('canvas_id')['iiif_metadata_obj'].to_dict()
df_pages['page_obj'] = df_pages['page_obj'].apply(lambda x: dict(x, metadata = iiif_links.get(x['id'], '')))

with open(f'data/iiif/manifests/{manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_manifest_object(VTM_UUID5_NS, manifest_uid, registry_label, 'en', df_pages['page_obj'].tolist()), f, indent=2, ensure_ascii=False)


#Produce Datset object
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

labels = CONF['labels']
filtered_df = gdf.drop(columns=exclude_hr_labels)
# the columns of the df needs to be ordered the way we want them to be ordered then in the configuration file.
labels = CONF['labels']
order = labels.keys()
main_label = "${name}"
sub_label = "${profession_eng}"
ds_conf = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS, 
    filtered_df[order],
    CONF["indexed"],
    CONF["short_display"],
    CONF["hidden"],
    {},
    CONF["tagged_fields"],
    CONF["labels"], 
    CONF["main_label"],
    CONF["sub_label"]
)

ds = produce_dataset_obj(DS_UUID,
    DS_SLUG,
    "1.0",
    CONF['name'],
    CONF['description'],
    CONF['paradata'],
    [],
    TR_OBJ,
    0,
    ds_conf,
    [venice_area_uuid],
    publish_obj=(CONF['doi'], CONF['github_link'])
)

save_data_file_if_different(DATA_FOLDER, 'datasets', [ds], '1857_gc_dataset', RDE.DATASET.value, is_dataset_obj=True)