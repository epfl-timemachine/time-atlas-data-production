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


DATA_SRC_PATH = Path(join(parent_dir, 'data-venice/1808_Sommarioni/'))


# aribtrary namespace, just to generate reproducible UUIDv5 from the entries of the dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
MAP_SLUG = f"{DS_SLUG}-map" # used for the map manifest, different from the map slug of the map itself.
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))

cadaster_layer_uuid = get_layer_uuid(get_filepath_like('../../maps/venice-1808-sommarioni/layers', 'json'), 'cadaster')
venice_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

DS_OBJ = (DS_UUID, DS_SLUG)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))
DATA_FOLDER = 'data'

# Source Entities Production:
#1. manifest for the registry
from utils import iiif

collection = {}
# debug that HR: 9b33424c-4947-52ce-b7ec-fa289ac1223f
df_imgs = pd.read_csv('src/imgs_width_height_format.csv')
df_imgs['volume'], df_imgs['page'] = zip(*df_imgs['filename'].str.split('/'))
df_imgs['label'] = df_imgs['filename'].str.replace('.jpg', '')
df_imgs = df_imgs.reset_index() # to derive a canvas_idx value for page generation.

manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'manifest_{DS_SLUG}'))
registry_label = {"en": ['Napoleonic cadaster\'s registry of 1808'],
                  "fr": ['Registre du cadastre napoléonien de 1808'],
                    "it": ['Registro catastale napoleonico del 1808']
                    }

collection[manifest_uid] = registry_label

df_imgs['page_obj'] = df_imgs.apply(lambda x:\
                                     iiif.generate_page_object(VTM_UUID5_NS, DS_SLUG, x['index'], manifest_uid, \
                                                             x['label'], 'venice/sommarioni/registry/'+x['filename'],\
                                                             x['media_type'], x['width'], x['height'], 'it'), axis=1)
df_imgs['canvas_id'] = df_imgs['page_obj'].apply(lambda x: x['id'])
range_id_pref = f'{manifest_uid}/range'
groups = df_imgs[['volume', 'canvas_id']].groupby(['volume']).agg(list)
structures = iiif.ordered_dict_to_iiif_toc_structure(iiif.multiindex_to_nested_dict(groups), "it", "Sommarioni", range_id_pref)

#2. manifest for the map
df_maps = pd.read_csv('src/maps_width_height_format.csv')
df_maps['label'] = df_maps['filename'].str.replace('.jpg', '')
df_maps = df_maps.reset_index() # to derive a canvas_idx value for page generation.

map_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'manifest_{MAP_SLUG}'))
map_label = {"en": ['Napoleonic\'s cadaster map of 1808'],
            "fr": ['Carte du cadastre napoléonien de 1808'],
            "it": ['Mappa del catastro napoleonico del 1808']
            }
collection[map_manifest_uid] = map_label
df_maps['page_obj'] = df_maps.apply(lambda x:\
                                     iiif.generate_page_object(VTM_UUID5_NS, MAP_SLUG, x['index'], map_manifest_uid, \
                                                             x['label'], 'venice/sommarioni/cadastral_maps/'+x['filename'],\
                                                             x['media_type'], x['width'], x['height'], 'it'), axis=1)
