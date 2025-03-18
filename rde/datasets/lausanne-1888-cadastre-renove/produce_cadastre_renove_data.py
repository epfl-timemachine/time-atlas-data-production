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
LTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(LTM_UUID5_NS, DS_SLUG))

cadaster_layer_uuid = get_layer_uuid(get_filepath_like('../../maps/lausanne-1888-cadastre-renove/layers', 'json'), 'vector')
lausanne_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

DS_OBJ = (DS_UUID, DS_SLUG)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))
DATA_FOLDER = 'data'

# Geometry RDE production
geometries_fp = get_filepath_like(os.path.join(DATA_SRC_PATH, "lausanne-1888-cadastre-renove-geometries-"), 'geojson')
# sample for testing uuid_gen
gdf = gpd.read_file(geometries_fp)
# this corresponds to geometry of id "2849", it it has a self intersecting segement that trnasform the geometry into a "geometrycolleciton" of multiple polygon and a single line string later. No parcel tied to it, so its fine, but to be fixed.
gdf = gdf[gdf.geom_id != 2849].copy()
# TODO: fix the geometry of id 2849 eventually.
gdf['start_time'] = TR_OBJ[0]
gdf['end_time'] = TR_OBJ[1]

tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(LTM_UUID5_NS, r, ['geom_id']), axis=1)
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

dfs.replace({np.nan: None}, inplace=True)
# because they hold no values
dfs.drop(columns=['cent', 'ares', 'articles', 'prix proportionnels par are de la commission cadastrale'], inplace=True)

point_fp = get_filepath_like(os.path.join(DATA_SRC_PATH, "lausanne-1888-cadastre-renove-points-"), 'geojson')
# reset index to use it as a seed for uuid 
point_gdf = gpd.read_file(point_fp).drop(columns=['parcel_id', 'folio']).reset_index()

geom_id_to_uuid = {str(k):v for k,v  in gdf.set_index('geom_id')['uuid'].to_dict().items()}
point_gdf['geom_uuid'] = point_gdf['geom_id'].map(geom_id_to_uuid)

# removing points that do not have an entry in the registry
point_gdf = point_gdf[point_gdf['merge_id'].isin(dfs['merge_id'])]

# and points that have no link to the cadastral sheets
dfs = dfs[dfs['merge_id'].isin(point_gdf['merge_id'])]
# TODO: investigate the missing entries. 

# as there can be multiple observations per hr, we need to generate a uuid for each of them here. 
merge_df = pd.merge(dfs, point_gdf, on='merge_id')[['*', 'index', 'merge_id']]
merge_df = merge_df.groupby('merge_id').agg(set).reset_index()

# below columns are just for the analysis of the cardinality of the relationship
merge_df['len_*'] = merge_df['*'].apply(len)
merge_df['len_index'] = merge_df['index'].apply(len)
# ON the cardinality:
# 1. 168 cases where there are multiples registry entry per "observation" => simple explosion of the parcels id (column named "*"") meaning deduplicatoin of the observation entry per registry entry
# 2. 674 cases where there are 2 observations per registry entry => taken by default with the cardinality of one to many between hr and obs

# only a single case of a many to many relationship. (2 registries to 2 observations) => exclude it for now as it is not clear how to handle it.
exclude_merged_id = merge_df[(merge_df['len_*'] > 1) & (merge_df['len_index'] > 1)].iloc[0]['merge_id']
dfs = dfs[dfs['merge_id'] != exclude_merged_id]
point_gdf = point_gdf[point_gdf['merge_id'] != exclude_merged_id]
merge_df = merge_df[merge_df['merge_id'] != exclude_merged_id]
merge_df = merge_df.explode('*', ignore_index=True)

def obs_uuid_and_point_id_gen(r: pd.Series) -> list[tuple[str, int]]:
    return [(str(uuid.uuid5(LTM_UUID5_NS, f"{r['*']}_{v}")), v) for v in r['index']]
    
tqdm.pandas(desc="Generating uuid for obs")
merge_df['obs_uuid_point_id'] = merge_df.progress_apply(obs_uuid_and_point_id_gen, axis=1)

tqdm.pandas(desc="Generating uuid for hr")
dfs['hr_uuid'] = dfs.progress_apply(lambda v: make_uuid_from_row_selection(LTM_UUID5_NS, v, ['*']), axis=1)

