import json
from tqdm.notebook import tqdm 
import pandas as pd

with open('src/WebAnnotationModel-2500-sample-results.json', 'r') as f:
    cont25 = json.load(f)

with open('src/wam_22k_results_internal.json', 'r') as f:
    cont22k = json.load(f)

cont = cont25 + cont22k

def flatten(li: list) -> list:
    return [item for sublist in li for item in sublist]

def extract_value_from_textual_body_with_semantic_prefix(purpose, value, sample):
    bodies = sample['body']
    for b in bodies:
        if b.get('purpose', None) == purpose and b.get('type', None) == 'TextualBody' and b.get('value', '').startswith(f'{value}:'):
            return b.get('value', '').replace(f'{value}: ', '')
    return None 

def extract_value_from_type_with_purpose(tpe, purpose, sample, str_cont = None):
    bodies = sample['body']
    for b in bodies:
        if b.get('type', None) == tpe and b.get('purpose', None) == purpose and (str_cont is None or str_cont in b.get('value', '')):
            return b.get('value', '')
    return None

def extract_value_from_textual_body_with_purpose(purpose, sample):
    return extract_value_from_type_with_purpose("TextualBody", purpose, sample)

def extract_target_img(sample):
    if sample.get('target', {}).get('type', None) == 'Image':
        return sample.get('target', {}).get('id', None)
    return None

def extract_dataset_tavily_results_in_array(sample):
    bodies = sample['body']
    res = []
    for b in bodies:
        if b.get('type', None) == 'Dataset' and b.get('purpose', None) == "searching":
            for entry in b.get('value', []):
                if 'search query' in entry.get('type', ''):
                    res.append('Query: ' + entry.get('value', ''))
                elif 'search result' in entry.get('type', ''):
                    res.append(f"Result: {entry.get('value', '')} - {entry.get('source', '')}")
    return res

def extract_google_search_results(sample):
    bodies = sample['body']
    res = []
    for b in bodies:
        if b.get('type', None) == 'Dataset' and b.get('purpose', None) == "linking":
            for entry in b.get('value', []):
                if 'Partial match' in entry.get('type', ''):
                    res.append(f"Partial match: {entry.get('value', '')} - {entry.get('source', '')}")
                elif 'Full match' in entry.get('type', ''):
                    res.append(f"Full match: {entry.get('value', '')} - {entry.get('source', '')}")
    return res

def extract_google_coordinates(sample):
    bodies = sample['body']
    res = []
    for b in bodies:
        if b.get('type', None) == 'Dataset' and b.get('purpose', None) == "linking":
            for entry in b.get('value', []):
                if coords := entry.get('object_coordinates', None):
                    if isinstance(coords[0], list) and isinstance(coords[0][0], list):
                        res.append(flatten(coords))
                    else:
                        res.append(coords)
    return res if len(res) >= 1 else None

def extract_landmark_information(sample):
    bodies = sample['body']
    res = []
    for b in bodies:
        if b.get('type', None) == 'Dataset' and b.get('purpose', None) == "identifying":
            for entry in b.get('value', []):
                if 'Landmark' in entry.get('type', ''):
                    val_str = entry.get('value', '')
                    if wd_id := entry.get('wikidata_id', None):
                        val_str += f" (https://www.wikidata.org/wiki/{wd_id})"
                    res.append(val_str)
    return res

def extract_landmark_coordinates(sample):
    bodies = sample['body']
    res = []
    for b in bodies:
        if b.get('type', None) == 'Dataset' and b.get('purpose', None) == "identifying":
            for entry in b.get('value', []):
                if coords := entry.get('coordinates', None):
                    res.append(coords)
    return res if len(res) >= 1 else None