df_maps['canvas_id'] = df_maps['page_obj'].apply(lambda x: x['id'])
with open(f'data/iiif/manifests/{map_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_manifest_object(VTM_UUID5_NS, map_manifest_uid, map_label, 'en', df_maps['page_obj'].tolist()), f, indent=2, ensure_ascii=False)

#3. the collection of manifests
collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
collection_label = {"en": ['Napoleonic cadaster of 1808'],
                  "fr": ['Cadastre napoléonien de 1808'],
                    "it": ['Catasto napoleonico del 1808']
                    }
with open(f'data/iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest(collection_manifest_uid, collection_label, collection), f, indent=2, ensure_ascii=False)

# Geometry RDE production
geometries_fp = get_filepath_like(os.path.join(DATA_SRC_PATH,"sommarioni_geometries_"), 'geojson')#sorted(list(DATA_SRC_PATH.rglob('sommarioni_geometries_*.geojson')))[-1]
# sample for testing uuid_gen
gdf = gpd.read_file(geometries_fp)
gdf_star = gdf[gdf.geometry_id >= 0].copy() # removing the -1 geometry id since we don't have historical record tied to those ones (-1 is default value for all geometries we have nothing for)
centre_gdf = gdf_star.dissolve(by='geometry_id').reset_index()[['geometry_id', 'geometry', 'parish_standardized']]
centre_gdf['centroid'] = centre_gdf['geometry'].apply(lambda v: v.centroid)
centre_gdf['coordinate'] = centre_gdf.apply(lambda x: constraint_point_to_center_of_one_polygon(x['centroid'], x['geometry']), axis=1)
centre_gdf.drop(columns=['centroid'], inplace=True)
gdf['start_time'] = pd.Series(data = [TR_OBJ[0]] * len(gdf), name='start_time')
gdf['end_time'] = pd.Series(data = [TR_OBJ[1]] * len(gdf), name='end_time')

tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['id']), axis=1)
gdf['layer_uuid'] = cadaster_layer_uuid
gdf['rde_type'] = "geometry"
QA_check_uuid_are_unique(gdf)

if not QA_check_all_geometries_are_valid(gdf, raise_exception=False):
    from shapely.validation import make_valid
    gdf['geometry'] = gdf['geometry'].apply(lambda g: g if g.is_valid else make_valid(g))
    QA_check_all_geometries_are_valid(gdf)

geom_shorthand = 'sommarioni_geometries'
# "parcel_type" was removed for consistency with the other datasets. 
save_data_file_if_different(DATA_FOLDER, 'geometries', gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']], geom_shorthand, RDE.GEOM.value)

# storing in a single dataframe all the data that will be needed to add to the Obs objects. 
geomid_uuid_list = gdf[gdf.geometry_id >= 0].groupby(by="geometry_id")['uuid'].apply(list).reset_index(name='has_geometry').set_index('geometry_id')
centre_gdf = centre_gdf.set_index('geometry_id')
geomid_uuid_list['coordinate'] = centre_gdf['coordinate']
geomid_uuid_list['parish_standardized'] = centre_gdf['parish_standardized']

txt_data_w_pages_file = get_filepath_like(os.path.join(DATA_SRC_PATH,"sommarioni_text_data_with_pages_"), 'json') #sorted(list(DATA_SRC_PATH.rglob('sommarioni_text_data_with_pages_*.json')))[-1]

dfs = pd.read_json(txt_data_w_pages_file)
# removing the 5 duplicated entries
s = dfs.drop(columns=['ownership_types', 'qualities', 'unique_id']).drop_duplicates()
dfs = dfs.iloc[s.index]

# so we have obs. of specific subparcels.
dfs['parcel_id'] = dfs[["parcel_number", "sub_parcel_number"]].apply(lambda v:  ", ".join(e for e in v if e), axis=1) # merci arnaud
# remove the "N" as a first value, so that the values are homogeneous with the ones from Catastici.
dfs['district_acronym'] = dfs['district_acronym'].str[1:]


# dictionary below obtained using a "value_counts" method and then it was simply manual matching with the list of the 6 venetian districts.
# Ghetto was added so the dictionary can be used with the catastici values
# dfs.district_acronym.value_counts()
district_acronym_d = {
    "CN": "Cannaregio",
    "CS": "Castello",
    "SM": "San Marco",
    "DD": "Dorsoduro",
    "SP": "San Polo",
    "SC": "San Croce",
    "GH": "Ghetto",
    "CC": "Cannaregio" # de facto all places with NCC as district (240 in total) all have the "CN" acronym as first information in the "place" value. To check with Isabella if it's meaningful.
}
# whiile waiting for proper dictionary implementation in the frontend, expanding the district_acronym to the full name.
dfs['district'] = dfs['district_acronym'].map(district_acronym_d)
df = dfs.join(geomid_uuid_list, on='geometry_id')

# the sorted is important to ensure reproducibility of the UUIDs.
cols_for_hr_uuid_prod = sorted(set(df.columns).difference({'geometry_id', 'has_geometry', 'coordinate', 'parcel_id'}))

tqdm.pandas(desc="Generating uuid for hr")
df['hr_uuid'] = df.progress_apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['unique_id']), axis=1)

