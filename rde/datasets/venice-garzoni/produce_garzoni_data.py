import uuid
import pandas as pd
import geopandas as gpd
import sys
import os
from os.path import join
from tqdm import tqdm
from shapely import Point
from datetime import datetime as dt
# to have progress bar in the notebook
tqdm.pandas()

# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE
from utils import iiif

gpd.options.io_engine = "pyogrio"

with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

VENICE_DATA_SRC = join(parent_dir, 'data-venice')
GARZONI_DATA_SRC = join(VENICE_DATA_SRC, 'data-alignment/Garzoni/')

# aribtrary namespace, just to generate reproducible UUIDv5 from the data of this dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))
DS_OBJ = (DS_UUID, DS_SLUG)

DATA_FOLDER = 'data'
TR_OBJ = (datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM']), datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True))
man_id = str(uuid.uuid5(VTM_UUID5_NS, f"manifest_{DS_SLUG}"))
PAR_TR_OBJ = (datetime_obj_from_int_time(17400101), datetime_obj_from_int_time(17401231, match_to_end=True))
collection = {man_id: "Garzoni 3 page sample for testing annotations."}
collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
MAP_FOLDER = '../../maps/venice-1740-parish/'
parish_layer_uuid = get_layer_uuid(get_filepath_like(MAP_FOLDER+'layers', 'json'), 'parish')
venice_area_uuids = get_area_uuids_from_slugs('../../areas/data', DATA_CONFIG['AREA_SLUGS'])

# Geometry RDE production
gdf = gpd.read_file(join(VENICE_DATA_SRC, '1740_redrawn_parishes_cleaned_wikidata_standardised.geojson'))
gdf['id'] = gdf['id'].astype(int)

# adding the sestiere since we have it thanks to wikidata reconciliation on the geometries file.
sestiere_to_acronym = {
    "Castello": "CS",
    "Cannaregio": "CN",
    "S.Marco": "SM",
    "Dorsoduro": "DD",
    "S. Croce": "SC", 
    "S. Polo": "SP",
    "San Marco": "SM"
}

gdf['district_acronym'] = gdf['SESTIERE'].apply(lambda v: sestiere_to_acronym[v]) 
gdf['start_time'] = pd.Series(data = [PAR_TR_OBJ[0]] * len(gdf), name='start_time')
gdf['end_time'] = pd.Series(data = [PAR_TR_OBJ[1]] * len(gdf), name='end_time')

tqdm.pandas(desc="Generating uuid from geometry")
gdf['uuid'] = gdf.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['geometry']), axis=1)
gdf['layer_uuid'] = parish_layer_uuid
gdf['rde_type'] = "geometry"

save_gdf = gdf[['uuid', 'geometry', 'start_time', 'end_time', 'layer_uuid', 'rde_type']]

save_data_file_if_different(MAP_FOLDER,'geometries', save_gdf, f'garzoni_geometries', RDE.GEOM.value)
QA_check_uuid_are_unique(gdf)

print('loading garzoni data into a dataframe, this may take a while.')
garzoni_fp = join(GARZONI_DATA_SRC, 'contracts_20240409_180544.xlsx')
#large dataset, I load it separately for ease of computation in the next cell
contracts = pd.read_excel(garzoni_fp, engine='openpyxl', sheet_name="Person Mentions")
people_mentions = contracts[~contracts['Workshop - Parish'].isna()]
# some assesments on the data:
# - the apprenticeships workshops place are always the same as the one of the master, whenever both information are present.
# - However this information very often differs between Guarantor, Master and Other tags. => have to make them separated in the HR.  
def short_person_string_from_elems(full_name:str,
                                   gender:str, 
                                   age:int,
                                   origin:str) -> str:
    base = f"{full_name}, {gender.lower().replace('grz:', '')}"
    if age and type(age) == int:
        base += f", {age}"
    if origin and type(origin) == str and len(origin) > 0:
        base += f", {origin}"
    return base

location_cols_primitive = ['Workshop - Parish', 'Workshop - Insigna']
location_cols = [f'{v} {k}' for k in location_cols_primitive for v in ['Master', 'Guarantor', 'Other']]