json_path_parse_dict = {
    "is_postcard": lambda s: extract_value_from_textual_body_with_semantic_prefix("classifying", "postcard", s),
    "back_postcard": lambda s: extract_value_from_textual_body_with_semantic_prefix("classifying", "postcard's back", s),
    "final_place": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "final_place", s),
    "final_country": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "final_country", s),
    "final_city": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "final_city", s),
    "filename": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "filename", s),
    "record_id": lambda s: extract_value_from_textual_body_with_semantic_prefix("identifying", "record_id", s),
    "description": lambda s: extract_value_from_textual_body_with_purpose("describing", s),
    "transcription": lambda s: extract_value_from_textual_body_with_purpose("transcribing", s),
    "date": lambda s: extract_value_from_textual_body_with_purpose("dating", s),
    "europeana_link": lambda s: extract_value_from_type_with_purpose("SpecificResource", "linking", s, "europeana.eu"),
    "rights_attribution": lambda s: extract_value_from_type_with_purpose("SpecificResource", "tagging", s),
    "reason": lambda s: extract_value_from_textual_body_with_purpose("commenting", s),
    "img_src": extract_target_img,
    # "tavily": extract_dataset_tavily_results_in_array,
    "google_search": extract_google_search_results,
    "google_coordinates": extract_google_coordinates,
    "landmarks_identified": extract_landmark_information,
    "landmarks_coordinates": extract_landmark_coordinates
}

sampled_values = []
sampled_vals_25 = []
sampled_vals_22k = []
for s in cont:
    vals = {}
    for k, v in json_path_parse_dict.items():
        vals[k] = v(s)
    sampled_values.append(vals)

# only for debuggin purpose in the union of the two datasets. 
for s in cont25:
    vals = {}
    for k, v in json_path_parse_dict.items():
        vals[k] = v(s)
    sampled_vals_25.append(vals)

for s in cont22k:
    vals = {}
    for k, v in json_path_parse_dict.items():
        vals[k] = v(s)
    sampled_vals_22k.append(vals)

df22k = pd.DataFrame(sampled_vals_22k)
df25 = pd.DataFrame(sampled_vals_25)

df = pd.DataFrame(sampled_values)
# all HR will at least have an observation at the level of the city. 
df = df[df['final_country'].notna() & df['final_city'].notna()]


with open('src/cached_city_country_loc.json', 'r') as f:
    city_country_loc = json.load(f)

with open('src/city_country_old_to_new.json', 'r') as f:
    city_country_old_to_new = json.load(f)

df['country_city'] = df['final_country'] + ', ' + df['final_city']
df['country_city'].to_csv('src/country_city_all_postcards.csv', index=False)
df['country_city_coordinates'] = df['country_city'].apply(lambda s: city_country_loc.get(s if not s in city_country_old_to_new else city_country_old_to_new[s], None))
# keeping only postcards that we can actually display on the timeatlas (i.e. with at least one coordinate source and a date)
df = df[(df['landmarks_coordinates'].notna() | df['google_coordinates'].notna() | df['country_city_coordinates'].notna()) & df['date'].notna()]
# print(len(df), "postcards with geolocation and date information.")
df = df[~df['record_id'].str.contains('S_TEK_photo_TEKA0221776')]
# print(len(df), "removing the webp stuff.")

df_wh_25 = pd.read_csv('src/2500_imgs_width_height.csv')
df_wh_22k = pd.read_csv('src/27k_image_width_height_format.csv')
df_wh = pd.concat([df_wh_25, df_wh_22k], ignore_index=True)
df_wh['filename'] = df_wh['filename'].apply(lambda v: v.split('/')[-1])
df_wh['width'] = df_wh['width'].astype(int)
df_wh['height'] = df_wh['height'].astype(int)
import numpy as np
needing_to_compute_bbox_extent = True
if needing_to_compute_bbox_extent:
    all_coordinates = flatten(df['landmarks_coordinates'].dropna().tolist() + [flatten(v) for v in df['google_coordinates'].dropna().tolist()])

    max_lat = max([coord[1] for coord in all_coordinates])
    min_lat = min([coord[1] for coord in all_coordinates])
    max_lon = max([coord[0] for coord in all_coordinates])
    min_lon = min([coord[0] for coord in all_coordinates])

    print('Max point:', (max_lon, max_lat))
    print('Min point:', (min_lon, min_lat))

    import uuid
