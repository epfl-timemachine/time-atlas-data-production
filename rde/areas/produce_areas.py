from shapely import Polygon, MultiPolygon, LineString
import sys
import os
import uuid
from typing import Union
import json 
from unidecode import unidecode
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import produce_area_obj, AREA_UUID5_NS, save_data_file_if_different, RDE

def produce_geometry_obj_from_two_corners(corners_array: list[float]) -> dict:
    if len(corners_array) != 4:
        raise ValueError("The corners_array must contain exactly four elements.")
    
    min_x, min_y, max_x, max_y = corners_array
    poly = [[[min_x, min_y], [min_x, max_y], [max_x, max_y], [max_x, min_y], [min_x, min_y]]]

    return {'type': 'Polygon', 'coordinates': poly}

def remove_weird_characters(input_str: str) -> str:
    input_str = unidecode(input_str)
    # remove punctation as well:
    input_str = ''.join(char for char in input_str if char.isalnum() or char == '-' or char == '_')
    return input_str

varea_min = [12.290776992, 45.373579637]
varea_max = [12.469331224, 45.497617311]

varea_name = {'en': ['Venice Area'], 'fr': ['Aire de Venise'],'it': ['Area di Venezia']}
varea_slug = 'city-venice-area'

varea_uuid = str(uuid.uuid5(AREA_UUID5_NS, varea_slug))
varea_data = produce_area_obj(varea_uuid, varea_name, produce_geometry_obj_from_two_corners(varea_min + varea_max), varea_slug, '1.0')
save_data_file_if_different('data', varea_slug, varea_data, varea_slug, RDE.AREA.value)

darea_min = [13.301703273382266, 50.816405027956586]
darea_max = [13.971978610336509, 51.25046323137894]

darea_name = {"en": ['Dresden Area'], "fr": ["Aire de Dresde"], "de": ["Bereich von Dresden"], 'it': ["Area di Dresda"]}
darea_slug = 'city-dresden-area'

darea_uuid = str(uuid.uuid5(AREA_UUID5_NS, darea_slug))
darea_data = produce_area_obj(darea_uuid, darea_name, produce_geometry_obj_from_two_corners(darea_min+darea_max), darea_slug, '1.0')
save_data_file_if_different('data', darea_slug, darea_data, darea_slug, RDE.AREA.value)

larea_min = [6.501622899, 46.470149236]
larea_max = [6.790137624, 46.642692356]

larea_name = {"en": ['Lausanne Area'], "fr": ["Aire de Lausanne"], "de": ["Bereich von Lausanne"], 'it': ["Area di Losanna"]}
larea_slug = 'city-lausanne-area'

larea_uuid = str(uuid.uuid5(AREA_UUID5_NS, larea_slug))
larea_data = produce_area_obj(larea_uuid, larea_name, produce_geometry_obj_from_two_corners(larea_min+larea_max), larea_slug, '1.0')
save_data_file_if_different('data', larea_slug, larea_data, larea_slug, RDE.AREA.value)

parea_min = [2.038020217, 49.206699347]
parea_max = [2.808018574, 48.595439112]

parea_name = {"en": ['Paris Area'], "fr": ["Aire de Paris"], "de": ["Bereich von Paris"], 'it': ["Area di Parigi"]}
parea_slug = 'city-paris-area'

parea_uuid = str(uuid.uuid5(AREA_UUID5_NS, parea_slug))
parea_data = produce_area_obj(parea_uuid, parea_name, produce_geometry_obj_from_two_corners(parea_min+parea_max), parea_slug, '1.0')
save_data_file_if_different('data', parea_slug, parea_data, parea_slug, RDE.AREA.value)

aarea_min = [4.629740525, 52.150125547]
aarea_max = [5.205523267, 52.550109077]

aarea_name = {"en": ['Amsterdam Area'], "fr": ["Aire d'Amsterdam"], "de": ["Bereich von Amsterdam"], 'it': ["Area di Amsterdam"], 'nl': ["Amsterdam gebied"]}
aarea_slug = 'city-amsterdam-area'

aarea_uid = str(uuid.uuid5(AREA_UUID5_NS, aarea_slug))
aarea_data = produce_area_obj(aarea_uid, aarea_name, produce_geometry_obj_from_two_corners(aarea_min+aarea_max), aarea_slug, '1.0')
save_data_file_if_different('data', aarea_slug, aarea_data, aarea_slug, RDE.AREA.value)

earea_max = [126.48944444444444, 62.390556]
earea_min = [-135.0, 14.917119]

earea_name = {"en": ['Europeana\'s postcards Area'], "fr": ["Aire des cartes postales d'Europe"], "de": ["Bereich der Postkarten von Europeana"], 'it': ["Area delle cartoline d'Europeana"], 'nl': ["Europeana's ansichtkaartengebied"]}
earea_slug = 'europeana-postcards-area'

earea_uuid = str(uuid.uuid5(AREA_UUID5_NS, earea_slug))
earea_data = produce_area_obj(earea_uuid, earea_name, produce_geometry_obj_from_two_corners(earea_min+earea_max), earea_slug, '1.0')
save_data_file_if_different('data', earea_slug, earea_data, earea_slug, RDE.AREA.value)

# producing all areas from the countries fetched in MapTiler. 
with open('countries_src/country_code_to_labels.json', 'r', encoding='utf-8') as f:
    code_to_country_labels = json.load(f)


def select_feature_that_is_a_polygon_or_multipolygon(features: list[dict]) -> Union[dict, None]:
    for feature in features:
        geom_type = feature.get('geometry', {}).get('type', '')
        if geom_type in ['Polygon', 'MultiPolygon']:
            return feature
    return None

language_codes = ['en', 'fr', 'de', 'it', 'nl']

for file in os.listdir('countries_src/src'):
    with open(os.path.join('countries_src/src', file), 'r', encoding='utf-8') as f:
        data = json.load(f)
        if file in code_to_country_labels:
            country_name_dict = {k: [v] for k, v in code_to_country_labels[file].items() if k in language_codes}
            en_label = country_name_dict.get('en')[0].replace(' ', '-').lower()
            country_slug = remove_weird_characters(f"country-{en_label}-area")
            country_uuid = str(uuid.uuid5(AREA_UUID5_NS, country_slug))
            if len(data['features']) > 1:
                geometry = select_feature_that_is_a_polygon_or_multipolygon(data['features'])
            elif len(data['features']) == 1:
                geometry = data['features'][0]['geometry']
            else:
                print(f"No features found in file {file}, skipping...")
                continue
            country_area_data = produce_area_obj(country_uuid, country_name_dict, geometry, country_slug, '1.0')
            save_data_file_if_different('data', country_slug, country_area_data, country_slug, RDE.AREA.value)
