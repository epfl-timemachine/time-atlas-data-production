import uuid
import pandas as pd
import geopandas as gpd
import os
from os.path import join
import sys
from tqdm import tqdm
from pathlib import Path
from datetime import datetime
# to have progress bar in the notebook
tqdm.pandas()

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

DORIGO_DATA_SRC = join(parent_dir, 'data-venice/Dorigo/')
DORIGO_DATA_PATH = Path(DORIGO_DATA_SRC)

CITATION_FMT = "Dorigo W. (2003) “Venezia romanica”. Cierre edizioni. P."

# aribtrary namespace, just to generate reproducible UUIDv5 from the entries of the dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])

DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
MAP_SLUG = f"{DS_SLUG}-map" # used for the map manifest, different from the map slug of the map itself.
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))
# cadastral layer uuid:
cadaster_layer_uuid = get_layer_uuid('../../maps/venice-dorigo/layers.json', 'venice-dorigo-map-zones') 
# so the same layer uuid is used between this dataset and the street network dataset
BEGIN_TR = 9460101
END_TR = 14081231
formatted_begin = datetime_obj_from_int_time(BEGIN_TR)
formatted_end = datetime_obj_from_int_time(END_TR, match_to_end=True)
TR_OBJ = [formatted_begin, formatted_end]
DATA_FOLDER = 'data'
venice_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

# Geometry RDE production
raimund_fmt = "%Y/%m/%d %H:%M:%S"
def format_raimund_dt(dt_str: str) -> str:
    return datetime.strptime(dt_str[:-3], raimund_fmt).isoformat() if dt_str and not pd.isnull(str) else dt_str

geometries_fp = list(DORIGO_DATA_PATH.rglob('*geometries.geojson'))[0]
# sample for testing uuid_gen
gdf = gpd.read_file(geometries_fp)
gdf = gdf.to_crs(UNIVERSAL_CRS)
gdf['start_time'] = gdf['start_date'].apply(format_raimund_dt).fillna(TR_OBJ[0])
gdf['end_time'] = gdf['end_date'].apply(format_raimund_dt).fillna(TR_OBJ[1])
# TODO: allow for multipolygon??
tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['id']), axis=1)
gdf['layer_uuid'] = cadaster_layer_uuid
gdf['rde_type'] = RDE.GEOM.value
QA_check_uuid_are_unique(gdf)

if not QA_check_all_geometries_are_valid(gdf, raise_exception=False):
    from shapely.validation import make_valid
    gdf['geometry'] = gdf['geometry'].apply(lambda g: g if g.is_valid else make_valid(g))
    QA_check_all_geometries_are_valid(gdf)


geom_shorthand = 'dorigo_geometries'
# "parcel_type" was removed for consistency with the other datasets. 
save_data_file_if_different(DATA_FOLDER, 'geometries', gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']], geom_shorthand, RDE.GEOM.value)
df = pd.read_json(list(DORIGO_DATA_PATH.rglob('*historical_records.json'))[0])
# fix NaN being serialized as literal in JSON alongside "null"
df = df.replace({np.nan: None})
df = df[~df['date_start'].isna()]

df['start_time'] = df['date_start'].astype(int).apply(datetime_obj_from_int_time)

def try_to_parse_date_end(date_end):
    try:
        return datetime_obj_from_int_time(date_end, match_to_end=True)
    except:
        print(f"Could not parse date_end: {date_end}")

df['end_time'] = df['date_end'].astype(int).apply(try_to_parse_date_end)
# direct IIIF sources with Dorigo is currently not advised as the data is under some rights limitation, instead we baked a bibliographical citation to the book in the data. 
with open(join(DORIGO_DATA_SRC, 'tables_manifest.json'), 'r') as f:
    tables_manifest = json.load(f)
tables_manifest

ids_pgs = {ann['id']: r['pages']  for r in tables_manifest for ann in r['annotations']}
df['pages'] = df['table_cell_ids'].apply(lambda ids: sorted(list(set(reduce(lambda a,b: a+b, [ids_pgs[id] for id in ids if id and id in ids_pgs], [])))))
df['bibliographic_citation'] = df['pages'].apply(lambda pgs: CITATION_FMT + '-'.join(map(str, pgs)))

# likely not the most optimized way to do it, but I had trouble wrapping my head around how to do it purely with pandas operations.
tqdm.pandas(desc="Merging geometries")
df['geometries'] = df['geometry_ids'].progress_apply(lambda vs: union_geom_from_geometry_ids_list(vs, gdf))
df['centroid'] = df['geometries'].apply(lambda g: g.centroid)
df['corrected_centroid'] = df.apply(lambda row: constraint_point_to_center_of_one_polygon(row['centroid'], row['geometries']), axis=1)
def find_uuid_in_gdf(id_list: list[str], gdf: gpd.GeoDataFrame) -> list[str]:
    return gdf[gdf['id'].isin(id_list)]['uuid'].tolist()

tqdm.pandas(desc="Propagating geometry uuid")
df['has_geometry'] = df['geometry_ids'].progress_apply(lambda ids: find_uuid_in_gdf(ids, gdf))
tqdm.pandas(desc="Generating UUIDs")
df['hr_uuid'] = df.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['id']), axis=1)
df['obs_uuid'] = df.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['id'], ad_hoc_seed='obs'), axis=1)
df['corrected_centroid_str'] = df['corrected_centroid'].progress_apply(lambda p: p.wkt)
df['poi_uuid'] = df.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['corrected_centroid_str'], ad_hoc_seed='poi'), axis=1)

