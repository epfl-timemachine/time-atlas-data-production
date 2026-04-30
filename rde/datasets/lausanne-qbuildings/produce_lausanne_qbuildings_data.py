
import uuid
import pandas as pd
import geopandas as gpd
import os
from os.path import join
import sys
from pathlib import Path
from tqdm import tqdm
import json

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from timeatlas.data_modeling import *
from utils import iiif
from timeatlas.RDEModel import RDEType


DATA_SRC_PATH = Path('src')

# aribtrary namespace, just to generate reproducible UUIDv5 from the entries of the dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))

lausanne_area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

DS_OBJ = (DS_UUID, DS_SLUG)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))
DATA_FOLDER = ''

# Geometry RDE production
geometries_fp = join(DATA_SRC_PATH, 'qbuildings-lausanne.geojson')
# sample for testing uuid_gen
gdf = gpd.read_file(geometries_fp, use_arrow=True).to_crs("EPSG:4326")


gdf['start_time'] = pd.Series(data = [TR_OBJ[0]] * len(gdf), name='start_time')
gdf['end_time'] = pd.Series(data = [TR_OBJ[1]] * len(gdf), name='end_time')

MAP_FOLDER = '../../maps/lausanne-qbuildings/'
cadaster_layer_uuid = get_layer_uuid(get_filepath_like(MAP_FOLDER+'layers', 'json'), 'buildings')
gdf['uuid'] = gdf.apply(lambda row: make_uuid_from_row_selection(VTM_UUID5_NS, row, ['geometry']), axis=1)


gdf['center'] = gdf['geometry'].apply(lambda v: v.centroid)

gdf['has_geometry'] = gdf['uuid'].apply(lambda v: [v])

gdf['layer_uuid'] = cadaster_layer_uuid
gdf['rde_type'] = "geometry"
QA_check_uuid_are_unique(gdf)

if not QA_check_all_geometries_are_valid(gdf, raise_exception=False):
    from shapely.validation import make_valid
    gdf['geometry'] = gdf['geometry'].apply(lambda g: g if g.is_valid else make_valid(g))
    QA_check_all_geometries_are_valid(gdf)

geom_shorthand = 'lausanne_qbuildings_geometries'
# "parcel_type" was removed for consistency with the other datasets. 
save_data_file_if_different(MAP_FOLDER, 'geometries', gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']], geom_shorthand, RDEType.GEOM.value)
df = gdf.drop(columns=['geometry']).copy().reset_index()

df['hr_uuid'] = df.apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['index'], ad_hoc_seed='hr'), axis=1)

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
obs_shorthand = 'lausanne_qbuildings_obs'
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

hr_shorthand = 'lausanne_qbuildings_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDEType.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'has_observations')

create_iiif_directory_if_not_exists()
# manifest for 2d thumbnails generation
man_list = {}
for _, row in df_of_hr.iterrows():
    content = row['metadata']
    man_label = f"{content['id_building']} - {content['class']}, {content['system_hotwater']}, {content['system_heating']}"
    hr_uuid = row['id']
    man_uuid = str(uuid.uuid5(VTM_UUID5_NS, man_label))
    annots = []
    pages = []
    building_id = content['id_building']
    # putting the thumbnail of the 3d vision of the model as the first page:
    page_0 = iiif.generate_page_object(VTM_UUID5_NS, DS_UUID, 0, man_uuid,  "Thumbnail of the cloudpoint model", \
                                                f'lausanne/3Dbuilding/thumbnails/qbuilding_{int(building_id)}.png', "image/png", 512, 1024, 'en')
    pages.append(dict(page_0, metadata = [(hr_uuid, man_label)]))
    man_cont = iiif.generate_manifest_object(VTM_UUID5_NS, man_uuid, {'en': [man_label]}, 'en', pages, None)
    man_list[man_uuid] = (man_label, pages[0])
    with open(f'iiif/manifests/{man_uuid}.json', 'w+', encoding='utf-8') as f:
        json.dump(man_cont, f, indent=2, ensure_ascii=False)

# 3d manifest generation
format = "application/vnd.las"
df_of_hr['3d_filename'] = df_of_hr['metadata'].apply(lambda x: f"qbuilding_{x['id_building']}.las")
man_3d_list = {}
for _, row in df_of_hr.iterrows():
    content = row['metadata']
    label = f"{content['id_building']} - {content['class']}, {content['system_hotwater']}, {content['system_heating']}"
    filename = row['3d_filename']
    man_uuid = str(uuid.uuid5(VTM_UUID5_NS, filename))
    access_url = f"http://timeatlas.eu/assets/las/{filename}"
    manifest = iiif.single_3d_model_manifest(VTM_UUID5_NS, man_uuid, {"en": [label]}, access_url, format)
    canvas_id = manifest['items'][0]['id']
    annotation = iiif.generate_hr_commenting_annotation(VTM_UUID5_NS, canvas_id, 'en', [(row['id'], {"en": [label]})], 'Scene')
    manifest['items'][0]['annotations'] = [annotation]
    man_3d_list[man_uuid] = (label, man_uuid)
    with open(f'iiif/manifests/{man_uuid}.json', 'w+') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

collection_3d_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_3d_{DS_SLUG}'))
collection_3d_label = {"en": ['Cloudpoints models in LAS format from all lausanne buildings from contemporary LIDAR data acquisition']}

with open(f'iiif/collections/{collection_3d_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest_no_thumbnail(collection_3d_manifest_uid, collection_3d_label, man_3d_list), f, indent=2, ensure_ascii=False)

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
    [],
    TR_OBJ,
    0,
    ds_conf,
    md,
    lausanne_area_uuids
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'lausanne_qbuildings_dataset', RDEType.DATASET.value, is_dataset_obj=True)
