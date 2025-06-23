import uuid
import pandas as pd
import geopandas as gpd
import os
from os.path import join
import sys
import json
import re
from tqdm import tqdm
from functools import reduce
from shapely import wkt
# to have progress bar displayed.
tqdm.pandas()


# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils import iiif
from utils.rde import RDE
from pathlib import Path

# this holds all main parameters of the data production process
# it is used to be able to change them easily and consistently across all generation script
with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

CATASTICI_DATA_PATH = Path(join(parent_dir, 'data-venice/1740_Catastici/'))

# boolean flag to switch between the tif and the jpeg version of the manifest to be generated.
is_man_tif = True
gpd.options.io_engine = "pyogrio"

# arbitrary namespace, just to generate reproducible UUIDv5 from the data of this dataset.
VTM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, DATA_CONFIG['UUID_NAMESPACE'])
DATA_FOLDER = 'data'
DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = str(uuid.uuid5(VTM_UUID5_NS, DS_SLUG))
DS_OBJ = (DS_UUID, DS_SLUG)
formatted_begin = datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MINIMUM'])
formatted_end = datetime_obj_from_int_time(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True)
TR_OBJ = (formatted_begin, formatted_end)
df = pd.read_json(list(CATASTICI_DATA_PATH.rglob('catastici_text_data_*.json'))[-1])

venice_area_uuid = get_single_object_uuid(DATA_CONFIG['AREA_FILE_LOC'])

# replacing the author values with the full author's name  (I did not know where it was better to do it, so let's do it as soon as possible)
df['author'] = df['author'].apply(lambda x: 'Davide Drago' if x == 'Davide' else 'Francesca Zugno' if x == 'Francesca' else x)
district_acronym_d = {
    "CN": "Cannaregio",
    "CS": "Castello",
    "SM": "San Marco",
    "DD": "Dorsoduro",
    "SP": "San Polo",
    "SC": "San Croce",
    "GH": "Ghetto",
}
df['sestiere'] = df['sestiere'].apply(lambda x: district_acronym_d[x])
df['geometry'] = df['geometry'].apply(wkt.loads)
gdf = gpd.GeoDataFrame(df).set_geometry('geometry')
gdf = gdf.set_crs('EPSG:32633')
gdf = gdf.to_crs('EPSG:4326')
# below in comments is the code I used to compare the path_img from the dataset and the actual image filenames in the folder. 

# all_path_imgs = set(v.replace('SSalvador_', 'SSalvadorMurano_') for v in gdf[gdf['path_img'].str.contains('438_SCroce')]['path_img'].unique().tolist())
# all_path_imgs = set(v for v in gdf[gdf['path_img'].str.contains('438_SCroce')]['path_img'].unique().tolist())
# all_path_imgs
# import os 
# from pathlib import Path
# path_base = '../../../../../Downloads/1740 CATASTICI/'

# all_dorso_imgs = set(str(v).replace(path_base, '') for v in Path(path_base+'439_Dorsoduro/').glob('**/*.png'))
# all_dorso_imgs
# all_path_imgs.difference(all_dorso_imgs)

smarco_replace_dict = {"434_SMarco/2_SBasso/SBasso_0_1.png": "434_SMarco/2_SBasso/SBasso_0_01.png",
                "434_SMarco/3_SZiminian/SZiminian_0_1.png": "434_SMarco/3_SZiminian/SZiminian_0_01.png",
                "434_SMarco/3_SZiminian/SZiminian_1_9.png": "434_SMarco/3_SZiminian/SZiminian_1_09.png",
                "434_SMarco/7_SBortolomio/SBortolomio_0_1.png": "434_SMarco/7_SBortolomio/SBortolomio_0_01.png",
                "434_SMarco/4_SMoise/SMoise_60_643.png": "434_SMarco/4_SMoise/SMoise_60_693.png"}