tqdm.pandas(desc="Generating uuid for obs")
df['obs_uuid'] = df.progress_apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['parcel_id', 'place']), axis=1)

tqdm.pandas(desc="Generating uuid for poi")
df['poi_uuid'] = df.progress_apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['coordinate']), axis=1)

# Obs RDE Procution
obs_df = df[['obs_uuid','hr_uuid', 'poi_uuid', 'coordinate']].groupby(by=['obs_uuid','coordinate']).agg(list).reset_index().set_index('obs_uuid')
obs_df['poi_uuid'] = obs_df['poi_uuid'].apply(lambda v: v[0])
# I have to do that because there is 7 obs. that have two historical sources recording it...
tpe = 'parcel ownership'
obs_df['has_geometry'] = df[~df.duplicated('obs_uuid',keep='first')].set_index('obs_uuid')['has_geometry']
obs_from_row = lambda v: produce_obs_obj(v.obs_uuid, TR_OBJ, DS_UUID, v.hr_uuid[0], tpe, v.coordinate, [r for r in v.has_geometry], v.poi_uuid)
obs = [obs_from_row(v) for _, v in obs_df.reset_index().iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})

QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'sommarioni_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDE.OBS.value)
QA_check_unique_uuid_in_uuid_array(gdf_obs.reset_index(), 'has_geometry')

#HR RDE Production
exclude_hr_labels = {
    'geometry_id', 
    'has_geometry', 
    'coordinate',
    'poi_uuid',
    'obs_uuid',
    'hr_uuid',
    'parcel_id'
}
# for display purposes in the intreface only, we will use the "owner" column, if it's empty, we will use "Unknown owner"
df['owner'].fillna('Unknown owner', inplace=True)
hr_metadata_cols = list(set(df.columns).difference(exclude_hr_labels))
tpe = 'cadaster registry'
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r['obs_uuid'], 'parcel_number']],\
                       TR_OBJ,\
                       tpe,\
                       r[hr_metadata_cols].to_dict()) \
            for _, r in df.iterrows()
        ]

hr_shorthand = 'sommarioni_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')

# POI RDE Production
df_poi = df[['coordinate', 'poi_uuid', 'obs_uuid']].groupby(by=['coordinate', 'poi_uuid']).agg(list)
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v.poi_uuid, v.coordinate, v.obs_uuid) for _, v in df_poi.reset_index().iterrows()])
gdf_poi = gdf_poi.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_poi = gdf_poi.rename(columns={'coordinate': 'geometry'})

save_data_file_if_different(DATA_FOLDER, 'points_of_interest', gdf_poi, 'sommarioni_pois', RDE.POI.value)
QA_check_uuid_are_unique(gdf_poi.reset_index())

QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')
QA_check_unique_uuid_in_uuid_array(gdf_poi.reset_index(), 'represents')

# Generating the manifest for the textual data
# (now that all HR uuid were generated)

df_of_hr['page'] = df_of_hr['annotated_content'].apply(lambda v: v['page'])
# only for reordering purpose. (note that parcel number should likely be casted to int, the ordering is not perfect)
df_of_hr['parcel_number'] = df_of_hr['annotated_content'].apply(lambda v: v['parcel_number'])
df_of_hr['sub_parcel_number'] = df_of_hr['annotated_content'].apply(lambda v: v['sub_parcel_number'])
page_to_canvas = df_imgs[['label', 'canvas_id']].set_index('label').to_dict()['canvas_id']
# preparing the data to insert in the canvas of the manifest.
df_iiif_links = df_of_hr[df_of_hr['page'].notnull()].copy().sort_values(by=['parcel_number', 'sub_parcel_number'])