obs_uuid_to_point_id = dict(reduce(lambda a,b: a + b[0], merge_df[['obs_uuid_point_id']].values, []))
registry_id_to_obs_uuid = {k: [v[0] for v in l] for k,l in merge_df.set_index('*')['obs_uuid_point_id'].items()}
dfs['obs_uuid'] = dfs['*'].map(registry_id_to_obs_uuid)
obs_uuid_to_hr_uuid = dfs[['hr_uuid', 'obs_uuid']].explode('obs_uuid').set_index('obs_uuid')['hr_uuid'].to_dict()
point_id_to_obs_uuid = pd.DataFrame(obs_uuid_to_point_id.items(), columns=['obs_uuid', 'point_id']).groupby('point_id').agg(list)['obs_uuid'].to_dict()
point_gdf['obs_uuid'] = point_gdf['index'].map(point_id_to_obs_uuid)

tqdm.pandas(desc="Generating uuid for poi")
point_gdf['poi_uuid'] = point_gdf.progress_apply(lambda r: make_uuid_from_row_selection(LTM_UUID5_NS, r, ['geometry']), axis=1)
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v.poi_uuid, v.geometry, v.obs_uuid) for _, v in point_gdf.reset_index().iterrows()])
gdf_poi = gdf_poi.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
gdf_poi = gdf_poi.rename(columns={'coordinate': 'geometry'})

save_data_file_if_different(DATA_FOLDER, 'points_of_interest', gdf_poi, 'lausanne_1888_cadastre_renove_pois', RDE.POI.value)
QA_check_uuid_are_unique(gdf_poi.reset_index())

obs_df = pd.DataFrame(obs_uuid_to_point_id.items(), columns=['uuid', 'point_id'])
obs_df['hr_uuid'] = obs_df['uuid'].map(obs_uuid_to_hr_uuid)
obs_df['coordinate'] = obs_df['point_id'].map(point_gdf.set_index('index')['geometry'])
obs_df['has_geometry'] = obs_df['point_id'].map(point_gdf.set_index('index')['geom_uuid'])
obs_df['poi_uuid'] = obs_df['point_id'].map(point_gdf.set_index('index')['poi_uuid'])

tpe = 'parcel ownership'
obs_from_row = lambda v: produce_obs_obj(v.uuid, TR_OBJ, DS_UUID, v.hr_uuid, tpe, v.coordinate, None if pd.isna(v.has_geometry) else [v.has_geometry], v.poi_uuid)
obs = [obs_from_row(v) for _, v in obs_df.reset_index().iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})
QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'lausanne_1888_cadastre_renove_observations'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDE.OBS.value)
QA_check_unique_uuid_in_uuid_array(gdf_obs.reset_index(), 'has_geometry')

#HR RDE Production
exclude_hr_labels = {
    '*', 
    'has_geometry', 
    'coordinate',
    'poi_uuid',
    'obs_uuid',
    'hr_uuid',
}

dfs['obs_uuid'] = dfs['obs_uuid'].apply(lambda vs: [[v, 'parcel_id'] for v in vs])


# for display purposes in the intreface only, we will use the "owner" column, if it's empty, we will use "Unknown owner"
dfs['owner'] = dfs['owner'].fillna('Propriétaire inconnu')
dfs['Noms locaux'] = dfs['Noms locaux'].fillna('Toponyme inconnu')
hr_metadata_cols = list(set(dfs.columns).difference(exclude_hr_labels))
tpe = 'cadaster registry'
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       r['obs_uuid'],\
                       TR_OBJ,\
                       tpe,\
                       r[hr_metadata_cols].to_dict()) \
            for _, r in dfs.iterrows()
        ]

hr_shorthand = 'lausanne_1888_cadastre_renove_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)

# Dataset RDE Production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

filtered_df = dfs[hr_metadata_cols].copy()
remaining_vals = list(filtered_df.columns)
order = CONF['labels'].keys()

ds_conf = produce_configuration_file_from_metadata_df(
    LTM_UUID5_NS, 
    filtered_df[order], CONF["indexed"], 
    CONF["short_display"],
    CONF["hidden"], 
    {}, 
    CONF["tagged_fields"], 
    CONF["labels"],
    main_label=CONF["main_label"], 
    sub_label=CONF["sub_label"]
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
    [lausanne_area_uuid],
    publish_obj=(CONF['doi'], CONF['github_link'])
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'lausanne_1888_cadastre_renove_dataset', RDE.DATASET.value, is_dataset_obj=True)