castello_replace_dict = {v:v.replace('Nuovo', 'Novo').replace('Pietro', 'Piero') for v in gdf[gdf['path_img'].str.contains('435_Castello')]['path_img'].unique().tolist()}
canna_replace_dict = {'436_Cannaregio/11_SCancian/SCancian_0_1.png': '436_Cannaregio/11_SCancian/SCancian_0_01.png'}
spolo_replace_dict = {v:v.replace('SGiovanniElmosinario', 'SGiovanniNovo') for v in gdf[gdf['path_img'].str.contains('437_SPolo')]['path_img'].unique().tolist()}
spolo_replace_dict['437_SPolo/1_SPolo/SPolo_12_85.png'] = '437_SPolo/1_SPolo/SPolo_12_86.png'
scroce_replace_dict = {v:v.replace('SSimeonProfeta', 'SSimonProfeta').replace('SSimeonApostolo', 'SSimonPiccolo').replace('SGiovanniDecollato', 'SGiovannidecollato') for v in gdf[gdf['path_img'].str.contains('438_SCroce')]['path_img'].unique().tolist()} 
dorso_replace_dict = {v:v.replace('SNicolo', 'SanNicolo').replace('SRaffael', 'AngeloRaffael') for v in gdf[gdf['path_img'].str.contains('439_Dorsoduro')]['path_img'].unique().tolist()}
dorso_replace_dict['439_Dorsoduro/5_SBarnaba/SBarnaba_11_103.png'] = '439_Dorsoduro/5_SBarnaba/SBarnaba__11_103.png'
dorso_replace_dict['439_Dorsoduro/9_SBaseggio/SBaseggio_0_1.png'] = '439_Dorsoduro/9_SBaseggio/SBaseggio_0_01.png'
manuals_leftovers = {
  '438_SCroce/2_SCassiano/SCassiano_0_1.png': '438_SCroce/2_SCassiano/SCassiano_0_01.png',
 '439_Dorsoduro/9_SBaseggio/SBaseggio_0_1.png': '439_Dorsoduro/9_SBaseggio/SBaseggio_0_01.png',
 '440_Ghetto/1_GhettoVecchio/57_407.png': '440_Ghetto/1_GhettoVecchio/57_407.jpg'
}


replace_dict = {**smarco_replace_dict, **castello_replace_dict, **canna_replace_dict, **scroce_replace_dict, **spolo_replace_dict, **dorso_replace_dict, **manuals_leftovers}

gdf['path_img'] = gdf['path_img'].apply(lambda x: x.replace('Beneto', 'Benetto').replace('Basegio', 'Baseggio') if x is not None else None)
gdf['path_img'] = gdf['path_img'].apply(lambda x: replace_dict.get(x, x))

def technical_name_to_natural_name(t:str) -> str:
    '''
    To translate short name of parish name beginning with "S"
    to the actual natural name. 
    '''
    all_vals = re.sub( r"([A-Z])", r" \1", t).split()
    prefix = ''
    if all_vals[0][0].isupper() and len(all_vals[0]) == 1:
        if all_vals[0] == 'S':
            prefix += 'San'
            if all_vals[1][-1] == 'a':
                prefix += 'ta'
    return ' '.join([prefix] + all_vals[1:] if len(prefix) > 0 else all_vals)

    
def underscore_split(t:str) -> list[str]:
    '''
    This function splits a string by underscore and removes the underscores.
    '''
    return [l for l in [v.replace('_', '') for v in re.sub( r"(_)", r" \1", t).split()] if l]

def filename_to_label(filename:str) -> tuple[int, str, int, str, int]:
    try:
        vol_, parish_, page_idx_ = [underscore_split(v) for v in filename.split('/')]
        vol_numb = vol_[0]
        vol = technical_name_to_natural_name(vol_[1])
        parish = technical_name_to_natural_name(parish_[1])
        parish_numb = parish_[0]
        page_idx = page_idx_[1] if not 'ghetto' in parish.lower() else page_idx_[0]
        if page_idx.endswith('.png'):
            page_idx = page_idx.replace('.png', '')
        if page_idx.endswith('.jpg'):
            page_idx = page_idx.replace('.jpg', '')
        return int(vol_numb), vol, int(parish_numb), parish, int(page_idx)
    except Exception as e:
        # to see which filenames do not work 
        print(e)
        print(filename)
        return filename, '', ''

