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

def min_without_nan(series: pd.Series):
    return series.dropna().min()

def max_without_nan(series: pd.Series):
    return series.dropna().max()

MAP_FOLDER = '../../maps/venice-2024-contemporary/'
edifici_layer_uuid = get_layer_uuid(MAP_FOLDER+'layers.json', 'venice-2024-contemporary-map-edifici')
df = pd.read_json('src/sample_3_edifici.json')
# fix NaN being serialized as literal in JSON alongside "null"
df = df.replace({np.nan: None})
min_time = datetime_obj_from_int_time(int(min_without_nan(df['BeginDate'])))
max_time = datetime_obj_from_int_time(int(max_without_nan(df['EndDate'])), match_to_end=True)
df['start_time'] = df['BeginDate'].apply(lambda x: datetime_obj_from_int_time(int(x)) if not pd.isna(x) else min_time)
df['end_time'] = df['EndDate'].apply(lambda x: datetime_obj_from_int_time(int(x), match_to_end=True) if not pd.isna(x) else max_time)
df['author_birth_date_time'] = df['AuthorBirth'].apply(lambda x: datetime_obj_from_int_time(int(x)) if not pd.isnull(x) else x)
df['author_death_date_time'] = df['AuthorDeath'].apply(lambda x: datetime_obj_from_int_time(int(x)) if not pd.isnull(x) else x)
DATA_VENICE_FOLDER = os.path.join(parent_dir, 'data-venice')

# to note: all the geometries are expressde as multipolygon, but actually there is a single geometry in each. No need to do multiple geometries per obs a simple explode reduce them to single polygon.
df_edifici = gpd.read_file(os.path.join(DATA_VENICE_FOLDER, 'contemporary_maps/2024_Edifici_EPSG32633.geojson')).to_crs('EPSG:4326').explode()
gdf_edifici = df_edifici[['geometry', 'EDIFI_ID']].groupby('EDIFI_ID').first().reset_index()
df = df.merge(df_edifici[['geometry', 'EDIFI_ID']].set_index('EDIFI_ID'), on='EDIFI_ID')
gdf = gpd.GeoDataFrame(df, geometry='geometry').set_crs('EPSG:4326')
geom_begin = datetime_obj_from_int_time(20240101)
geom_end = datetime_obj_from_int_time(20241231, match_to_end=True)
gdf_geom = gdf[['geometry', 'EDIFI_ID']].groupby('EDIFI_ID').first().reset_index()
DATA_FOLDER = 'data'

venice_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

# Generating geometries
gdf_edifici['start_time'] = geom_begin
gdf_edifici['end_time'] = geom_end

tqdm.pandas(desc="Generating uuid from geometry")
gdf_edifici['uuid'] = gdf_edifici.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['EDIFI_ID']), axis=1)
# fetching only the uuid that matters for the current sample version of the dataset.
gdf_geom = gdf_geom.merge(gdf_edifici[['uuid', 'EDIFI_ID']], on='EDIFI_ID')
gdf_edifici['layer_uuid'] = edifici_layer_uuid
gdf_edifici['rde_type'] = RDE.GEOM.value
with open('edifici_id_to_geom_uuid.json', 'w+') as f:
    #if other dataset might need to point to the same geometries, this file can be used to correctly reference the uuids.
    json.dump(gdf_edifici.set_index('EDIFI_ID')['uuid'].to_dict(), f)
QA_check_uuid_are_unique(gdf_geom)

if not QA_check_all_geometries_are_valid(gdf_edifici, raise_exception=False):
    from shapely.validation import make_valid
    gdf_edifici['geometry'] = gdf_edifici['geometry'].apply(lambda g: g if g.is_valid else make_valid(g))
    QA_check_all_geometries_are_valid(gdf_geom)

