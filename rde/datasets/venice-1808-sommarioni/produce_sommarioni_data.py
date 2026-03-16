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

DATA_SRC_PATH = Path(join(parent_dir, 'data-venice/1808_Sommarioni/'))

# aribtrary namespace, just to generate reproducible UUIDv5 from the entries of the dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
# MAP_SLUG = f"{DS_SLUG}-map" # used for the map manifest, different from the map slug of the map itself.
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))

MAP_FOLDER = '../../maps/venice-1808-sommarioni/'
cadaster_layer_uuid = get_layer_uuid(get_filepath_like(MAP_FOLDER+'layers', 'json'), 'cadaster')
venice_area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

DS_OBJ = (DS_UUID, DS_SLUG)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))
DATA_FOLDER = 'data'

# Source Entities Production:
#1. manifest for the registry
from utils import iiif

collection = {}
df_imgs = pd.read_csv('src/imgs_width_height_format.csv')
df_imgs['volume'], df_imgs['page'] = zip(*df_imgs['filename'].str.split('/'))
df_imgs['label'] = df_imgs['filename'].str.replace('.jpg', '')
df_imgs = df_imgs.reset_index() # to derive a canvas_idx value for page generation.

df_imgs['page_obj'] = None
df_imgs['manifest_uid'] = None
for vol, sdf in df_imgs.groupby('volume'):
    manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'manifest_{DS_SLUG}_{vol}'))
    registry_label = {
                        "en": [f'Archivio di Stato di Venezia, Catasti, Censo Stabile, Sommarioni, {vol}'],
                        "fr": [f'Archivio di Stato di Venezia, Catasti, Censo Stabile, Sommarioni, {vol}'],
                        "it": [f'Archivio di Stato di Venezia, Catasti, Censo Stabile, Sommarioni, {vol}']
                    }
    for _, x in sdf.iterrows():
        df_imgs.at[x['index'], 'page_obj'] = iiif.generate_page_object(VTM_UUID5_NS, DS_SLUG, x['index'], manifest_uid, \
                                                                    x['label'], 'venice/sommarioni/registry/'+x['filename'],\
                                                                    x['media_type'], x['width'], x['height'], 'it')
        df_imgs.at[x['index'], 'manifest_uid'] = manifest_uid
    
    collection[manifest_uid] = (registry_label, df_imgs[df_imgs['manifest_uid'] == manifest_uid]['page_obj'].tolist()[0])
                      
# as grouping were done on the volume, no longer necessary in the splitted version of the manifest. 
# range_id_pref = f'{manifest_uid}/range'
# groups = df_imgs[['volume', 'canvas_id']].groupby(['volume']).agg(list)
# structures = iiif.ordered_dict_to_iiif_toc_structure(iiif.multiindex_to_nested_dict(groups), "it", "Sommarioni", range_id_pref)
df_imgs['canvas_id'] = df_imgs['page_obj'].apply(lambda x: x['id'])

#2. manifest for the map 
# REMOVED BY REQUEST OF ISABELLA
# df_maps = pd.read_csv('src/maps_width_height_format.csv')
# df_maps['label'] = df_maps['filename'].str.replace('.jpg', '')
# df_maps = df_maps.reset_index() # to derive a canvas_idx value for page generation.

# map_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'manifest_{MAP_SLUG}'))
# map_label = {"en": ['Napoleonic\'s cadaster map of 1808'],
#             "fr": ['Carte du cadastre napoléonien de 1808'],
#             "it": ['Mappa del catastro napoleonico del 1808']
#             }
# df_maps['page_obj'] = df_maps.apply(lambda x:\
#                                     iiif.generate_page_object(VTM_UUID5_NS, MAP_SLUG, x['index'], map_manifest_uid, \
#                                                             x['label'], 'venice/sommarioni/cadastral_maps/'+x['filename'],\
#                                                             x['media_type'], x['width'], x['height'], 'it'), axis=1)


# collection[map_manifest_uid] = (map_label, df_maps['page_obj'].tolist()[0])

# df_maps['canvas_id'] = df_maps['page_obj'].apply(lambda x: x['id'])


# with open(f'data/iiif/manifests/{map_manifest_uid}.json', 'w+', encoding='utf-8') as f:
#     json.dump(iiif.generate_manifest_object(VTM_UUID5_NS, map_manifest_uid, map_label, 'en', df_maps['page_obj'].tolist()), f, indent=2, ensure_ascii=False)


#3. the collection of manifests
collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
collection_label = {"en": ['Archivio di Stato di Venezia, Catasti, Censo Stabile, Sommarioni'],
                  "fr": ['Archivio di Stato di Venezia, Catasti, Censo Stabile, Sommarioni'],
                    "it": ['Archivio di Stato di Venezia, Catasti, Censo Stabile, Sommarioni']
                    }