# the file below was produced by the script "images_width_height_format_extrator.py" on the images of the dataset.
df_wh = pd.read_csv('src/imgs_width_height_format.csv')
df_wh['filename'] = df_wh['filename'].apply(lambda x: x.replace('434_SanMarco', '434_SMarco') if x is not None else x)
# cooking all the data I need to build a ToC and individual ordered pages.
df_wh['volume_number'], df_wh['volume'], df_wh['parish_number'], df_wh['parish'], df_wh['page_index'] = zip(*df_wh['filename'].apply(filename_to_label))


if is_man_tif:
    # firstly, reunite all the tif wh/format reads into a single file that adds the folder prefix to all the files.
    all_catasticis = Path('src/tif_img_wh/').rglob('catastici_1740_4*.csv')

    def read_csv_and_patch_folder_name(f:Path) -> pd.DataFrame:
        folder_name = str(f).split('_')[-1].replace('.csv','')
        df = pd.read_csv(f)
        df['filename'] = df['filename'].apply(lambda x: f'/catastici/Catastici-{folder_name}/{x}')
        return df

    df_tifs = reduce(lambda x,y: pd.concat([x,y]), [read_csv_and_patch_folder_name(f) for f in all_catasticis], pd.DataFrame())
    # building the tif version of the ToC using the jpg version of the ToC for bootstrapping. 

    #issue with sorting there: 
    sel_cols = ['volume_number', 'volume', 'parish_number', 'parish']
    # the sort value is essential so when we take the first elelment, it is actually the first.  
    toc_vals = df_wh.sort_values(by=['page_index']).groupby(sel_cols).first().reset_index()[sel_cols+['filename']]
    path_to_tif_path = gdf[['path_img', 'tif_path_img']].drop_duplicates().set_index('path_img')['tif_path_img'].to_dict()
    missing_matches = {
        "435_Castello/4_SMartin/SMartin_0_1.png":"Catastici-435/4/0565.tif",
        "436_Cannaregio/12_SGiovanniGrisostomo/SGiovanniGrisostomo_0_ni.png":"Catastici-436/11/1519.tif",
        "438_SCroce/10_SSalvadorMurano/SSalvadorMurano_0.png": "Catastici-438/10/1263.tif",
        "438_SCroce/11_SStefanoMurano/SStefanoMurano_0.png": "Catastici-438/11/1279.tif",
        "438_SCroce/12_SMartinMurano/SMartinMurano_0.png": "Catastici-438/12/1491.tif",
        "438_SCroce/13_SDonatoMurano/SDonatoMurano_0.png": "Catastici-438/13/1555.tif",
    }
    path_to_tif_path = {**path_to_tif_path, **missing_matches}
    toc_vals['path_tif'] = toc_vals['filename'].apply(lambda x: path_to_tif_path.get(x, None))
    toc_vals['path_tif'].isna().sum()

    def tif_filename_to_subparts(tif_filename:str) -> tuple[int, int, int]:
        try:
            tif_filename = tif_filename.replace('/catastici/Catastici-', '').replace('.tif', '')
            vals = [v for v in tif_filename.split('/')]
            if len(vals) == 3:
                vol_numb, parish_numb, page_idx = vals
            elif len(vals) == 2:
                vol_numb, page_idx = vals
                parish_numb = 0
            else:
                raise ValueError('The filename does not have the correct number of parts.', tif_filename)
            return int(vol_numb), int(parish_numb), int(page_idx)
        except Exception as e:
            print(e)
            print(tif_filename)
            return tif_filename, '', ''


    df_tifs[['volume_number', 'parish_number', 'page_index']] = df_tifs['filename'].apply(lambda x: tif_filename_to_subparts(x)).apply(pd.Series)
    df_tifs = df_tifs.sort_values(by=['volume_number', 'page_index', 'parish_number'])
    # building an intermediate structure to match all the pages where a range of the ToC starts in the jpeg version so it can then be propagated to the tif version
    filenames_of_interest = toc_vals[toc_vals['path_tif'].notna()].set_index('path_tif')[['volume_number', 'volume', 'parish_number', 'parish']].to_dict(orient='index')
    # we also add the first page of each volume as its own entry of the ToC separately, since those were not present in the jpeg version.
    
    vol_first_pages = {
        "/catastici/Catastici-434/0000.tif": {'volume_number': 434, 'volume': 'San Marco', 'parish_number': 0, 'parish': 'index'},
        "/catastici/Catastici-435/0000.tif": {'volume_number': 435, 'volume': 'Castello', 'parish_number': 0, 'parish': 'index'},
        "/catastici/Catastici-436/0000.tif": {'volume_number': 436, 'volume': 'Cannaregio', 'parish_number': 0, 'parish': 'index'},
        "/catastici/Catastici-437/0000.tif": {'volume_number': 437, 'volume': 'San Polo', 'parish_number': 0, 'parish': 'index'},
        "/catastici/Catastici-438/0000.tif": {'volume_number': 438, 'volume': 'Santa Croce', 'parish_number': 0, 'parish': 'index'},
        "/catastici/Catastici-439/0000.tif": {'volume_number': 439, 'volume': 'Dorsoduro', 'parish_number': 0, 'parish': 'index'},
    }
    # note: there is duplicates tif files for the 204 first pages of Santa Croce
    filenames_of_interest = {**filenames_of_interest, **vol_first_pages}
    df_tifs[['volume_number_toc', 'volume_toc', 'parish_number_toc', 'parish_toc']] = df_tifs['filename'].apply(lambda x: filenames_of_interest.get(x, None)).apply(pd.Series)
    # ffill is forward fill, matches all volume and parish name from the first page to the following.
    df_wh_tif = df_tifs.ffill().drop(columns=['volume_number', 'parish_number']).rename(columns={'volume_number_toc':'volume_number', 'parish_number_toc':'parish_number', 'volume_toc':'volume', 'parish_toc':'parish'})
    # we don't have the tif version of the ghetto, so we add the values from the jpeg/png version instead.
    df_ghetto = df_wh[df_wh['volume_number'] == 440]
    df_ghetto_sorted = df_ghetto.sort_values(by=['parish_number','page_index'])
    df_ghetto_index = df_ghetto_sorted.iloc[:6].copy()
    # also for consistency with the ToC as it is organized in the other volumes, setting the parish number to 0 and name to index to make the index appear in the ToC.
    df_ghetto_index['parish_number'] = 0
    df_ghetto_index['parish'] = 'index'
    df_ghetto_fixed = pd.concat([df_ghetto_index, df_ghetto_sorted.iloc[6:]])
    df_wh_tif = pd.concat([df_wh_tif, df_ghetto_fixed])
    df_wh_tif['volume_number'] = df_wh_tif['volume_number'].astype(int)
    df_wh_tif['parish_number'] = df_wh_tif['parish_number'].astype(int)
    # ovwerwrite the df_wh that is going to be used for the ToC with the tif version
    df_wh = df_wh_tif

