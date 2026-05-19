import uuid
import pandas as pd
import geopandas as gpd
import os
import sys
import re 
from tqdm import tqdm
# to have progress bar in the notebook
tqdm.pandas()

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils import iiif
from timeatlas.RDEModel import RDEType

with open('dataproduction_config_edifici.json') as f:
    DATA_CONFIG = json.load(f)

DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))

min_time = datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM'])
max_time = datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True)

MAP_FOLDER = '../../maps/venice-2024-contemporary/'
edifici_layer_uuid = get_layer_uuid(MAP_FOLDER+'layers.json', 'venice-2024-contemporary-map-edifici')
DATA_VENICE_FOLDER = os.path.join(parent_dir, 'data-venice')

# to note: all the geometries are expressde as multipolygon, but actually there is a single geometry in each. No need to do multiple geometries per obs a simple explode reduce them to single polygon.
df = gpd.read_file('src/2025-08-06_edifici_forwebinterface.geojson').to_crs('EPSG:4326').explode()
df = df.drop_duplicates()
df['EDIFI_ID'] = df['EDIFI_ID'].astype(str)

edifi_id_to_remove = ['6422','6421']
df = df[~df['EDIFI_ID'].isin(edifi_id_to_remove)]
df['start_time'] = min_time
df['end_time'] = max_time
DATA_FOLDER = ''

venice_area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

edific_id_fp = '../venice-cini-photographs/edifici_id_to_geom_uuid.json'
with open(edific_id_fp) as f:
    edifici_id_to_geom_uuid = json.load(f)

df['geometry_uuid'] = df['EDIFI_ID'].map(edifici_id_to_geom_uuid)
df['has_geometry'] = df['geometry_uuid'].apply(lambda r: [r])
df['aulic_name'] = df['aulic_name'].fillna('Unknown edifice name')

df['hr_uuid'] = df.apply(lambda x: make_uuid_from_row_selection(VTM_UUID5_NS, x, ['EDIFI_ID']), axis=1)
df['obs_uuid'] = df.apply(lambda x: make_uuid_from_row_selection(VTM_UUID5_NS, x, ['geometry'], ad_hoc_seed='obs'), axis=1)

# Generating Obs
df['type'] = '3d-structure'
obs_from_row = lambda v: produce_obs_obj(v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, v.type, v.geometry.centroid, v.has_geometry)
obs = [obs_from_row(v) for _, v in df.iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_index('id').set_crs('EPSG:4326')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})
gdf_obs = gdf_obs.set_geometry('geometry')
QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'cloudpoints_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDEType.OBS.value)

#Produce HRs
cols_of_non_interest = [
    'geometry',
    'centroid',
    'hr_uuid',
    'obs_uuid',
    'has_geometry',
    'geometry_uuid',
    'start_date',
    'end_date',
    'SESTIERE_ABR',
    'end_time',
    "start_time",
    "type"
]

recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r['obs_uuid'], 'EDIFI_ID']],\
                       (r.start_time, r.end_time),\
                       r.type,\
                       r[df.columns.difference(cols_of_non_interest)].to_dict()).to_dict(flatten_metadata=False) \
            for _, r in df.iterrows()
        ]

hr_shorthand = 'cloudpoints_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDEType.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'has_observations')

df_img = pd.read_csv('src/2025-08-25_images_width_height.csv')
df_img.groupby('folder').first()

def extract_uid_square_bracket(s):
    '''
    Using regex, extract the UID from the filename.
    example: 2549_[uid_0389]_.png => 0389
    '''
    match = re.search(r'\[uid_(W?\d+)\]', s)
    if match:
        return match.group(1)
    return None

def extract_uid_beginning(s): 
    '''
    Using regex, extract the UID from the filename.
    example: /2549_0389.png => 2549
    '''
    match = re.search(r'(\d+)', s)
    if match:
        return match.group(1)
    return None

extract_strategy_per_folder = {
    'edifici_depthmap': extract_uid_beginning,
    'edifici_facades': extract_uid_square_bracket,
    'edifici_panoramas': extract_uid_beginning,
    'street_depthmap_noaxis': extract_uid_beginning,
    'street_depthmap_waxis': extract_uid_square_bracket,
    'street_panopticon_noaxis': extract_uid_square_bracket,
    'street_panopticon_waxis': extract_uid_square_bracket
}

df_img['uid'] = df_img.apply(lambda x: extract_strategy_per_folder[x['folder']](x['filename']), axis=1)
df_img['uid'] = df_img['uid'].apply(lambda x: x.replace('W', '0'))
df_img['uid'] = df_img['uid'].apply(lambda x: x.zfill(4) if len(x) < 4  else x)

edificies_order = [
    'edifici_panoramas',
    'edifici_depthmap',
    'edifici_footprints',
    'edifici_facades',
]

streets_order = [
    'street_panopticon_noaxis',
    'street_panopticon_waxis',
    'street_depthmap_noaxis',
    'street_depthmap_waxis',
    'street_facades'
]