with open(f'data/iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest(collection_manifest_uid, collection_label, collection), f, indent=2, ensure_ascii=False)

# Geometry RDE production
geometries_fp = get_filepath_like(os.path.join(DATA_SRC_PATH, "venice_1808_landregister_geometries_internal_version"), 'geojson')#sorted(list(DATA_SRC_PATH.rglob('sommarioni_geometries_*.geojson')))[-1]
# sample for testing uuid_gen
gdf = gpd.read_file(geometries_fp)
gdf['geometry_id'] = gdf['geometry_id'].fillna(0).astype(int)


txt_data_w_pages_file = get_filepath_like(os.path.join(DATA_SRC_PATH, "venice_1808_landregister_textual_entries_internal_version"), 'json') #sorted(list(DATA_SRC_PATH.rglob('sommarioni_text_data_with_pages_*.json')))[-1]
dfs = pd.read_json(txt_data_w_pages_file)

gdf_star = gdf[gdf.geometry_id.isin(dfs['geometry_id'])].copy()

centre_gdf = gdf_star.dissolve(by='geometry_id').reset_index()[['geometry_id', 'geometry', 'parish_standardised']]
centre_gdf['centroid'] = centre_gdf['geometry'].apply(lambda v: v.centroid)
centre_gdf['coordinate'] = centre_gdf.apply(lambda x: constraint_point_to_center_of_one_polygon(x['centroid'], x['geometry']), axis=1)
centre_gdf.drop(columns=['centroid'], inplace=True)
gdf['start_time'] = pd.Series(data = [TR_OBJ[0]] * len(gdf), name='start_time')
gdf['end_time'] = pd.Series(data = [TR_OBJ[1]] * len(gdf), name='end_time')

tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['id']), axis=1)
gdf['layer_uuid'] = cadaster_layer_uuid
gdf['rde_type'] = "geometry"
QA_check_uuid_are_unique(gdf)

if not QA_check_all_geometries_are_valid(gdf, raise_exception=False):
    from shapely.validation import make_valid
    gdf['geometry'] = gdf['geometry'].apply(lambda g: g if g.is_valid else make_valid(g))
    QA_check_all_geometries_are_valid(gdf)

geom_shorthand = 'sommarioni_geometries'
# "parcel_type" was removed for consistency with the other datasets. 
save_data_file_if_different(MAP_FOLDER, 'geometries', gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']], geom_shorthand, RDEType.GEOM.value)

# storing in a single dataframe all the data that will be needed to add to the Obs objects. 
geomid_uuid_list = gdf.groupby(by="geometry_id")['uuid'].apply(list).reset_index(name='has_geometry').set_index('geometry_id')
centre_gdf = centre_gdf.set_index('geometry_id')
geomid_uuid_list['coordinate'] = centre_gdf['coordinate']
geomid_uuid_list['parish_standardised'] = centre_gdf['parish_standardised']

# so we have obs. of specific subparcels.
dfs['parcel_id'] = dfs[["parcel_number", "sub_parcel_number"]].apply(lambda v:  ", ".join(e for e in v if e), axis=1) # merci arnaud
df = dfs.join(geomid_uuid_list, on='geometry_id')

df['owner_transcription'] = df['owner_transcription'].fillna('Unknown owner')
# the sorted is important to ensure reproducibility of the UUIDs.
cols_for_hr_uuid_prod = sorted(set(df.columns).difference({'geometry_id', 'has_geometry', 'coordinate', 'parcel_id'}))

tqdm.pandas(desc="Generating uuid for hr")
df['hr_uuid'] = df.apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['unique_id']), axis=1)

tqdm.pandas(desc="Generating uuid for obs")
df['obs_uuid'] = df.apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['parcel_id', 'place', 'hr_uuid']), axis=1)

# Obs RDE Procution
obs_df = df[['obs_uuid','hr_uuid', 'coordinate']].groupby(by=['obs_uuid','coordinate']).agg(list).reset_index().set_index('obs_uuid')
tpe = 'parcel ownership'
obs_df['has_geometry'] = df[~df.duplicated('obs_uuid',keep='first')].set_index('obs_uuid')['has_geometry']
obs_from_row = lambda v: produce_obs_obj(v.obs_uuid, TR_OBJ, DS_UUID, v.hr_uuid[0], tpe, v.coordinate, [r for r in v.has_geometry])
obs = [obs_from_row(v) for _, v in obs_df.reset_index().iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})
gdf_obs = gdf_obs.set_geometry('geometry')
QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'sommarioni_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDEType.OBS.value)
QA_check_unique_uuid_in_uuid_array(gdf_obs.reset_index(), 'has_geometry')

