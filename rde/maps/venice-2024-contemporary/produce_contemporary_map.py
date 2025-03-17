import sys
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BASE_SLUG = 'venice-2024-contemporary'
MAP_SLUG = f"{BASE_SLUG}-map"
BEGIN_TR = 20240101
END_TR = 20241231
TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
# cadastral layer uuid:
edifici_slug = f"{MAP_SLUG}-edifici"
edifici_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, edifici_slug))

# the two corners of the bounding box of the area.
extent =  [1370421.2197, 5692718.6843, 1376129.1641, 5689219.1288]

# transforming those two corners into a closed polygon.
extent_as_point = list(zip(extent, extent[1:] + extent[:1]))
extent_as_point = extent_as_point + [extent_as_point[0]]
wgs84_extent = [(p.x, p.y) for p in [to_wgs84_from_epsg3857(e[0], e[1]) for e in extent_as_point]]
zoom_lvl= [11,21]

venice_area_uuid = get_single_object_uuid('../../areas/venice-area.json')
 
contemporary_edifici_layer = produce_layer_obj(edifici_layer_uuid, 
                                            edifici_slug,
                                          {"en": ["Footprints of contemporary buildings from 2024"],
                                           "fr": ["Empreintes des bâtiments contemporains de 2024"],
                                           "it": ["Impronte degli edifici contemporanei del 2024"]},
                                           {"en": ["The footprints of contemporary buildings from 2024 are the vectorized representation of the buildings from a contemporary cadaster of the city of Venice"],
                                            "fr": ["Les empreintes des bâtiments contemporains de 2024 sont la représentation vectorisée des bâtiments d'un cadastre contemporain de la ville de Venise"],
                                            "it": ["Le impronte degli edifici contemporanei del 2024 sono la rappresentazione vettoriale degli edifici di un catasto contemporaneo della città di Venezia"]},
                                            TR,
                                            MAP_UUID,
                                            is_vector=True,
                                            layer_configs=[produce_layer_config(
                                              str(uuid.uuid5(VMAP_UUID5_NS, f'{edifici_slug}-config-1')),
                                              zoom_lvl=zoom_lvl,
                                              extent=wgs84_extent,
                                              access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{edifici_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf",
                                              format='mvt'
                                              )]
                                            )

layers = [contemporary_edifici_layer]
layer_ids = [l['uuid'] for l in layers]
contemporary_map = produce_map_obj(MAP_UUID, 
                             MAP_SLUG,
                             {"en": ["Layers relating to contemporary geographical entities of Venice"],
                              "fr": ["Couches relatives aux entités géographiques contemporaines de Venise"],
                              "it": ["Livelli relativi alle entità geografiche contemporanee di Venezia"]},
                             {"en": ["Formed of footprints of contemporary buildings from 2024"],
                             "fr": ["Formé d'empreintes de bâtiments contemporains de 2024"],
                             "it": ["Formato da impronte di edifici contemporanei del 2024"]},
                             {"en": ["Stems from public and official GIS data from the city of Venice (?)"],
                              "fr": ["Découle de données SIG publiques et officielles de la ville de Venise (?)"],
                              "it": ["Deriva da dati GIS pubblici e ufficiali della città di Venezia (?)"]},
                              "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2Fedifici_rialto.png/full/max/0/default.jpg",
                              "1.0",
                              TR,
                              layer_ids,
                              areas_id=[venice_area_uuid]
                             )

save_data_file_if_different('', 'map', [contemporary_map], 'contemporary_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', layers, 'contemporary_layers', RDE.LAYER.value)