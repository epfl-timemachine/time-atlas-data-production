import uuid
import pandas as pd
import geopandas as gpd
import os
from os.path import join
import sys
from pathlib import Path
from tqdm import tqdm
import json

# to have progress bar in the notebook
tqdm.pandas()
with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

DATA_SRC_PATH = Path('src')

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

# aribtrary namespace, just to generate reproducible UUIDv5 from the entries of the dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))

amsterdam_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

DS_OBJ = (DS_UUID, DS_SLUG)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))
DATA_FOLDER = 'data'

# Geometry RDE production
geometries_fp = join(DATA_SRC_PATH, '1832_Adamhuurw_gebouwlaagkadaster')
point_fp = join(DATA_SRC_PATH, '1832_AdamPointlayer')
# sample for testing uuid_gen
gdf = gpd.read_file(geometries_fp).set_crs("EPSG:28992").to_crs("EPSG:4326")
df = gpd.read_file(point_fp).set_crs("EPSG:28992").to_crs("EPSG:4326")

gdf['start_time'] = pd.Series(data = [TR_OBJ[0]] * len(gdf), name='start_time')
gdf['end_time'] = pd.Series(data = [TR_OBJ[1]] * len(gdf), name='end_time')

MAP_FOLDER = '../../maps/amsterdam-1832-huurwarden/'
cadaster_layer_uuid = get_layer_uuid(get_filepath_like(MAP_FOLDER+'layers', 'json'), 'huurwarden')

tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['OBJECTID']), axis=1)
object_id_to_uuid = gdf.set_index('OBJECTID')['uuid'].to_dict()
df['has_geometry'] = df['OBJECTID'].apply(lambda r: object_id_to_uuid[r])
gdf['layer_uuid'] = cadaster_layer_uuid
gdf['rde_type'] = "geometry"
QA_check_uuid_are_unique(gdf)

if not QA_check_all_geometries_are_valid(gdf, raise_exception=False):
    from shapely.validation import make_valid
    gdf['geometry'] = gdf['geometry'].apply(lambda g: g if g.is_valid else make_valid(g))
    QA_check_all_geometries_are_valid(gdf)

geom_shorthand = 'amsterdam_1832_huurwarden_geometries'
# "parcel_type" was removed for consistency with the other datasets. 
save_data_file_if_different(MAP_FOLDER, 'geometries', gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']], geom_shorthand, RDE.GEOM.value)

cols_for_hr_uuid_prod = sorted(set(df.columns).difference({'geometry_id', 'has_geometry', 'coordinate', 'parcel_id'}))

tqdm.pandas(desc="Generating uuid for hr")
df['hr_uuid'] = df.progress_apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['OBJECTID'], ad_hoc_seed='hr'), axis=1)

tqdm.pandas(desc="Generating uuid for obs")
df['obs_uuid'] = df.progress_apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['OBJECTID'], ad_hoc_seed='obs'), axis=1)

obs_df = df[['obs_uuid','hr_uuid', 'geometry']].groupby(by=['obs_uuid','geometry']).agg(list).reset_index().set_index('obs_uuid')
# I have to do that because there is 7 obs. that have two historical sources recording it...
tpe = 'parcel ownership'
obs_df['has_geometry'] = df[~df.duplicated('obs_uuid',keep='first')].set_index('obs_uuid')['has_geometry']
obs_from_row = lambda v: produce_obs_obj(v.obs_uuid, TR_OBJ, DS_UUID, v.hr_uuid[0], tpe, v.geometry, [v.has_geometry])
obs = [obs_from_row(v) for _, v in obs_df.reset_index().iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})
gdf_obs = gdf_obs.set_geometry('geometry')
QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'amsterdam_1832_huurwarden_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDE.OBS.value)
QA_check_unique_uuid_in_uuid_array(gdf_obs.reset_index(), 'has_geometry')

#HR RDE Production
exclude_hr_labels = {
    'geometry_id', 
    'has_geometry',
    'obs_uuid',
    'hr_uuid',
    'geometry'
}

drop_cols = {
    "Periode",
    "OBJECTID"
}

exlude_cols = exclude_hr_labels.union(drop_cols)

df = df.replace({np.nan:None})
hr_metadata_cols = list(set(df.columns).difference(exlude_cols))
tpe = 'cadaster registry'
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r['obs_uuid'], 'parcel_number']],\
                       TR_OBJ,\
                       tpe,\
                       r[hr_metadata_cols].to_dict()) \
            for _, r in df.iterrows()
        ]

hr_shorthand = 'amsterdam_1832_huurwarden_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')


# Dataset RDE Production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

filtered_df = df[hr_metadata_cols].copy()
remaining_vals = list(filtered_df.columns)
order = CONF['labels'].keys()

ds_conf = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS, 
    filtered_df[order],
    CONF['dataset_metadata_config'],
    CONF["indexed"], 
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
    [],
    TR_OBJ,
    0,
    ds_conf,
    [amsterdam_area_uuid]
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'amsterdam_1832_huurwarden_dataset', RDE.DATASET.value, is_dataset_obj=True)