roles  = ['Apprentice', 'Master', 'Guarantor', 'Other']
def group_to_individual_mentions(k:str, group:pd.DataFrame) -> pd.Series:
    vals = {
        "Contract ID": k,
        "Apprentice": None,
        "Master": None,
        "Guarantor": None,
        "Other": None,
        "Master Workshop - Parish": None,
        "Master Workshop - Insigna": None,
        "Guarantor Workshop - Parish": None,
        "Guarantor Workshop - Insigna": None,
        "Other Workshop - Parish": None,
        "Other Workshop - Insigna": None,
    }
    for _, r in group.iterrows():
        id_line = short_person_string_from_elems(r['Full Name'], r['Gender'], r['Age'], r['Geo Origin - Transcript'])
        if r['Tag'] == 'grz:Apprentice' or r['Tag'] == 'grz:Master':
            vals[r['Tag'].replace('grz:', '')] = id_line
            vals['Profession - Standard Forms'] = r['Professions - Standard Forms']
            vals['Profession - Transcripts'] = r['Professions - Transcripts']
            if r['Workshop - Parish']:
                vals['Master Workshop - Parish'] = r['Workshop - Parish']
            if r['Workshop - Insigna']:
                vals['Master Workshop - Insigna'] = r['Workshop - Insigna']
        elif r['Tag'] == 'grz:Guarantor':
            vals['Guarantor'] = id_line
            if r['Workshop - Parish']:
                vals['Guarantor Workshop - Parish'] = r['Workshop - Parish']
            if r['Workshop - Insigna']:
                vals['Guarantor Workshop - Insigna'] = r['Workshop - Insigna']
        elif r['Tag'] == 'grz:Other':
            vals['Other'] = id_line
            if r['Workshop - Parish']:
                vals['Other Workshop - Parish'] = r['Workshop - Parish']
            if r['Workshop - Insigna']:
                vals['Other Workshop - Insigna'] = r['Workshop - Insigna']

    return pd.Series(vals)

vals = [group_to_individual_mentions(k, g) for k, g in contracts.groupby('Contract ID').filter(lambda x: any((x['Workshop - Parish'].notnull()))).groupby('Contract ID')]
df_flat_ = pd.DataFrame(vals)
df_flat = df_flat_[df_flat_['Master Workshop - Parish'].notnull() | df_flat_['Guarantor Workshop - Parish'].notnull()]
# to avoid NaN being standardized as weird values in the json (because in this state they coexists with value None)
df_flat = df_flat.replace({np.nan: None})
contract_ids_to_date = pd.read_excel(garzoni_fp, engine='openpyxl', sheet_name="Contracts").set_index('Contract ID')['Date'].to_dict()

def correct_date_and_strptime(d:str)->dt.date:
    '''
    In the garzoni dataset, there are dozens of 29 februaries on not bisextil year, matching those date to the 1st of march of the same year
    There is also a single instance of '1646-06-00', arbitrarily matching it to the 1st of june
    '''
    try:
        return dt.strptime(d, '%Y-%m-%d') 
    except Exception as e:
        if '02-29' in d:
            return correct_date_and_strptime(d.replace('02-29', '01-03'))
        elif '-00' in d: 
            return correct_date_and_strptime(d.replace('-00', '-01'))
        else:
            raise e

contract_ids_to_date = {k: correct_date_and_strptime(v) for k,v in contract_ids_to_date.items() if v != '0000-00-00'} #filtering null date
img_path_fp = join(GARZONI_DATA_SRC, 'contracts_id_to_img_path.json')
with open(img_path_fp, 'r') as f:
    contracts_ids_to_img_path = json.load(f)

df_flat['date'] = df_flat['Contract ID'].apply(lambda v: contract_ids_to_date[v] if v in contract_ids_to_date else None)
df_flat['start_time'] = df_flat['date'].apply(lambda v: v.replace(hour=0, minute=0, second=0).isoformat())
df_flat['end_time'] = df_flat['date'].apply(lambda v: v.replace(hour=23, minute=59, second=59).isoformat())
# keeping only what we know the date of.
df_flat = df_flat[~df_flat.date.isna()].drop_duplicates()
df_flat['img_path'] = df_flat['Contract ID'].apply(lambda v: contracts_ids_to_img_path[v] if v in contracts_ids_to_img_path else None)