import pandas as pd
import geopandas as gpd
from datetime import datetime as dt
import os
import sys
from tqdm import tqdm
from shapely import Point
# to have progress bar in the notebook
tqdm.pandas()

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from timeatlas.data_modeling import *
from timeatlas.RDEModel import RDEType
from pathlib import Path

gpd.options.io_engine = "pyogrio"

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

# arbitrary namespace, just to generate reproducible UUIDv5 from the data of this dataset.
TM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])

DATA_FOLDER = 'data'
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(TM_UUID5_NS, DS_SLUG))
DS_OBJ = (DS_SLUG, DS_UUID)
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))

europeana_area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

#all the date are in the format of "1910s" so decades.
def format_single_date_elem(date_elem):
    if pd.isna(date_elem):
        return None
    date_elem = date_elem.replace('s', '')
    # if the date starts with 0, it means that the exact date is not known, so we assume the whole year
    year = int(date_elem)
    begin = dt(year, 1, 1)
    end = dt(year+10, 12, 31, 23, 59, 59)
    return (begin.isoformat(), end.isoformat())

df['start_time'], df['end_time']= zip(*df['date'].apply(format_single_date_elem))

# split the dataset into two: one with duplicates record_id and one without duplicates record_id. The duplicates will be processed to have a single entry
# for each record_id, merging the information from the different postcards (front and back).
df_dup = df[df.duplicated(subset=['record_id'], keep=False)].sort_values(by=['record_id']).copy()
# splitting the dataset from any entries that had a duplicate:
df_no_dup = df[~df['record_id'].isin(df_dup['record_id'].unique())].copy()
df_dup_grouped = df_dup.groupby('record_id')
def generate_single_row_from_postcard_group(rows: pd.DataFrame) -> pd.Series:
    # taking the postcard that is not a back postcard as the main entry
    first_entry = rows[rows['back_postcard'] == 'no'].iloc[0].copy()
    country_city_coords = first_entry['country_city_coordinates']
    if country_city_coords is None:
        # try to get it from other entries
        for idx, r in rows.iterrows():
            if r['country_city_coordinates'] is not None:
                country_city_coords = r['country_city_coordinates']
                break
    first_entry['landmarks_coordinates'] = flatten(rows['landmarks_coordinates'].dropna().tolist())
    first_entry['google_coordinates'] = flatten(rows['google_coordinates'].dropna().tolist())
    first_entry['country_city_coordinates'] = country_city_coords
    filenames = rows.sort_values(by=['back_postcard'])['filename'].unique().tolist()
    first_entry['filename'] = filenames
    return first_entry

df_dup_processed = df_dup_grouped.apply(generate_single_row_from_postcard_group).reset_index(drop=True)
df_no_dup['filename'] = df_no_dup['filename'].apply(lambda s: [s])
df = pd.concat([df_no_dup, df_dup_processed], ignore_index=True)

tqdm.pandas(desc="Generating hr uuid")
df['hr_uuid'] = df.apply(lambda r: make_uuid_from_row_selection(TM_UUID5_NS, r, ['record_id']), axis=1)

remove_rec_id = [
    'bib_rnod_278752', # that portugal one who ended up everywhere in englsih countries
    'PMRMaeyaert_8321bdedf13106db26fe67c243765281938d1eb3' # the Rome one. 
]
df = df[~df['record_id'].isin(remove_rec_id)]

def get_all_coordinates_from_row(row):
    coords = []
    if isinstance(row['landmarks_coordinates'], list):
        coords.extend(row['landmarks_coordinates'])
    if isinstance(row['google_coordinates'], list):
        coords.extend(flatten(row['google_coordinates']))
    return coords