# Producing PoIs
poi_df = df.groupby('corrected_centroid_str').agg(list)[['corrected_centroid','obs_uuid', 'poi_uuid']].reset_index()
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v['poi_uuid'][0], v['corrected_centroid'][0], v['obs_uuid']) for _, v in poi_df.iterrows()])
gdf_poi = gdf_poi.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
gdf_poi = gdf_poi.rename(columns={'coordinate': 'geometry'})

save_data_file_if_different(DATA_FOLDER, 'points_of_interest', gdf_poi, 'dorigo_pois', RDE.POI.value)
QA_check_uuid_are_unique(gdf_poi.reset_index())

QA_check_unique_uuid_in_uuid_array(gdf_poi.reset_index(), 'represents')

# Producing Obs.
obs_from_row = lambda v: produce_obs_obj(v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, v.type, v.corrected_centroid, v.has_geometry, v.poi_uuid)
obs = [obs_from_row(v) for _, v in df.iterrows()]
gdf_obs = gpd.GeoDataFrame(obs)
gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
# when the geodataframe is serialized, the label of the geometry column is lost (default to geometry), doing it here makes it explicit and make the save_data_file_if_different work.
gdf_obs = gdf_obs.rename(columns={'coordinate': 'geometry'})

QA_check_uuid_are_unique(gdf_obs.reset_index())
obs_shorthand = 'dorigo_obs'
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, obs_shorthand, RDE.OBS.value)

# Producing HRs
hr_metadata_cols = [
 'bibliographic_citation',
 'place_name',
 'owner_name',
 'owner_title',
 'owner_last_name',
 'owner_first_name',
 'owner_name_appendix',
 'date_comment',
 'source',
]

df['owner_name'] = df['owner_name'].fillna('Unknown owner')
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r['obs_uuid'], 'place_name']],\
                       (r.start_time, r.end_time),\
                       r.type,\
                       r[hr_metadata_cols].to_dict()) \
            for _, r in df.iterrows()
        ]

hr_shorthand = 'dorigo_historical_records'
save_data_file_if_different(DATA_FOLDER, 'historical_records',recs, hr_shorthand, RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')

# Producing dataset
CONF = DATA_CONFIG['DATASET_CONFIGURATION']

labels = CONF['labels']
filtered_df = df[hr_metadata_cols].copy()
remaining_vals = list(filtered_df.columns)
order = labels.keys()

ds_conf = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS,
    filtered_df[order],
    CONF["indexed"],
    CONF["short_display"],
    CONF["hidden"], 
    {},
    CONF["tagged_fields"],
    labels,
    main_label=CONF["main_label"],
    sub_label=CONF["sub_label"]
)
ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    '1.0',
    CONF["name"],
    CONF["description"],
    CONF["paradata"],
    [],
    TR_OBJ,
    0,
    ds_conf,
    [venice_area_uuid],
    publish_obj=(CONF["doi"], CONF["github_link"])
)

save_data_file_if_different(DATA_FOLDER,'datasets', [ds], 'dorigo_dataset', RDE.DATASET.value, is_dataset_obj=True)