import uuid
import pandas as pd
import geopandas as gpd
import os
import sys
from tqdm import tqdm
# to have progress bar in the notebook
tqdm.pandas()

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils import iiif
from utils.rde import RDE

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))

edifici_list = '''edifici_1.las
edifici_1009.las
edifici_1010.las
edifici_1014.las
edifici_1017.las
edifici_1027.las
edifici_1030.las
edifici_1033.las
edifici_1034.las
edifici_1039.las
edifici_1097.las
edifici_1113.las
edifici_1115.las
edifici_1136.las
edifici_1143.las
edifici_1149.las
edifici_1151.las
edifici_1153.las
edifici_1161.las
edifici_1163.las
edifici_1194.las
edifici_1197.las
edifici_1214.las
edifici_1235.las
edifici_1271.las
edifici_1277.las
edifici_1278.las
edifici_1286.las
edifici_1295.las
edifici_1297.las
edifici_1306.las
edifici_1308.las
edifici_1310.las
edifici_1319.las
edifici_1321.las
edifici_1327.las
edifici_1329.las
edifici_1351.las
edifici_1373.las
edifici_1465.las
edifici_1496.las
edifici_1498.las
edifici_1522.las
edifici_1571.las
edifici_16.las
edifici_22.las
edifici_30.las
edifici_497.las
edifici_498.las
edifici_679.las
edifici_711.las
edifici_921.las
edifici_922.las
edifici_923.las
edifici_925.las
edifici_930.las
edifici_931.las
edifici_933.las
edifici_936.las
edifici_939.las
edifici_941.las
edifici_963.las
edifici_6382.las'''

min_time = datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM'])
max_time = datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True)
edifici_layer_uuid = get_layer_uuid('../../maps/venice-2024-contemporary/layers.json', 'venice-2024-contemporary-map-edifici')
ids_of_interests = [v.replace('edifici_', '').replace('.las', '') for v in edifici_list.split('\n')]
DATA_VENICE_FOLDER = os.path.join(parent_dir, 'data-venice')

# to note: all the geometries are expressde as multipolygon, but actually there is a single geometry in each. No need to do multiple geometries per obs a simple explode reduce them to single polygon.
df_edifici = gpd.read_file(os.path.join(DATA_VENICE_FOLDER, 'contemporary_maps/2024_Edifici_EPSG32633.geojson')).to_crs('EPSG:4326').explode()
df_edifici['EDIFI_ID'] = df_edifici['EDIFI_ID'].astype(str)

col_of_interest = ['geometry', 'EDIFI_ID', 'names', 'CIVICI', 'wikipedia', 'wikidata']

df = df_edifici[df_edifici['EDIFI_ID'].isin(ids_of_interests)].copy().set_crs('EPSG:4326')[col_of_interest]

df['display_name'] = df.apply(lambda r: r['CIVICI'] if r['CIVICI'] else r['names'] if r['names'] else 'Unnamed building', axis=1)
df['start_time'] = min_time
df['end_time'] = max_time
DATA_FOLDER = 'data'

venice_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

with open('../venice-cini-photographs/edifici_id_to_geom_uuid.json') as f:
    edifici_id_to_geom_uuid = json.load(f)

df['geometry_uuid'] = df['EDIFI_ID'].map(edifici_id_to_geom_uuid)
df['has_geometry'] = df['geometry_uuid'].apply(lambda r: [r])

df['hr_uuid'] = df.apply(lambda x: make_uuid_from_row_selection(VTM_UUID5_NS, x, ['EDIFI_ID']), axis=1)
df['obs_uuid'] = df.apply(lambda x: make_uuid_from_row_selection(VTM_UUID5_NS, x, ['geometry'], ad_hoc_seed='obs'), axis=1)
df['poi_uuid'] = df.apply(lambda x: make_uuid_from_row_selection(VTM_UUID5_NS, x, ['geometry'], ad_hoc_seed='poi'), axis=1)
# Generating PoIs
poi_df = df.groupby('EDIFI_ID').agg(list)[['geometry', 'obs_uuid', 'poi_uuid']].reset_index()
# this weird contraption to get the .centroid of the first geometry properly without getting the warning about no crs projected
poi_rec = gpd.GeoDataFrame([[v['poi_uuid'][0], v['geometry'][0], v['obs_uuid']] for _, v in poi_df.iterrows()], columns=['poi_uuid', 'geometry', 'obs_uuid']).set_geometry('geometry').set_crs('EPSG:4326')
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v['poi_uuid'], v.geometry.centroid, v['obs_uuid']) for _, v in poi_rec.iterrows()]).set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_poi = gdf_poi.rename(columns={'coordinate': 'geometry'})
gdf_poi.rename(columns={'poi_uuid': 'uuid'}, inplace=True)
gdf_poi = gdf_poi.set_geometry('geometry')
save_data_file_if_different(DATA_FOLDER, 'points_of_interest', gdf_poi, 'mockup_3d_buildings_pois', RDE.POI.value)
QA_check_uuid_are_unique(gdf_poi.reset_index())