grz_to_loc = pd.read_csv(join(GARZONI_DATA_SRC, 'grz_parish_to_geometry_id_and_church_coordinates.csv'))

# note that poi are still generated here for legacy reasons, as the script was built with obs being derived for poi rather than the reverse. 
# However they are not saved, and the poi from the merge_obs script are the one that will link the obs from this dataset.
grz_to_loc['poi_uuid'] = grz_to_loc.progress_apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['church_coordinate']), axis=1)

def parse_coordinates(coord:str) -> Point:
    c1, c2 = coord.split(' ')
    lat = float(c1.replace('Point(', ''))
    lon = float(c2.replace(')', ''))
    return Point(lat, lon)

grz_to_loc['church_coordinate'] = grz_to_loc['church_coordinate'].apply(parse_coordinates)

# we link the PoI to the HR as we can use it later as key to link the HR to the geometries and generate the osb which have the same coordinates as the PoI
parish_loc_cols = [c for c in location_cols if 'Parish' in c]
parish_id_suffix = ' parish id'
for l in parish_loc_cols:
    df_flat[l+parish_id_suffix] = None

for i, r in df_flat.iterrows():
    for l in parish_loc_cols:
        curr_val = r[l]
        if type(curr_val) is str and curr_val:
            if curr_val in grz_to_loc['grz_parish'].values:
                df_flat.at[i, l+parish_id_suffix] = grz_to_loc[grz_to_loc['grz_parish'] == curr_val].iloc[0]['poi_uuid']
            else:
                print(f"Could not find {curr_val} in the grz_to_loc dataframe")

# generating the obs UUID directly in the same column as the geom_id so that it will be the seed for the obs generation process
for l in parish_loc_cols:
    s = l + parish_id_suffix
    # important, the name of the column is given as an ad-hoc seed to the UUID generation
    df_flat[s] = df_flat.apply(lambda v: (make_uuid_from_row_selection(VTM_UUID5_NS, v, ["Contract ID"], l), v[s]) if v[s] else None, axis=1)

tqdm.pandas(desc="Generating uuid for HRs")
df_flat['hr_uuid'] = df_flat.progress_apply(lambda v: make_uuid_from_row_selection(VTM_UUID5_NS, v, ['Contract ID']), axis=1)

# Obs. RDE Production
# because of the cardinality of the different links between all data, we need to prepare dictionnary of uuid and generate the obs in two steps.
geom_id_to_geom_uuid = gdf.groupby('id')['uuid'].apply(list).to_dict()
poi_uuid_to_geom_id = grz_to_loc.set_index('poi_uuid')['geom_id'].to_dict()
poi_uuid_to_geom_uuid = {k: geom_id_to_geom_uuid[v] for k,v in poi_uuid_to_geom_id.items() if v in geom_id_to_geom_uuid}
poi_uuid_to_coord = grz_to_loc.set_index('poi_uuid')['church_coordinate'].to_dict()
def produce_obs_from_uuid_geom_id_and_date(uuid:str, poi_uuid:str, hr_uuid: str,  date: tuple[str,str]) -> dict:
    geom_uuid = poi_uuid_to_geom_uuid[poi_uuid]
    return produce_obs_obj(
        uuid,
        date,
        DS_UUID,
        hr_uuid,
        "apprenticeship",
        coords=poi_uuid_to_coord[poi_uuid],
        geometries_links=geom_uuid
    )

obs = []

for _, r in df_flat.iterrows():
    for l in parish_loc_cols:
        s = l + parish_id_suffix
        if r[s]:
            obs.append(produce_obs_from_uuid_geom_id_and_date(r[s][0], r[s][1], r.hr_uuid, (r.start_time, r.end_time)))


gdf_obs = gpd.GeoDataFrame(obs).set_geometry('coordinate').set_index('uuid').set_crs('EPSG:4326')
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, f'garzoni_obs', RDE.OBS.value)
QA_check_uuid_are_unique(gdf_obs.reset_index())

