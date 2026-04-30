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

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from timeatlas.data_modeling import *
from timeatlas.RDEModel import RDEType
from utils import iiif


DATA_SRC_PATH = Path(join(parent_dir, 'data-lausanne/1831-cadastre-berney/'))

# aribtrary namespace, just to generate reproducible UUIDv5 from the entries of the dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))

lausanne_area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

DS_OBJ = (DS_UUID, DS_SLUG)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))
DATA_FOLDER = ''

# Geometry RDE production
geometries_fp = join(DATA_SRC_PATH, 'Berney_merge_legende_v7-7_formatted_for_timeatlas.geojson')
wh_fp = join(DATA_SRC_PATH, 'wh_images.csv')
# sample for testing uuid_gen
gdf = gpd.read_file(geometries_fp, use_arrow=True).to_crs("EPSG:4326")


gdf['start_time'] = pd.Series(data = [TR_OBJ[0]] * len(gdf), name='start_time')
gdf['end_time'] = pd.Series(data = [TR_OBJ[1]] * len(gdf), name='end_time')

MAP_FOLDER = '../../maps/lausanne-1831-berney/'
cadaster_layer_uuid = get_layer_uuid(get_filepath_like(MAP_FOLDER+'layers', 'json'), 'cadaster')
tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.apply(lambda row: make_uuid_from_row_selection(VTM_UUID5_NS, row, ['geometry']), axis=1)

# entries without identifier only relate to geometric features without information from the registry, they don't make sense as Historical Record
df = gdf[gdf['identifier'] != ''].copy()
df = df.groupby('identifier').first().reset_index()

from shapely.ops import unary_union
from shapely.geometry import Point
id_geoms = df.groupby('identifier').agg({'uuid': lambda x: list(x), 'geometry': lambda x: list(x)}).reset_index()
def compute_center(geoms: list):
    if len(geoms) == 0:
        return None
    if len(geoms) == 1:
        c = geoms[0].centroid
    else:
        # multiple geometries: fuse them and take centroid
        fused = unary_union(geoms)
        c = fused.centroid
    # return as (x, y) tuple
    return Point(c.x, c.y)
id_geoms['center'] = id_geoms['geometry'].apply(compute_center)

df['has_geometry'] = df['identifier'].apply(lambda idf: id_geoms.loc[id_geoms['identifier'] == idf, 'uuid'].values[0])
df['center'] = df['identifier'].apply(lambda idf: id_geoms.loc[id_geoms['identifier'] == idf, 'center'].values[0])
df = df.drop(columns=['uuid'])

gdf['layer_uuid'] = cadaster_layer_uuid
gdf['rde_type'] = "geometry"
QA_check_uuid_are_unique(gdf)

if not QA_check_all_geometries_are_valid(gdf, raise_exception=False):
    from shapely.validation import make_valid
    gdf['geometry'] = gdf['geometry'].apply(lambda g: g if g.is_valid else make_valid(g))
    QA_check_all_geometries_are_valid(gdf)

geom_shorthand = 'lausanne_1831_berney_geometries'
# "parcel_type" was removed for consistency with the other datasets. 
save_data_file_if_different(MAP_FOLDER, 'geometries', gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']], geom_shorthand, RDEType.GEOM.value)
tqdm.pandas(desc="Generating uuid for hr")
df['hr_uuid'] = df.apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['identifier'], ad_hoc_seed='hr'), axis=1)

tqdm.pandas(desc="Generating uuid for obs")
df['obs_uuid'] = df.apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['center'], ad_hoc_seed='obs'), axis=1)

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
obs_shorthand = 'lausanne_1831_berney_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDEType.OBS.value)
QA_check_unique_uuid_in_uuid_array(gdf_obs.reset_index(), 'has_geometries')

hr_uuid_to_page_filename = df.set_index('hr_uuid')['page_filename'].to_dict()

#HR RDE Production
exclude_hr_labels = {
    'geometry_id', 
    'has_geometry',
    'obs_uuid',
    'hr_uuid',
    'geometry',
    'own_col_de', #empty.
    'page', 
    'number'
}

drop_cols = {
    'page_filename',
    'center'
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

hr_shorthand = 'lausanne_1831_berney_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDEType.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'has_observations')

# normally the pages are already sorted as is in the CSV
df_pages = pd.read_csv(wh_fp)

def format_filename_to_code(filename:str):
    code = filename.replace('PC_1827-1831_Berney_Vol-', '')
    if 'legende' in code:
        code = code.replace('_legende', '') + (' (légende)')
    code = code.split('_')[-1].replace('.jpg', '')
    if code.isnumeric():
        code = int(code)
    return code

df_pages['page_num'] = df_pages['filename'].apply(lambda x: format_filename_to_code(x))

IMG_LOC_PREFIX = 'lausanne/berney'

manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'manifest_{DS_SLUG}'))
df_pages['page_obj'] = None
for i, x in df_pages.iterrows():
    df_pages.at[i, 'page_obj'] = iiif.generate_page_object(VTM_UUID5_NS, DS_SLUG, i, manifest_uid, \
                                                                'pg. '+str(x['page_num']), IMG_LOC_PREFIX+x['filename'],\
                                                                x['media_type'], x['width'], x['height'], 'fr')
    
df_pages['canvas_id'] = df_pages['page_obj'].apply(lambda x: x['id'])

page_to_canvas = df_pages[['filename', 'canvas_id']].set_index('filename').to_dict()['canvas_id']
# preparing the data to insert in the canvas of the manifest.

collection = {}
registry_label = {
                    "fr": [f'Cadastre de Lausanne en 1831'],
                    "en": [f'Lausanne\'s cadaster in 1831'],
                    "it": [f'Cadastre di Losanna nel 1831'],
                    "de": [f'Kataster von Lausanne im Jahr 1831'],
                    "nl": [f'Kadaster van Lausanne in 1831']
                }

collection[manifest_uid] = (registry_label, df_pages['page_obj'].tolist()[0])
create_iiif_directory_if_not_exists()
collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
with open(f'iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest(collection_manifest_uid, registry_label, collection), f, indent=2, ensure_ascii=False)

hr_uuid_to_page_filename
page_to_canvas
canvas_to_hr_list = {}
for hr_uuid, page_filename in hr_uuid_to_page_filename.items():
    if page_filename in page_to_canvas:
        canvas_id = page_to_canvas[page_filename]
        if canvas_id not in canvas_to_hr_list:
            canvas_to_hr_list[canvas_id] = []
        canvas_to_hr_list[canvas_id].append(hr_uuid)

df_pages['page_obj'] = df_pages['page_obj'].apply(lambda x: dict(x, metadata = canvas_to_hr_list.get(x['id'], '')))

with open(f'iiif/manifests/{manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_manifest_object(VTM_UUID5_NS, manifest_uid, registry_label, 'en', df_pages['page_obj'].tolist()), f, indent=2, ensure_ascii=False)


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

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    '1.0',
    CONF['name'],
    [collection_manifest_uid],
    TR_OBJ,
    0,
    ds_conf,
    md,
    lausanne_area_uuids
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'lausanne_1831_berney_dataset', RDEType.DATASET.value, is_dataset_obj=True)