QA_check_unique_uuid_in_uuid_array(gdf_poi.reset_index(), 'represents')

# Generating Obs
df['type'] = '3d-structure'
obs_from_row = lambda v: produce_obs_obj(v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, v.type, v.geometry.centroid, v.has_geometry, v.poi_uuid)
obs = [obs_from_row(v) for _, v in df.iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})
gdf_obs = gdf_obs.set_geometry('geometry')
QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'mockup_3d_buildings_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDE.OBS.value)

#Produce HRs
cols_of_non_interest = [
    'geometry',
    'centroid',
    'hr_uuid',
    'obs_uuid',
    'poi_uuid',
    'has_geometry',
    'geometry_uuid'
]

recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r['obs_uuid'], 'EDIFI_ID']],\
                       (r.start_time, r.end_time),\
                       r.type,\
                       r[df.columns.difference(cols_of_non_interest)].to_dict()) \
            for _, r in df.iterrows()
        ]

hr_shorthand = 'mockup_3d_buildings_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')


# Source Production
url_prefix = 'https://image-timemachine.epfl.ch/iiif/3/venice%2F3Dbuilding%2Fsample_screenshots%2Fedifici_{EDIFI_ID}.png/full/max/0/default.jpg'


df['filename'] = df.apply(lambda r: f'edifici_{r["EDIFI_ID"]}.png', axis=1)
df['annotation_txt'] = df.apply(lambda s: f"{s['display_name']} | {s['EDIFI_ID']}", axis=1)
df['media_type'] = 'image/png'
df['height'] = 600
df['width'] = 1024
man_label = 'manifest of a sample of screenshots of 3D buildings for mockup purpose'
man_uuid = str(uuid.uuid5(VTM_UUID5_NS,man_label))
annots = []
pages = []
df = df.sort_values('EDIFI_ID')
for num, r in df.reset_index().iterrows():
    canvas_uuid = str(uuid.uuid5(VTM_UUID5_NS, r['filename']))
    page_obj = iiif.generate_page_object(VTM_UUID5_NS, DS_UUID, num, man_uuid,  r['annotation_txt'], \
                                            'venice/3Dbuilding/sample_screenshots/' +r['filename'],r['media_type'], r['height'], r['width'], 'en')
    # annotation done with the "metadata" tag. Weird.
    pages.append(dict(page_obj, metadata =[(r['hr_uuid'], r['annotation_txt'])]))
man_cont = iiif.generate_manifest_object(VTM_UUID5_NS, man_uuid, {'en': [man_label]}, 'en', pages, None)

with open(f'data/iiif/manifests/{man_uuid}.json', 'w+', encoding='utf-8') as f:
    json.dump(man_cont, f, indent=2)
collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
collection_label = {"en": ['Screenshots of 3d models of 63 Venetian Buildings (test sample)']
                    }

man_list = {man_uuid: (man_label, pages[0])}

with open(f'data/iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest(collection_manifest_uid, collection_label, man_list), f, indent=2, ensure_ascii=False)

# Produce dataset object
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
cols_of_interest_ordered = [
    'display_name','names','wikidata', 'wikipedia', 'CIVICI', 'EDIFI_ID', 
]

ds_conf = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS,
    df[cols_of_interest_ordered],
    CONF["indexed"],
    CONF["short_display"],
    CONF["hidden"], 
    {},
    CONF["tagged_fields"],
    CONF["labels"],
    CONF["main_label"],
    CONF["sub_label"],
    display_thumbnail=True
)

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    '1.0',
    CONF['name'],
    CONF['description'],
    CONF['paradata'],
    [collection_manifest_uid],
    (min_time, max_time),
    0,
    ds_conf,
    [venice_area_uuid],
    publish_obj=(None, CONF['github_link']),
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], '3dbuilding_mockup_dataset', RDE.DATASET.value, is_dataset_obj=True)