df['coordinates'] = df.apply(get_all_coordinates_from_row, axis=1)
df['coordinates'] = df['coordinates'].apply(lambda v: pd.Series(v).drop_duplicates().tolist())

def quick_uuid(hr_uuid:str, coords:str) -> str: 
    return str(uuid.uuid5(TM_UUID5_NS, f'{hr_uuid}-{coords}')) 

# need to split between obs that actually have street level geolocatin, and as such will have POIs. 
df_precise_coords = df[df['coordinates'].apply(len) > 0].copy()
df_precise_coords.to_csv('geolocated_postcards.csv', index=False)
# the "no precise coords" are the ones that will only have the city level geolocation, will still have observations ang get triggered by reserach, but no POIs.s
df_no_precise_coords = df[df['coordinates'].apply(len) == 0].copy()
df_no_precise_coords['coordinates'] = df_no_precise_coords['country_city_coordinates'].apply(lambda v: [v])

tpe='postcard'
def produce_obs_gdf(df:pd.DataFrame, need_poi:bool=True) -> gpd.GeoDataFrame:
    tqdm.pandas(desc="Generating obs uuid")
    df['obs_data'] = df.apply(lambda r: [(c, quick_uuid(r['hr_uuid'], c)) for c in r['coordinates']], axis=1)
    df_obs = df[['obs_data', 'hr_uuid', 'start_time', 'end_time']].copy().explode('obs_data')
    df_obs['lat_lon'], df_obs['obs_uuid'] = df_obs['obs_data'].apply(lambda x: x[0]), df_obs['obs_data'].apply(lambda x: x[1])
    df_obs = df_obs.drop(columns=['obs_data'])
    df_obs['geometry'] = df_obs['lat_lon'].apply(lambda v: Point(v[1], v[0]))
    gdf = gpd.GeoDataFrame(df_obs.drop('lat_lon', axis=1)).set_geometry('geometry')
    gdf = gdf.set_crs('EPSG:4326').reset_index()
    obs = [produce_obs_obj(
        v.obs_uuid, (v.start_time, v.end_time), DS_UUID, v.hr_uuid, tpe, v.geometry, None, need_poi=need_poi
    ) for _,v in gdf.iterrows()]

    gdf_obs = gpd.GeoDataFrame(obs)
    gdf_obs = gdf_obs.set_geometry('coordinate').set_crs('EPSG:4326').set_index('uuid')
    return gdf_obs

gdf_obs_precise = produce_obs_gdf(df_precise_coords)
gdf_obs_no_precise = produce_obs_gdf(df_no_precise_coords, need_poi=False)
gdf_obs = pd.concat([gdf_obs_precise, gdf_obs_no_precise], ignore_index=False)
print(f'Total number of observations generated: {len(gdf_obs)}')
QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, "observations", gdf_obs, f'europeana_postcards_obs', RDEType.OBS.value)

filename_to_wh_infos = {}
for idx, row in df_wh.iterrows():
    filename_to_wh_infos[row['filename']] = {
        'width': row['width'],
        'height': row['height'],
        'format': row['format'] if 'format' in row else 'media/jpeg'
    }

