import uuid
import pandas as pd
import geopandas as gpd
import os
from os.path import join
import sys
from pathlib import Path
from tqdm import tqdm
import json
from pyproj import Transformer
from shapely.ops import transform

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils import iiif
from timeatlas.RDEModel import RDEType, Geometry


DATA_SRC_PATH = Path('src')

# aribtrary namespace, just to generate reproducible UUIDv5 from the entries of the dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))


DS_OBJ = (DS_UUID, DS_SLUG)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))


DATA_FOLDER = ''
MAP_FOLDER = '../../maps/switzerland-qbuildings/'

# Geometry RDE production
geometries_fp = join(DATA_SRC_PATH, 'qbuildings_whole_db.geojson')
# sample for testing uuid_gen

# the file is too big, so we're going to proceed by reading it line by line and generated the data this way.
import json
from shapely import wkt

SAVE_FILE_PREAMBLE = {
 "name": None,
 "type_in_file": [
 ],
 "creation_time": None,
 "rde_objects": None
}

from datetime import datetime
def save_list_of_rde_as_ingestion_file(ls: list, save_fp:str, name:str)->None:
    # does no checking. Used to brute force saving in case of huge amounts of data where automatic checking is too slow.
    # Use with caution and make sure data is clean before using it.
    # Ensure the directory exists before saving
    save_dir = os.path.dirname(save_fp)
    if save_dir and not os.path.exists(save_dir):
        os.makedirs(save_dir, exist_ok=True)
    
    all_types = list(set([l.get_type() for l in ls]))
    base = SAVE_FILE_PREAMBLE.copy()
    base['name'] = name
    base['type_in_file'] = all_types
    base['creation_time'] = datetime.now().isoformat()
    base['rde_objects'] = [l.to_dict() for l in ls]
    with open(save_fp, 'w', encoding='utf-8') as f:
        json.dump(base, f, ensure_ascii=False, indent=4)

def blocks(files, size=65536):
    while True:
        b = files.read(size)
        if not b: break
        yield b

with open(geometries_fp, "r",encoding="utf-8",errors='ignore') as f:
    number_of_lines = sum(bl.count("\n") for bl in blocks(f))


MAP_FOLDER_ORIG = '../../maps/switzerland-qbuildings/'
cadaster_layer_uuid = get_layer_uuid(get_filepath_like(MAP_FOLDER_ORIG+'layers', 'json'), 'buildings')
prop_array = []
geoms = []


MAX_FILE_SIZE_BYTES = 104857600 / 3  # 100MB (divided by 3 to be safe and avoid memory issues, since the size in memory can be bigger than the size on disk due to serialization overhead)
batch_nbr = 0
current_batch_size = 0

# because we don't instantiate a geofataframe, we have to do the CRS transformation manually, which is done here.
crs_transformer = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)

for i, line in tqdm(enumerate(open(geometries_fp, 'r')), desc='Processing geometries', total=number_of_lines):
    # break
    if not line.startswith('{ "type": "Feature",'):
        continue
    else:
        to_proc = line.strip().rstrip(',')  # remove the comma at the end of the line, which is not valid JSON
        feature = json.loads(to_proc)
        properties = feature.get('properties')
        curr_uuid = str(uuid.uuid5(VTM_UUID5_NS, properties['egid'] + '_geometry'))
        # todo: check the geometries are valid
        geom = Geometry.constructor_from_raw_geojson_line(to_proc, curr_uuid, cadaster_layer_uuid)
        geom.geometry = transform(crs_transformer.transform, geom.geometry)
        geoms.append(geom)
        center = geom.geometry.centroid
        properties['center'] = center
        prop_array.append(properties)

        # Estimate current batch size by serializing to JSON
        geom_dict = geom.to_dict()
        geom_size = len(json.dumps(geom_dict, ensure_ascii=False).encode('utf-8'))
        current_batch_size += geom_size
        
        # Save batch when it reaches approximately 100MB
        if current_batch_size >= MAX_FILE_SIZE_BYTES:
            save_list_of_rde_as_ingestion_file(geoms, join(MAP_FOLDER, f'geometries_batch_{batch_nbr}.json'), f'switzerland_qbuildings_geometries_batch_{batch_nbr}')
            batch_nbr += 1
            # clear the memory from the list content
            del geoms[:]
            geoms = []
            current_batch_size = 0
            
save_list_of_rde_as_ingestion_file(geoms, join(MAP_FOLDER, f'geometries_batch_{batch_nbr}.json'), f'switzerland_qbuildings_geometries_batch_{batch_nbr}')
import pickle
with open(join(DATA_SRC_PATH, 'prop_array.pkl'), 'wb') as f:
    pickle.dump(prop_array, f)
df = pd.DataFrame(prop_array)
# df = pd.read_csv('tmp_geometries_properties_batch.csv')
df['hr_uuid'] = df.apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['egid'], ad_hoc_seed='hr'), axis=1)
df['obs_uuid'] = df.apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['center'], ad_hoc_seed='obs'), axis=1)
df['has_geometry'] = df['egid'].apply(lambda x: [str(uuid.uuid5(VTM_UUID5_NS, str(x) + '_geometry'))])
# df.to_csv(f'tmp_geometries_properties_batch.csv', index=False)

obs_df = df[['obs_uuid','hr_uuid', 'center', 'has_geometry']].copy().reset_index().set_index('obs_uuid')
tpe = 'parcel ownership'
obs_from_row = lambda v: produce_obs_obj(v.obs_uuid, TR_OBJ, DS_UUID, v.hr_uuid, tpe, v.center, v.has_geometry)
obs = [obs_from_row(v) for _, v in obs_df.reset_index().iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_index('id').set_crs('EPSG:4326')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})
gdf_obs = gdf_obs.set_geometry('geometry')
QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'switzerland_qbuildings_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDEType.OBS.value)
QA_check_unique_uuid_in_uuid_array(gdf_obs.reset_index(), 'has_geometries')

#HR RDE Production
exclude_hr_labels = {
    'geometry_id', 
    'has_geometry',
    'obs_uuid',
    'hr_uuid',
    'geometry',
    'center',
    'end_time',
    'start_time',
    'index',
    'rde_type',
    'layer_uuid',
    'uuid',
    "status" # because it is an array and it fumbles the data generation.
}

drop_cols = {
}

exlude_cols = exclude_hr_labels.union(drop_cols)

df = df.replace({np.nan:None})
hr_metadata_cols = list(set(df.columns).difference(exlude_cols))

tpe = 'cadaster registry'

recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r['obs_uuid'], 'identifier']],\
                       TR_OBJ,\
                       tpe,\
                       r[hr_metadata_cols].to_dict()).to_dict(flatten_metadata=False) \
            for _, r in df.iterrows()
        ]

hr_shorthand = 'switzerland_qbuildings_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDEType.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'has_observations')

# Dataset RDE Production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

filtered_df = df[hr_metadata_cols].copy()
remaining_vals = list(filtered_df.columns)
order = CONF['labels'].keys()

ds_conf, md = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS, 
    filtered_df[order], 
    CONF
)
swiss_area_uids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    '1.0',
    CONF['name'],
    [],
    TR_OBJ,
    0,
    ds_conf,
    md,
    swiss_area_uids
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'switzerland_qbuildings_dataset', RDEType.DATASET.value, is_dataset_obj=True)