df_pages = df_wh.sort_values(by=['volume_number', 'parish_number', 'page_index']).reset_index(drop=True).reset_index()

collection = {}
structures = {}
df_pages['page_obj'] = None
df_pages['manifest_uid'] = None
df_pages['canvas_id'] = None
for g, group_df in df_pages.groupby(['volume_number', 'volume']):
    volume_number = g[0]
    volume_name = g[1]
    volume_title = f'{volume_number}-{volume_name}'
    man_label = {"it": [f'Catastici di Venezia 1740 ({volume_title})'], "en": [f'Venice\'s civil registry from 1740 ({volume_title})'], "fr": [f'Registre civil de Venise en 1740 ({volume_title})']}
    manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'manifest_{DS_SLUG}_{volume_title}'))
    collection[manifest_uid] = man_label
    for i, x in group_df.iterrows():
        page_obj =  iiif.generate_page_object(VTM_UUID5_NS, DS_UUID, x['index'],\
                                                                manifest_uid, f"{x['volume']}: {x['page_index']}",\
                                                                'venice/' + ('' if x['filename'].endswith('tif') else 'catastici_1740/')+ x['filename'],  \
                                                                x['media_type'], x['height'], x['width'], 'it')
        df_pages.at[i, 'page_obj'] = page_obj
        df_pages.at[i, 'manifest_uid'] = manifest_uid
        df_pages.at[i, 'canvas_id'] = page_obj['id']
        group_df.at[i, 'canvas_id'] = page_obj['id']

    # adding back the numbers so the structure is ordered correctly.
    group_df['volume_order'] = group_df['volume_number'].astype(str) + '-' + group_df['volume']
    group_df['parish_order'] = group_df['parish_number'].apply(lambda v: f"{v:02d}") + '-' + group_df['parish']
    groups = group_df[['parish_order', 'canvas_id']].groupby(['parish_order']).agg(list)
    range_id_pref = f'{manifest_uid}/range'
    curr_structure = iiif.ordered_dict_to_iiif_toc_structure(iiif.multiindex_to_nested_dict(groups), "it", "Sommario", range_id_pref)
    structures[manifest_uid] = curr_structure