def sommarioni_metadata_object_to_string_representation(metadata: dict) -> str:
    quick_check = lambda x: x if type(x) is str and x.lower() != 'nan' and len(x) > 0 else ''
    vals = [quick_check(metadata.get(v, '')) for v in ['parcel_number', 'sub_parcel_number', 'owner', 'qualities']]
    return ' | '.join([v for v in vals if len(v) > 0])

df_iiif_links['iiif_display_string'] = df_iiif_links['annotated_content'].apply(sommarioni_metadata_object_to_string_representation)
df_iiif_links['iiif_metadata_obj'] = df_iiif_links.apply(lambda x: (x['uuid'], x['iiif_display_string']), axis=1)
# applying the page to canvas mapping.
df_iiif_links['canvas_id'] = df_iiif_links['page'].apply(lambda v: page_to_canvas.get(v, None))
# # the hr_uuid is missing. 
iiif_links = df_iiif_links[['canvas_id', 'iiif_metadata_obj']].groupby('canvas_id', sort=False).agg(list).reset_index().set_index('canvas_id')['iiif_metadata_obj'].to_dict()
df_imgs['page_obj'] = df_imgs['page_obj'].apply(lambda x: dict(x, metadata = iiif_links.get(x['id'], '')))
with open(f'data/iiif/manifests/{manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_manifest_object(VTM_UUID5_NS, manifest_uid, registry_label, 'en', df_imgs['page_obj'].tolist(), structures), f, indent=2, ensure_ascii=False)

# dictionary OE Production
own_tpe_d = {k: k[0] + k.lower()[1:] for k in sorted(reduce(lambda a,b: a.union(set(b)), dfs.ownership_types.to_list(), set()))}
qual_d = {k: k[0] + k.lower()[1:] for k in sorted(reduce(lambda a,b: a.union(set(b)), dfs.qualities.to_list(), set()))}

own_tpe_n = 'venice-sommarioni-ownership-types-dictionary'
own_tpe_name = { "en": ['Ownership types of 1808 cadaster'], "fr": ['Types de propriété du cadastre de 1808'], "it": ['Tipi di proprietà del catasto del 1808']}
own_uuid = str(uuid.uuid5(VTM_UUID5_NS, own_tpe_n))
save_dictionary('../../dictionaries/', own_uuid, own_tpe_n, own_tpe_name, own_tpe_d)
qual_n = 'venice-sommarioni-parcel-functions-dictionary'
qual_name = { "en": ['Parcel functions of 1808 cadaster'], "fr": ['Fonctions des parcelles du cadastre de 1808'], "it": ['Funzioni delle particelle del catasto del 1808']}
qual_uuid = str(uuid.uuid5(VTM_UUID5_NS, qual_n))
save_dictionary('../../dictionaries/', qual_uuid,qual_n, qual_name, qual_d)
dist_n = 'venice-district-dictionary'
dist_name = { "en": ['Venetian districts'], "fr": ['Districts vénitiens'], "it": ['Distretti veneziani']}
dist_uuid = str(uuid.uuid5(VTM_UUID5_NS, dist_n))
save_dictionary('../../dictionaries/',dist_uuid, dist_n, dist_name, district_acronym_d)

# Dataset RDE Production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

dictionnaries = {
    "district_acronym": dist_uuid,
    "ownership_types": own_uuid,
    "qualities": qual_uuid,
    "parish_standardized": get_single_object_uuid('../../dictionaries/venice-garzoni-church-dictionary.json')
}

filtered_df = df[hr_metadata_cols].copy()
remaining_vals = list(filtered_df.columns)
remaining_vals.remove('unique_id')
order = CONF['labels'].keys()

ds_conf = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS, 
    filtered_df[order], CONF["indexed"], 
    CONF["short_display"],
    CONF["hidden"], 
    dictionnaries, 
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
    [collection_manifest_uid],
    TR_OBJ,
    len(df_iiif_links['canvas_id'].unique()),
    ds_conf,
    [venice_area_uuid],
    publish_obj=(CONF['doi'], CONF['github_link'])
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'sommarioni_dataset', RDE.DATASET.value, is_dataset_obj=True)