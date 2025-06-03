from shapely import Polygon
import sys
import os
import uuid
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import produce_area_obj, AREA_UUID5_NS, save_data_file_if_different, RDE


varea_points = [ [12.301703273382266, 45.416405027956586],
    [12.301703273382266, 45.45046323137894],
    [12.371978610336509, 45.45046323137894],
    [12.371978610336509,  45.416405027956586],
    [12.301703273382266, 45.416405027956586] ]

varea_name = {'en': ['Venice Area'], 'fr': ['Aire de Venise'],'it': ['Area di Venezia']}
varea_slug = 'venice-area'

varea_uuid = str(uuid.uuid5(AREA_UUID5_NS, varea_slug))
varea_data = produce_area_obj(varea_uuid, varea_name, Polygon(varea_points), varea_slug, '1.0')
save_data_file_if_different('', varea_slug, varea_data, varea_slug, RDE.AREA.value)


darea_points = [ [13.301703273382266, 50.816405027956586],
                [13.301703273382266, 51.25046323137894],
                [13.971978610336509, 51.25046323137894],
                [13.971978610336509,  50.816405027956586],
                [13.301703273382266, 50.816405027956586] ]

darea_name = {"en": ['Dresden Area'], "fr": ["Aire de Dresde"], "de": ["Bereich von Dresden"], 'it': ["Area di Dresda"]}
darea_slug = 'dresden-area'

darea_uuid = str(uuid.uuid5(AREA_UUID5_NS, darea_slug))
darea_data = produce_area_obj(darea_uuid, darea_name, Polygon(darea_points), darea_slug, '1.0')
save_data_file_if_different('', darea_slug, darea_data, darea_slug, RDE.AREA.value)


larea_points = [ [6.501622899, 46.642692356],
                [6.501622899, 46.470149236],
                [6.790137624, 46.470149236],
                [6.790137624,  46.642692356],
                [6.501622899, 46.642692356] ]

larea_name = {"en": ['Lausanne Area'], "fr": ["Aire de Lausanne"], "de": ["Bereich von Lausanne"], 'it': ["Area di Losanna"]}
larea_slug = 'lausanne-area'

larea_uuid = str(uuid.uuid5(AREA_UUID5_NS, larea_slug))
larea_data = produce_area_obj(larea_uuid, larea_name, Polygon(larea_points), larea_slug, '1.0')
save_data_file_if_different('', larea_slug, larea_data, larea_slug, RDE.AREA.value)


parea_points = [ [2.038020217, 49.206699347],
                [2.038020217, 48.595439112],
                [2.808018574, 48.595439112],
                [2.808018574,  49.206699347],
                [2.038020217, 49.206699347] ]

parea_name = {"en": ['Paris Area'], "fr": ["Aire de Paris"], "de": ["Bereich von Paris"], 'it': ["Area di Parigi"]}
parea_slug = 'paris-area'

parea_uuid = str(uuid.uuid5(AREA_UUID5_NS, parea_slug))
parea_data = produce_area_obj(parea_uuid, parea_name, Polygon(parea_points), parea_slug, '1.0')
save_data_file_if_different('', parea_slug, parea_data, parea_slug, RDE.AREA.value)