collection_manifest_uid = str(uuid.uuid5(VTM_UUID5_NS, f'collection_{DS_SLUG}'))
filename_to_canvas_id = dict(zip(df_pages['filename'], df_pages['canvas_id']))

# this sanity check works only in the jpeg version because of how "path_imag" is used to do the sanity check (would need some workaround for tif, as there are no scans for the Ghetto)
if not is_man_tif:
    disk_p = set(df_pages['filename'])
    trsnc_p = set(gdf['path_img'].unique())
    # sanity check to be sure all images referenced in the transcription is matched to a filename on the disk
    missingno = trsnc_p.difference(disk_p)

tqdm.pandas(desc="Generating obs uuid")
df['obs_uuid'] = df.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['uidx', 'id']), axis=1)
tqdm.pandas(desc="Generating hr uuid")
df['hr_uuid'] = df.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['uidx']), axis=1)
tqdm.pandas(desc="Generating poi uuid")
df['poi_uuid'] = df.progress_apply(lambda r: make_uuid_from_row_selection(VTM_UUID5_NS, r, ['geometry']), axis=1)

# Generate Obs RDE
tpe = 'parcel ownership'
obs = [produce_obs_obj(r.obs_uuid, TR_OBJ, DS_UUID, r.hr_uuid, tpe, r.geometry, None, r.poi_uuid) for _,r in df.iterrows()]
gdf_obs = gpd.GeoDataFrame(obs).set_geometry('coordinate').set_crs('EPSG:32633').to_crs('EPSG:4326').set_index('uuid')

QA_check_uuid_are_unique(gdf_obs.reset_index())
save_data_file_if_different(DATA_FOLDER, 'observations', gdf_obs, 'catastici_obs', RDE.OBS.value)

# Generate PoI RDE
# for the one to many relationship with the obs 
df_poi = df[['poi_uuid', 'obs_uuid', 'geometry']].groupby('poi_uuid').agg(list)
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(v.poi_uuid, v.geometry[0], v.obs_uuid) for _,v in df_poi.reset_index().iterrows()])
gdf_poi = gdf_poi.set_geometry('coordinate').set_crs('EPSG:32633').to_crs('EPSG:4326').set_index('uuid')

QA_check_uuid_are_unique(gdf_poi.reset_index())
QA_check_unique_uuid_in_uuid_array(gdf_poi, 'represents')
save_data_file_if_different(DATA_FOLDER, 'points_of_interest', gdf_poi,  f'catastici_poi', RDE.POI.value)

# Generate HR RDE
exclude_hr_labels = {
    'geometry', 
    'poi_uuid',
    'obs_uuid',
    'hr_uuid',
    'uidx',
    'uid'
}
hr_metadata_cols = list(set(df.columns).difference(exclude_hr_labels))
tpe = 'cadaster registry'
recs = [produce_hr_obj(r.hr_uuid,\
                       DS_UUID,\
                       [[r.obs_uuid, 'place']],\
                       TR_OBJ,\
                       tpe,\
                   r[hr_metadata_cols].to_dict()) \
                   for _, r in df.iterrows()]

save_data_file_if_different(DATA_FOLDER, 'historical_records', recs, f'catastici_hrs', RDE.HR.value)

df_of_hr = pd.DataFrame(data = recs)

QA_check_uuid_are_unique(df_of_hr)
QA_check_unique_uuid_in_uuid_array(df_of_hr, 'documents')

# Source Entities Production
# (Now that we have all the HR generated, we can finish the manifest generation process)

# preparing the data to insert in the canvas of the manifest.
df_iiif_links = df_of_hr.copy()