df_img['type'] = df_img['folder'].apply(lambda x: 'edifici' if 'edifici' in x else 'street')

def sorting_key(folder):
    if folder in edificies_order:
        return edificies_order.index(folder)
    elif folder in streets_order:
        return streets_order.index(folder)
    else:
        return len(edificies_order) + len(streets_order) # if the folder is not in any of the two lists, put it at the end

def sort_group(df, df_group: tuple):
    dfi = df.sort_values('folder', key=lambda x: x.map(sorting_key))
    dfi['uid'] = df_group[0] # putting the uid back in the sorted dataframe, as it is lost during the groupby apply
    dfi['type'] = df_group[1]
    return dfi
    
# apply the order per grouped by edifi id according to the types:
df_man = df_img.groupby(['uid', 'type']).apply(lambda v: sort_group(v, v.name))
df_man_edifici = df_man[df_man['type'] == 'edifici'].drop(columns=['uid'])
df_of_hr['EDIFI_ID'] = df_of_hr['metadata'].apply(lambda x: str(x['EDIFI_ID']).zfill(4) if 'EDIFI_ID' in x else None)
df_of_hr['label_txt'] = df_of_hr['metadata'].apply(lambda x: f"{x['aulic_name']}, {x['EDIFI_ID']} - {x['CIVICI']}")

# Source Production
url_prefix = 'https://image-timemachine.epfl.ch/iiif/3/venice%2F3Dbuilding%2Ffigures%2F{folder}/{file_name}.png/full/max/0/default.jpg'
create_iiif_directory_if_not_exists()
man_list = {}
for group, sdf in df_man_edifici.groupby('uid'):
    vals = df_of_hr[df_of_hr['EDIFI_ID'] == group]
    if len(vals) == 0:
        print(f'Warning: no HR found for group {group}, skipping')
        continue
    man_label = vals['label_txt'].iloc[0]
    hr_uuid = vals['id'].iloc[0]
    man_uuid = str(uuid.uuid5(VTM_UUID5_NS, man_label))
    annots = []
    pages = []
    # putting the thumbnail of the 3d vision of the model as the first page:
    page_0 = iiif.generate_page_object(VTM_UUID5_NS, DS_UUID, 0, man_uuid,  "Thumbnail of the cloudpoint model", \
                                                f'venice/3Dbuilding/thumbnails/edifici_{int(group)}.png', "image/png", 512, 1024, 'en')
    pages.append(dict(page_0, metadata = [(hr_uuid, man_label)]))
    for i, (num, r) in enumerate(sdf.iterrows()):
        canvas_uuid = str(uuid.uuid5(VTM_UUID5_NS, r['filename']))
        page_obj = iiif.generate_page_object(VTM_UUID5_NS, DS_UUID, i+1, man_uuid,  r['filename'].replace('/', '').replace('.png', ''), \
                                                'venice/3Dbuilding/figures/' + r['folder'].replace('/', '') + '/' + r['filename'].replace('/', ''), r['media_type'], r['height'], r['width'], 'en')
        pages.append(page_obj)
    man_cont = iiif.generate_manifest_object(VTM_UUID5_NS, man_uuid, {'en': [man_label]}, 'en', pages, None)
    man_list[man_uuid] = (man_label, pages[0])
    with open(f'iiif/manifests/{man_uuid}.json', 'w+', encoding='utf-8') as f:
        json.dump(man_cont, f, indent=2, ensure_ascii=False)

collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
collection_label = {"en": ['Figures of facades and panoramas extracted from cloudpoints of venetian buildings']}
create_iiif_directory_if_not_exists()
with open(f'iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest(collection_manifest_uid, collection_label, man_list), f, indent=2, ensure_ascii=False)

format = "application/vnd.las"
df_of_hr['3d_filename'] = df_of_hr['metadata'].apply(lambda x: f"edifici_{x['EDIFI_ID']}.las")
man_3d_list = {}
for _, row in df_of_hr.iterrows():
    content = row['metadata']
    label = f"{content['aulic_name']}, {content['EDIFI_ID']} - {content['CIVICI']}"
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
collection_3d_label = {"en": ['Cloudpoints models in LAS format from all venetian buildings from contemporary data acquisition']}

with open(f'iiif/collections/{collection_3d_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest_no_thumbnail(collection_3d_manifest_uid, collection_3d_label, man_3d_list), f, indent=2, ensure_ascii=False)

# Produce dataset object
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

df.rename(columns={'volume [m3]': 'volume'}, inplace=True)

cols_of_interest = list(set(df.columns).difference(set(cols_of_non_interest)))

ds_conf, md = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS,
    df[cols_of_interest],
    CONF
)

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    '1.0',
    CONF['name'],
    [collection_manifest_uid],
    (min_time, max_time),
    0,
    ds_conf,
    md,
    venice_area_uuids
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'cloudpoints_dataset', RDEType.DATASET.value, is_dataset_obj=True)