#HR RDE Production
exclude_hr_labels = {
    'geometry_id', 
    'has_geometry', 
    'coordinate',
    'obs_uuid',
    'hr_uuid',
    'parcel_id'
}

drop_cols = {
    "llm_guess",
    "is_people",
    "new_transcription",
    "area"
}

bilingual_cols = {
   "old_religious_entity_type",
    "qualities",
    "old_owner_right_of_use_"
    "owner_right_of_use",
    "ownership_types"
}
exlude_cols = exclude_hr_labels.union(drop_cols.union(bilingual_cols))

# for display purposes in the intreface only, we will use the "owner" column, if it's empty, we will use "Unknown owner"
df['owner_transcription'] = df['owner_transcription'].fillna('Unknown owner')
df = df.replace({np.nan:None})
# for some reasone, a NaN cannot be replaced there.
df.at[df[df.unique_id == 23647].index[0], 'parish_standardised'] = None 
hr_metadata_cols = list(set(df.columns).difference(exlude_cols))
tpe = 'cadaster registry'
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r['obs_uuid'], 'parcel_number']],\
                       TR_OBJ,\
                       tpe,\
                       r[hr_metadata_cols].to_dict()).to_dict(flatten_metadata=False) \
            for _, r in df.iterrows()
        ]

hr_shorthand = 'sommarioni_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDEType.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')

# Generating the manifest for the textual data
# (now that all HR uuid were generated)

df_of_hr['page'] = df_of_hr['metadata'].apply(lambda v: v['page_number'])
# only for reordering purpose. (note that parcel number should likely be casted to int, the ordering is not perfect)
df_of_hr['parcel_number'] = df_of_hr['metadata'].apply(lambda v: v['parcel_number'])
df_of_hr['sub_parcel_number'] = df_of_hr['metadata'].apply(lambda v: v['sub_parcel_number'])
page_to_canvas = df_imgs[['label', 'canvas_id']].set_index('label').to_dict()['canvas_id']
# preparing the data to insert in the canvas of the manifest.
df_iiif_links = df_of_hr[df_of_hr['page'].notnull()].copy().sort_values(by=['parcel_number', 'sub_parcel_number'])

def sommarioni_metadata_object_to_string_representation(metadata: dict) -> str:
    quick_check = lambda x: x if type(x) is str and x.lower() != 'nan' and len(x) > 0 else ''
    vals = [quick_check(metadata.get(v, '')) for v in ['parcel_number', 'sub_parcel_number', 'owner', 'qualities']]
    return ' | '.join([v for v in vals if len(v) > 0])

df_iiif_links['iiif_display_string'] = df_iiif_links['metadata'].apply(sommarioni_metadata_object_to_string_representation)
df_iiif_links['iiif_metadata_obj'] = df_iiif_links.apply(lambda x: (x['uuid'], x['iiif_display_string']), axis=1)
# applying the page to canvas mapping.
df_iiif_links['canvas_id'] = df_iiif_links['page'].apply(lambda v: page_to_canvas.get(v, None))
# # the hr_uuid is missing. 
iiif_links = df_iiif_links[['canvas_id', 'iiif_metadata_obj']].groupby('canvas_id', sort=False).agg(list).reset_index().set_index('canvas_id')['iiif_metadata_obj'].to_dict()
df_imgs['page_obj'] = df_imgs['page_obj'].apply(lambda x: dict(x, metadata = iiif_links.get(x['id'], '')))

for manifest_uid, sub_df in df_imgs.groupby('manifest_uid'):
    curr_label = collection[manifest_uid][0]
    with open(f'data/iiif/manifests/{manifest_uid}.json', 'w+', encoding='utf-8') as f:
        json.dump(iiif.generate_manifest_object(VTM_UUID5_NS, manifest_uid, curr_label, 'en', sub_df['page_obj'].tolist()), f, indent=2, ensure_ascii=False)


# Dataset RDE Production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

filtered_df = df[hr_metadata_cols].copy()
remaining_vals = list(filtered_df.columns)
remaining_vals.remove('unique_id')
order = CONF['labels'].keys()

ds_conf = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS, 
    filtered_df[order], 
    CONF
)

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    '1.1',
    CONF['name'],
    [collection_manifest_uid],
    TR_OBJ,
    len(df_iiif_links['canvas_id'].unique()),
    ds_conf,
    venice_area_uuids
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'sommarioni_dataset', RDEType.DATASET.value, is_dataset_obj=True)