# HR RDE Production
# cleaning up the grz: in the parish values:
for l in parish_loc_cols:
    df_flat[l] = df_flat[l].apply(lambda v: v.replace('grz:', '').replace('_', ' ') if type(v) == str else v)
hr_metadata_cols = df_flat.columns.difference(['hr_uuid'] + [l+parish_id_suffix for l in parish_loc_cols] + ['date', 'start_time', 'end_time', 'img_path'])

def produce_hr_from_contract_row(r: pd.Series) -> dict:
    obs_vals = [[r[c+parish_id_suffix][0], c] for c in parish_loc_cols if r[c+parish_id_suffix]] 
    return produce_hr_obj(
        r.hr_uuid,
        DS_UUID,
        obs_vals,
        (r.start_time, r.end_time),
        "contract",
        r[hr_metadata_cols].to_dict()
    )

recs = [produce_hr_from_contract_row(r) for _, r in df_flat.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'garzoni_hrs', RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)
QA_check_uuid_are_unique(df_of_hr)


# ad-hoc manifest and collection production for testing purposes
ad_hoc_man_prod = False

if ad_hoc_man_prod:
    def produce_five_of_uuuid(manifest_uid:str, seed:str)->tuple[str, str, str, str,str ]:
        return str(uuid.uuid5(VTM_UUID5_NS, f"{manifest_uid}_{seed}_1")), \
            str(uuid.uuid5(VTM_UUID5_NS, f"{manifest_uid}_{seed}_2")), str(uuid.uuid5(VTM_UUID5_NS, f"{manifest_uid}_{seed}_3")), str(uuid.uuid5(VTM_UUID5_NS, f"{manifest_uid}_{seed}_4")), str(uuid.uuid5(VTM_UUID5_NS, f"{manifest_uid}_{seed}_5"))

    prefix = 'https://image-timemachine.epfl.ch/iiif/3/venice%2Fgarzoni%2F%2F/full/max/0/default.jpg'

    three_contracts_ids = [
        "cbae2eda-dde1-449d-b839-07a0a586a8bf", # Apostolo, '0d4a6d1e-20dc-4ddd-80ea-2a035dc9dcad/257.jpg' top of the page https://garzoni.org/contract/view/cbae2eda-dde1-449d-b839-07a0a586a8bf "width": 4486, "height": 5896,
        "b3638323-8389-46c0-a0ee-cc18ac86cc33", # Daniel, '0d4a6d1e-20dc-4ddd-80ea-2a035dc9dcad/258.jpg' bottom of the page https://garzoni.org/contract/view/b3638323-8389-46c0-a0ee-cc18ac86cc33 "width": 4759, "height": 5896,
        "810909de-6f33-42f0-a919-5ced861a4acb"  # Allessandro, '0d4a6d1e-20dc-4ddd-80ea-2a035dc9dcad/259.jpg', bottom of the page. https://garzoni.org/contract/view/810909de-6f33-42f0-a919-5ced861a4acb "width": 4486, "height": 5896,
    ]

    # all those values and comments above were used to create manualy an ad-hoc manifest with three types of annotation, just for testing purposes. 
    for p in three_contracts_ids:
        print(p, produce_five_of_uuuid(man_id, p))
        
    coll_name = {"en": ["Garzoni document collection"], "fr": ["Collection de documents Garzoni"], "it": ["Collezione di documenti Garzoni"]}
    from utils import iiif
    with open(f'data/iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
        json.dump(iiif.generate_collection_manifest(collection_manifest_uid, coll_name, collection), f, indent=2, ensure_ascii=False)

    # hr257 = df_flat[df_flat['Contract ID'] == three_contracts_ids[0]]['hr_uuid'].values[0]
    # hr258 = df_flat[df_flat['Contract ID'] == three_contracts_ids[1]]['hr_uuid'].values[0]
    # hr259 = df_flat[df_flat['Contract ID'] == three_contracts_ids[2]]['hr_uuid'].values[0]
    # print(hr257, hr258, hr259)

    pgs = [
        [257, "Box annotation", 'venice/garzoni/0d4a6d1e-20dc-4ddd-80ea-2a035dc9dcad/257.jpg', 'image/jpeg',5896,4486, ('e3692019-59f9-5ff0-96e2-3a396b85fc62', 'Some text about Apostolo, the master.', iiif.Selector(iiif.SelectorType.XYWH, (500,300,3760,1539)))],
        [258,'Point annotation','venice/garzoni/0d4a6d1e-20dc-4ddd-80ea-2a035dc9dcad/258.jpg', 'image/jpeg',5896,4759, ('b7f52cbd-5460-58dc-8ff1-b0006866a012', 'Some text about Daniel, the master.', iiif.Selector(iiif.SelectorType.POINT, (2385,3464)))],
        [259,'Polygon annotation','venice/garzoni/0d4a6d1e-20dc-4ddd-80ea-2a035dc9dcad/259.jpg', 'image/jpeg',5896,4486, ('8f3f1297-0824-5b61-9bc9-5b528d3b2369', 'Some text about Alessandro, the master.', iiif.Selector(iiif.SelectorType.SVG, [(270,1900), (1530,1900), (1530,1610), (1315,1300), (1200,986), (904,661), (600,986), (500,1300), (270,1630)]))]
    ]

    pages = [iiif.generate_page_object(VTM_UUID5_NS, DS_SLUG,p[0],man_id,p[1],p[2], p[3],p[4],p[5], 'en', [p[6]]) for p in pgs]
    manifest = iiif.generate_manifest_object(VTM_UUID5_NS, man_id, {"en": ["Garzoni 3 page sample for testing annotations."], "fr": ["Garzoni, échantillon de 3 pages pour tester les annotations."], "it":["Garzoni 3 pagine, test."]}, 'en', pages, None)
    with open(f'data/iiif/manifests/{man_id}.json', 'w+', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

# parish dictionary, can also be used for catastici, so some more treatment are made, and the wikidata name is used as the "canon" value
prof_vals = {v:v for v in df_flat['Profession - Standard Forms'].unique() if not pd.isna(v)}
gdf['canon_name'] = gdf.apply(lambda v: v['wd_italian_name'] if v['wd_italian_name'] else v['NAME'], axis=1)
parish_vals = gdf.set_index('NAME')['canon_name'].to_dict()

church_n = 'venice-garzoni-church-dictionary'
church_name = {"en": ["Venice Garzoni Church Dictionary"], "it": ["Venezia Garzoni Dizionario delle Chiese"], 'fr': ["Venise Dictionnaire des églises"]}
church_uuid = str(uuid.uuid5(VTM_UUID5_NS, church_n))
save_dictionary('../../dictionaries/',church_uuid, church_n, church_name, parish_vals)
prof_n = 'venice-garzoni-profession-dictionary'
prof_name = {"en": ["Venice Garzoni Profession Dictionary"], "it": ["Venezia Garzoni Dizionario delle Professioni"], 'fr': ["Venise Dictionnaire des professions"]}
prof_uuid = str(uuid.uuid5(VTM_UUID5_NS, prof_n))
save_dictionary('../../dictionaries/', prof_uuid ,prof_n, prof_name, prof_vals)

# Dataset object production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
dictionaries = {
    "Profession - Standard Forms": prof_uuid,
    'Master Workshop - Parish': church_uuid,
    'Guarantor Workshop - Parish': church_uuid,
    'Other Workshop - Parish': church_uuid,
}

order = ['Apprentice',
 'Master',
 'Guarantor',
 'Profession - Standard Forms',
 'Master Workshop - Parish',
 'Master Workshop - Insigna',
 'Guarantor Workshop - Insigna',
 'Guarantor Workshop - Parish',
 'Profession - Transcripts',
 'Other',
 'Other Workshop - Insigna',
 'Other Workshop - Parish',
 'Contract ID'
]


ds_conf = produce_configuration_file_from_metadata_df(
    VTM_UUID5_NS,
    df_flat[order],
    CONF
)

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    "1.0",
    CONF['name'],
    [collection_manifest_uid],
    TR_OBJ,
    3,
    ds_conf,
    venice_area_uuids
)

save_data_file_if_different(DATA_FOLDER, 'datasets', [ds], f'garzoni_dataset', RDE.DATASET.value, is_dataset_obj=True)