from utils.iiif import *
# Generating the IIIF manifests
df['image_fp'] = df['filename'].apply(lambda v: f'europeana/postcards/{v}')
man_list = {}
for i, row in tqdm(df.iterrows(), total=len(df), desc="Generating IIIF manifests"):
    manifest_uuid = make_uuid_from_row_selection(TM_UUID5_NS, row, ['record_id'], ad_hoc_seed='postcard_manifest')
    description = row['description']
    pages_obj = []
    if len(row['filename']) == 0:
        continue
    for fname in row['filename']:
        if fname.endswith('.webp'):
            fname = fname.replace('.webp', '.jpg')
        wh_info = filename_to_wh_infos.get(fname, None)
        if wh_info is not None:
            width, height = wh_info['width'], wh_info['height']
            media_type = wh_info['format']
            pages_obj.append(generate_page_object(
                TM_UUID5_NS,
                DS_UUID,
                0,
                manifest_uuid,
                description,
                f'europeana/postcards/{fname}',
                media_type,
                height,
                width,
                'en',
                metadata=[[row['hr_uuid'], description]],
                external_resource=row['europeana_link']))
        else:
            print(f'Warning: no width/height info for file {fname}')
            continue
    man = generate_manifest_object(TM_UUID5_NS, manifest_uuid, {'en':[description]},'en', pages_obj)
    with open(f'data/iiif/manifests/{manifest_uuid}.json', 'w') as f:
        f.write(json.dumps(man, indent=2, ensure_ascii=False))
    man_list[manifest_uuid] = ({"en":[description]}, pages_obj[0])

hr_uuid_to_obs_uuid = {}
for _, row in tqdm(gdf_obs.reset_index().iterrows(), total=len(gdf_obs), desc="Mapping hr_uuid to obs_uuid"):
    if row['documented_in'] not in hr_uuid_to_obs_uuid:
        hr_uuid_to_obs_uuid[row['documented_in']] = []
    hr_uuid_to_obs_uuid[row['documented_in']].append(row['uuid'])

    # generating the collection
collection_uuid = str(uuid.uuid5(TM_UUID5_NS, f'{DS_SLUG}_collection'))
collection_obj = generate_collection_manifest(
    collection_uuid,
    {'en': [f'{len(man_list)} geolocated postcards from Europeana. Data retrieved from Europeana. Geolocation process done at EPFL.']},
    man_list)
with open(f'data/iiif/collections/{collection_uuid}.json', 'w') as f:
    f.write(json.dumps(collection_obj, indent=2, ensure_ascii=False))

remove_cols_from_hr = [
    'back_postcard', # is always no when referenced.
    'europeana_link', # will be put in manifest in special field
    'google_coordinates', # used for observation/PoIs placements
    'landmarks_coordinates', # used for observation/PoIs placements
    'filename', # for locating the files.
    'is_postcard', # always yes
    'country_city', # intermediate field
    'country_city_coordinates', # intermediate field
    # 'record_id', # europeana internal id
    'coordinates',
    "image_fp"
]


df_hr = df.copy().drop(columns=remove_cols_from_hr)

df_hr['obs_uuid'] = df_hr['hr_uuid'].map(hr_uuid_to_obs_uuid)
df_hr = df_hr.replace({np.nan: None})
tpe = 'postcard'

recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                   [[v, 'Monuments'] for v in r.obs_uuid] ,\
                       (r.start_time, r.end_time),\
                       tpe, \
                   r.drop(labels = ['hr_uuid', 'obs_uuid', 'start_time', 'end_time', 'rights_attribution']).to_dict(),
                   r['rights_attribution'],
                   'a'
                   ).to_dict(flatten_metadata=False) \
                   for _, r in df_hr.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'europeana_postcards_hrs', RDEType.HR.value)

df_of_hr = pd.DataFrame(data = recs)

QA_check_uuid_are_unique(df_of_hr)
# QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents') # disabled because of "Monuments" being the same field of origin for both obs uuuid.

# Dataset RDE Object production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
filtered_df = df_hr.drop(columns=['hr_uuid', 'obs_uuid'])
order = CONF['labels'].keys()
ds_conf = produce_configuration_file_from_metadata_df(
    TM_UUID5_NS,
    filtered_df[order],
    CONF
)

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    "1.0",
    CONF['name'],
    [collection_uuid],
    TR_OBJ,
    0,
    ds_conf,
    europeana_area_uuids,
)

save_data_file_if_different(DATA_FOLDER,'datasets',[ds], f'europeana_postcards_dataset', RDEType.DATASET.value, is_dataset_obj=True)