import uuid
import pandas as pd
import geopandas as gpd
from datetime import datetime as dt
import os
import sys
import json
import numpy as np 
from tqdm import tqdm
# to have progress bar in the notebook
tqdm.pandas()
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

gpd.options.io_engine = "pyogrio"

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# aribtrary namespace, just to generate reproducible UUIDv5 from the data of this dataset.
VTM_SN_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'] )


DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_SN_UUID5_NS, DS_SLUG))

DS_OBJ = (DS_UUID, DS_SLUG)
DATA_FOLDER = 'data'
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))

venice_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])
sn_layer_uuid = get_layer_uuid(get_filepath_like('../../maps/venice-1808-sommarioni/layers', 'json'), 'street')

# Geometry RDE Production
gdf = gpd.read_file('src/1808_TOPONOMASTICA.shp')
gdf = gdf[~gdf.geometry.isna()] # for now.
gdf['NAME'] = gdf['NAME'].str.replace('_', ' ') 
# fixing the typo in the column
gdf['length'] = gdf['lenght']
gdf['length'] = gdf['length'].apply(lambda s: str(s) + 'm' if not pd.isna(s) else s)

# I have no idea what the id column is for, so dropping it for the moment.
gdf = gdf.drop(columns=['lenght', 'id']).reset_index()
gdf['start_time'] = pd.Series(data = [TR_OBJ[0]] * len(gdf), name='start_time')
gdf['end_time'] = pd.Series(data = [TR_OBJ[1]] * len(gdf), name='end_time')

tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.apply(lambda r: make_uuid_from_row_selection(VTM_SN_UUID5_NS, r, ['geometry']), axis=1)
gdf['rde_type'] = "geometry"
gdf['layer_uuid'] = sn_layer_uuid
gdf = gdf.set_geometry('geometry').to_crs('EPSG:4326')
QA_check_uuid_are_unique(gdf)
# "NAME" was removed for consistency with the other datasets.
save_data_file_if_different(DATA_FOLDER, 'geometries', gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']], '1808_street_network_geometries', RDE.GEOM.value)
gdf['coordinate'] = gdf['geometry'].apply(lambda v: v.centroid)
tqdm.pandas(desc="Generating obs uuid")
gdf['obs_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_SN_UUID5_NS, r, ['coordinate']), axis=1)
tqdm.pandas(desc="Generating hr uuid")
gdf['hr_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_SN_UUID5_NS, r, ['index']), axis = 1)
tqdm.pandas(desc="Generating poi uuid")
gdf['poi_uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_SN_UUID5_NS, r, ['obs_uuid']), axis = 1)

# HR RDE Production
tpe = "street toponym"
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                   [[r.obs_uuid, 'NAME']],\
                   TR_OBJ,\
                   tpe,\
                   r[['NAME', 'length']].to_dict()) \
                   for _, r in gdf.iterrows()]

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')
save_data_file_if_different(DATA_FOLDER, 'historical_records',  recs, f'1808_street_network_hrs', RDE.HR.value)


# Obs RDE Production
tpe = "street toponym"
gpd.options.io_engine = "pyogrio"

gdf_obs = gpd.GeoDataFrame([produce_obs_obj(v.obs_uuid, TR_OBJ, DS_UUID, v.hr_uuid,tpe, v.coordinate,  [v.uuid], v.poi_uuid) for _, v in gdf.iterrows()])
gdf_obs = gdf_obs.set_geometry('coordinate').set_index('uuid').set_crs('EPSG:4326')
QA_check_uuid_are_unique(gdf_obs.reset_index())
QA_check_unique_uuid_in_uuid_array(gdf_obs, 'has_geometry')
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, f'1808_street_network_obs', RDE.OBS.value)

# PoI RDE Production
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v.poi_uuid, v.coordinate, [v.obs_uuid] ) for _, v in gdf.iterrows()])
gdf_poi = gdf_poi.set_geometry('coordinate').set_index('uuid').set_crs('EPSG:4326')
QA_check_uuid_are_unique(gdf_poi.reset_index())
QA_check_unique_uuid_in_uuid_array(gdf_poi, 'represents')
save_data_file_if_different(DATA_FOLDER, 'points_of_interest', gdf_poi, f'1808_street_network_pois', RDE.POI.value)

# Dataset Object Production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

# the columns of the df needs to be ordered the way we want them to be ordered then in the configuration file.
labels = CONF['labels']
order = labels.keys()
ds_conf = produce_configuration_file_from_metadata_df(
    VTM_SN_UUID5_NS,
    gdf[order], 
    CONF['indexed'], 
    CONF['short_display'],
    CONF['hidden'],
    {},
    CONF['tagged_fields'],
    labels,
    CONF['main_label'],
    CONF['sub_label']
)

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    '1.0',
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
save_data_file_if_different(DATA_FOLDER, 'dataset', [ds], f'1808_street_network_dataset', RDE.DATASET.value, is_dataset_obj=True)