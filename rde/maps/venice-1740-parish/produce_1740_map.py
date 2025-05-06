from pathlib import Path
import sys
import uuid
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BEGIN_TR = 17400101
END_TR = 17401231
TR_OBJ = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_SLUG = "venice-1740-map"
MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
parish_layer_slug = f"{MAP_SLUG}-parish-layer"
parish_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, parish_layer_slug))
# the two corners of the bounding box of the area.
extent =  [1370421.2197, 5692718.6843, 1376129.1641, 5689219.1288]

venice_area_uuid = get_single_object_uuid('../../areas/venice-area.json')

# copied from sommarioni code, probably a modular function to be added to the utils
# transforming those two corners into a closed polygon.
extent_as_point = list(zip(extent, extent[1:] + extent[:1]))
extent_as_point = extent_as_point + [extent_as_point[0]]
wgs84_extent = [[p.x, p.y] for p in [to_wgs84_from_epsg3857(e[0], e[1]) for e in extent_as_point]]
zoom_lvl= [11,21]

layer_name = {"en": ["Parishes of 1740"], "fr": ["Paroisses de 1740"], "it": ["Parrocchie di 1740"]}
layer_description = {"en": ["Manual interpretation of the administrative delimitation of the religious parishes from 1740 in the isle of Venice."], "fr": ["Interprétation manuelle de la délimitation administrative des paroisses religieuses de 1740 dans l'île de Venise."], "it": ["Interpretazione manuale della delimitazione amministrativa delle parrocchie religiose del 1740 nell'isola di Venezia."]}
parish_layer = produce_layer_obj(
    parish_layer_uuid,
    parish_layer_slug,
    layer_name,
    layer_description,
    TR_OBJ,
    MAP_UUID,
    is_vector=True,
    layer_configs=[produce_layer_config(
        str(uuid.uuid5(VMAP_UUID5_NS, f'{parish_layer_slug}-config-1')),
        zoom_lvl=zoom_lvl,
        extent=wgs84_extent,
        format='mvt',
        access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{parish_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf"
    )]
)

map_name = {"en":["Digital Layer – 1740 Parish Boundaries"],
            "fr":["Couche numérique - Limites des paroisses de 1740"],
            "it":["Layer digitale - Confini parrocchiali del 1740"]
            }
map_description = {"en":["Vector data manually extracted and realigned from the parishes mentioned in the 1740 Catastici dataset. Provides spatial representations of parish areas based on historical references. Dataset created at EPFL."],
                    "fr":["Données vectorielles extraites et réalignées manuellement à partir des paroisses mentionnées dans le jeu de données Catastici de 1740. Fournit des représentations spatiales des zones paroissiales basées sur des références historiques. Jeu de données créé à l'EPFL."],
                    "it":["Dati vettoriali estratti e riallineati manualmente dalle parrocchie menzionate nel dataset Catastici del 1740. Fornisce rappresentazioni spaziali delle aree parrocchiali basate su riferimenti storici. Dataset creato all'EPFL."]}
map_paradata = {"en":["Is formed of a manual interpretation of the parishes' geographical delimitation from 1740"], "fr":["Est formée d'une interprétation manuelle de la délimitation géographique des paroisses de 1740"], "it": ["Basato su un'interpretazione manuale dei confini parrocchiali del 1740."]}
map_1740 = produce_map_obj(
    MAP_UUID,
    MAP_SLUG,
    map_name,
    map_description,
    map_paradata,
    "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2Fparish_rialto.png/full/max/0/default.jpg",
    "1.0",
    TR_OBJ,
    [parish_layer_uuid],
    areas_id=[venice_area_uuid]
)

save_data_file_if_different('', 'map', [map_1740], '1740_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', [parish_layer], '1740_layers', RDE.LAYER.value)