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
df = pd.read_csv(list(Path('src').rglob('1857_commercial_guide_20*.csv'))[-1])
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