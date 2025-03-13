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

# to have progress bar in the notebook
tqdm.pandas()
with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE


DATA_SRC_PATH = Path(join(parent_dir, 'data-lausanne/1888-cadastre-renove'))


# aribtrary namespace, just to generate reproducible UUIDv5 from the entries of the dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))

cadaster_layer_uuid = get_layer_uuid(get_filepath_like('../../maps/lausanne-1888-cadastre-renove/layers', 'json'), 'vector')
lausanne_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

DS_OBJ = (DS_UUID, DS_SLUG)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))
DATA_FOLDER = 'data'

# Geometry RDE production
geometries_fp = get_filepath_like(os.path.join(DATA_SRC_PATH, "lausanne-1888-cadastre-renove-geometries-"), 'geojson')
# sample for testing uuid_gen
gdf = gpd.read_file(geometries_fp)
gdf['start_time'] = pd.Series(data = [TR_OBJ[0]] * len(gdf), name='start_time')
gdf['end_time'] = pd.Series(data = [TR_OBJ[1]] * len(gdf), name='end_time')

tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['geom_id']), axis=1)
gdf['layer_uuid'] = cadaster_layer_uuid
gdf['rde_type'] = "geometry"
QA_check_uuid_are_unique(gdf)

if not QA_check_all_geometries_are_valid(gdf, raise_exception=False):
    from shapely.validation import make_valid
    gdf['geometry'] = gdf['geometry'].apply(lambda g: g if g.is_valid else make_valid(g))
    QA_check_all_geometries_are_valid(gdf)

geom_shorthand = 'lausanne_1888_cadastre_renove_geometries'
# "parcel_type" was removed for consistency with the other datasets. 
save_data_file_if_different(DATA_FOLDER, 'geometries', gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']], geom_shorthand, RDE.GEOM.value)

txt_fp = get_filepath_like(os.path.join(DATA_SRC_PATH, "lausanne-1888-cadastre-renove-registre-"), 'csv')
dfs = pd.read_csv(txt_fp)


point_fp = get_filepath_like(os.path.join(DATA_SRC_PATH, "lausanne-1888-cadastre-renove-points-"), 'geojson')
point_gdf = gpd.read_file(point_fp).drop(columns=['parcel_id', 'folio'])

geom_id_to_uuid = {str(k):v for k,v  in gdf.set_index('geom_id')['uuid'].to_dict().items()}
point_gdf['geom_uuid'] = point_gdf['geom_id'].map(geom_id_to_uuid)
point_gdf = point_gdf[point_gdf['merge_id'].isin(dfs['merge_id'])]

tqdm.pandas(desc="Generating uuid for hr")
dfs['hr_uuid'] = dfs.progress_apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['*']), axis=1)