geom_shorthand = 'cini-photographs_geometries'
# "parcel_type" was removed for consistency with the other datasets. 
save_data_file_if_different(MAP_FOLDER, 'geometries', gdf_edifici[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']].set_crs('EPSG:4326'), geom_shorthand, RDE.GEOM.value)
gdf['hr_uuid'] = gdf.apply(lambda x: make_uuid_from_row_selection(VTM_UUID5_NS, x, ['ImageNumber']), axis=1)
gdf['obs_uuid'] = gdf.apply(lambda x: make_uuid_from_row_selection(VTM_UUID5_NS, x, ['ImageNumber'], ad_hoc_seed='obs'), axis=1)

# Generating Obs
gdf['has_geometry'] = gdf.apply(lambda r: gdf_geom[gdf_geom['EDIFI_ID'] == r['EDIFI_ID']]['uuid'].values, axis=1)
gdf['type'] = 'photograph'
obs_from_row = lambda v: produce_obs_obj(v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, v.type, v.geometry.centroid, v.has_geometry)
obs = [obs_from_row(v) for _, v in gdf.iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})
gdf_obs = gdf_obs.set_geometry('geometry')
QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'cini_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDE.OBS.value)

#Produce HRs
cols_of_non_interest = [
    'geometry',
    'centroid',
    'hr_uuid',
    'obs_uuid',
    'has_geometry',
    'FondoStamp',
    'Country',
    'ImageNumber',
    'EDIFI_ID',
    'AuthorNeighbour',
    'CiniTime',
    'AuthorComplemented',
    'AuthorDeathLat',
    'AuthorDeathLong',
    'AuthorBirthLat',
    'AuthorBirthLong',
    'AuthorDeath',
    'AuthorBirth',
    'AuthorNeighbourhood',
    'AutorNeighbour',
    'AuthorComplement',
    'AuthorComplemented',
    'PhysicalID',
    'CiniTime',
    'City', #because it is always Venice
    'Country', #because it is always Italy
    'Reference', # too few values
    'archiType', # too few values
    'AuthorGender', # always male
    'AuthorNationality', # always Italian
    'uid', # redondant with other IDs
    'CardboardURL', # redondant with iiif source thingy
    'ImageURL', # redondant with iiif source thingy
    'archiComment', # always Palazzi
    'archiLikelyType', # always Photographical.
    'AuthorULAN', # redondant with AuthorURL
    'AuthorULANLabel', # redondant with AuthorURL
    'CiniNumber', # not relevant. (different from CINI_ID)
    'BeginDate', # redondant with start_time
    'EndDate', # redondant with end_time
    'uidMorph'
]

recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r['obs_uuid'], 'place_name']],\
                       (r.start_time, r.end_time),\
                       r.type,\
                       r[gdf.columns.difference(cols_of_non_interest)].to_dict()) \
            for _, r in gdf.iterrows()
        ]

hr_shorthand = 'cini_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')

# Source Production
url_prefix = 'https://image-timemachine.epfl.ch/iiif/3/venice%2Fcini%2Fcardboards%2F{drawer}%2F{CINI_ID}.jpg/full/max/0/default.jpg'

all_wh_data = Path('src/img_wh/').rglob('*.csv')

def read_csv_and_patch_folder_name(f:Path) -> pd.DataFrame:
    folder_name = str(f).split('_')[-1].replace('.csv','')
    df = pd.read_csv(f)
    df['filename'] = df['filename'].apply(lambda x: f'/{folder_name}/{x}')
    return df

df_wh = reduce(lambda x,y: pd.concat([x,y]), [read_csv_and_patch_folder_name(f) for f in all_wh_data], pd.DataFrame())

gdf['filename'] = gdf.apply(lambda r: f'/{r["Drawer"]}/{r["CINI_ID"]}.jpg', axis=1)
gdf['filename'].isin(df_wh['filename']).value_counts()
gdf['annotation_txt'] = gdf.apply(lambda s: f"{s['BUILDING_NAME']} | {s['CiniNumber']}", axis=1)
df_wh = df_wh.merge(gdf[['filename', 'hr_uuid', 'Drawer', 'annotation_txt']].set_index('filename'), on='filename')
man_uuids_and_cont = {}
for g, sdf in df_wh.groupby('Drawer'):
    man_uuid = str(uuid.uuid5(VTM_UUID5_NS, g))
    annots = []
    pages = []
    for num, r in sdf.reset_index().iterrows():
        canvas_uuid = str(uuid.uuid5(VTM_UUID5_NS, r['filename']))
        page_obj = iiif.generate_page_object(VTM_UUID5_NS, DS_UUID, num, man_uuid,  r['annotation_txt'], \
                                             'venice/cini/cardboards' +r['filename'],r['media_type'], r['height'], r['width'], 'en')
        # annotation done with the "metadata" tag. Weird.
        pages.append(dict(page_obj, metadata =[(r['hr_uuid'], r['annotation_txt'])]))
    man_uuids_and_cont[man_uuid] = (iiif.generate_manifest_object(VTM_UUID5_NS, man_uuid, {'en': ['Cardboards Photographs from Cini\'s Foundation: '+g]}, 'en', pages, None), pages[0])

for uid,(man,_) in man_uuids_and_cont.items():
    with open(f'data/iiif/manifests/{uid}.json', 'w+', encoding='utf-8') as f:
        json.dump(man, f, indent=2)
collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
collection_label = {"en": ['Cini\'s Foundation: Photographs of 3 Venetian Buildings (test sample)']
                    }
man_and_label = {k: (v[0]['label']['en'][0], v[1]) for k,v in man_uuids_and_cont.items()}
with open(f'data/iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest(collection_manifest_uid, collection_label, man_and_label), f, indent=2, ensure_ascii=False)

# Produce dataset object
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
cols_of_interest_ordered = [
        'BUILDING_NAME', 'Author','Description', 
        'AuthorBirthCity', 'AuthorDeathCity', 'AuthorOriginal',
        'AuthorURL', 'BiographyLabel', 'CINI_ID',
       'CiniCollection', 'Drawer', 'Institution',
       'SimpleCollection', 'author_birth_date_time', 'author_death_date_time',
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

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'cini_dataset', RDE.DATASET.value, is_dataset_obj=True)