def retrieve_canvas_id_from_filename(metada_obj:str) -> str:
    x = metada_obj
    # the if-else selecting between the tif and jpeg version of the image is done here, because of the ghetto not having the tif version.
    filename = x['tif_path_img'] if x['tif_path_img'] and is_man_tif else x['path_img']
    return filename_to_canvas_id.get(filename, '')

df_iiif_links['canvas_id'] = df_iiif_links['annotated_content'].apply(retrieve_canvas_id_from_filename)

def catastici_metadata_object_to_string_representation(metadata: dict) -> str:
    quick_check = lambda x: x if type(x) is str and x.lower() != 'nan' and len(x) > 0 else ''
    vals = [quick_check(metadata.get(v, '')) for v in ['place', 'function', 'ten_name', 'owner_name']]
    rendi = metadata.get('an_rendi', '')
    if type(rendi) == int or type(rendi) == float:
        rendi = str(rendi)
    elif type(rendi) == str:
        if rendi.lower() == 'nan' or len(rendi) == 0:
            rendi = ''
    return ' | '.join([v for v in vals + [rendi] if len(v) > 0])

df_iiif_links['iiif_display_string'] = df_iiif_links['annotated_content'].apply(catastici_metadata_object_to_string_representation)
df_iiif_links['iiif_metadata_obj'] = df_iiif_links.apply(lambda x: (x['uuid'], x['iiif_display_string']), axis=1)
# the hr_uuid is missing. 
iiif_links = df_iiif_links[['canvas_id', 'iiif_metadata_obj']].groupby('canvas_id').agg(list).reset_index().set_index('canvas_id')['iiif_metadata_obj'].to_dict()
df_pages['page_obj'] = df_pages['page_obj'].apply(lambda x: dict(x, metadata = iiif_links.get(x['id'], '')))

for manifest_uid, man_label in collection.items():
    # generating the manifests
    with open(f'data/iiif/manifests/{manifest_uid}.json', 'w+', encoding='utf-8') as f:
        data = df_pages[df_pages['manifest_uid'] == manifest_uid].copy()
        json.dump(iiif.generate_manifest_object(VTM_UUID5_NS, manifest_uid, man_label, 'it', data['page_obj'].tolist(), structures[manifest_uid]), f, indent=2, ensure_ascii=False)

coll_mulilingual_label = {'en': ["Venice's civil registry from 1740"],
  'fr': ['Registre civil de Venise en 1740'], 
  'it': ['Catastici di Venezia 1740']
}

with open(f'data/iiif/collections/{collection_manifest_uid}.json', 'w+', encoding='utf-8') as f:
    json.dump(iiif.generate_collection_manifest(collection_manifest_uid, coll_mulilingual_label, collection), f, indent=2, ensure_ascii=False)

# Dataset RDE Production
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
dictionaries = {
    "sestiere": get_single_object_uuid('../../dictionaries/venice-district-dictionary.json'),
    "parish_std": get_single_object_uuid('../../dictionaries/venice-garzoni-church-dictionary.json')
}

filtered_df = df.drop(columns=exclude_hr_labels)
# the columns of the df needs to be ordered the way we want them to be ordered then in the configuration file.
order = CONF['labels'].keys()
ds_conf = produce_configuration_file_from_metadata_df(VTM_UUID5_NS, 
                                                      filtered_df[order],
                                                      CONF['indexed'],
                                                      CONF["short_display"],
                                                      CONF["hidden"], 
                                                      dictionaries,
                                                      CONF["tagged_fields"],
                                                      CONF["labels"], 
                                                      CONF["main_label"],
                                                      CONF["sub_label"])

ds = produce_dataset_obj(
    DS_UUID,
    DS_SLUG,
    "1.0",
    CONF['name'],
    CONF['description'],
    CONF['paradata'],
    [collection_manifest_uid],
    TR_OBJ,
    len(df_iiif_links['canvas_id'].unique()),
    ds_conf,
    [venice_area_uuid],
    publish_obj=(CONF["doi"],CONF["github_link"])
)

save_data_file_if_different(DATA_FOLDER, 'datasets', [ds], 'catastici_dataset', RDE.DATASET.value, is_dataset_obj=True)