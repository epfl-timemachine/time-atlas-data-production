import sys
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BASE_SLUG = 'venice-1834-gallo'
MAP_SLUG = f"{BASE_SLUG}-map"
BEGIN_TR = 18340101
END_TR = 18341231
tuple_TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
bm_slug = f"{MAP_SLUG}-base"
basemap_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, bm_slug))

# the two corners of the bounding box of the area.
extent =  [1370421.2197, 5692718.6843, 1376129.1641, 5689219.1288]

# transforming those two corners into a closed polygon.
extent_as_point = list(zip(extent, extent[1:] + extent[:1]))
extent_as_point = extent_as_point + [extent_as_point[0]]
wgs84_extent = [[p.x, p.y] for p in [to_wgs84_from_epsg3857(e[0], e[1]) for e in extent_as_point]]
zoom_lvl= [11,21]

venice_area_uuid = get_single_object_uuid('../../areas/venice-area.json')

gallo_bm_layer = produce_layer_obj(basemap_layer_uuid,
                                        bm_slug,
                                         {"en": ["Historical map of Venice from 1834"],
                                          "fr": ["Carte historique de Venise de 1834"],
                                            "it": ["Mappa storica di Venezia del 1834"]},
                                        {"en": ["The historical maps of the parcels are the digital facsimile of the original map."],
                                         "fr": ["Les cartes historiques des parcelles sont le fac-similé numérique de la carte originale."],
                                         "it": ["Le mappe storiche delle particelle sono il facsimile digitale della mappa originale."]},
                                         tuple_TR,
                                         MAP_UUID,
                                         is_vector=False,
                                         layer_configs=[produce_layer_config(
                                          str(uuid.uuid5(VMAP_UUID5_NS, f'{bm_slug}-config-1')),
                                          zoom_lvl=zoom_lvl,
                                          extent=wgs84_extent,
                                          access_url="https://geo-timemachine.epfl.ch/geoserver/wms?service=WMS&version=1.1.0&request=GetMap&layers=TimeMachine:venice-1834-bggallo",
                                          format='wms'
                                          )]
                                        )

layers = [gallo_bm_layer]
layer_ids = [l['uuid'] for l in layers]
map_obj = produce_map_obj(MAP_UUID, 
                             MAP_SLUG,
                             {"en": ["Map of Venice from 1834 established by Bertoja G. Gallo"],
                              "fr": ["Carte de Venise de 1834 établie par Bertoja G. Gallo"],
                              "it": ["Mappa di Venezia del 1834 stabilita da Bertoja G. Gallo"]},
                             {"en": ["Is formed of the digital facsimile of the original full map of Venice"],
                             "fr": ["Est formée du fac-similé numérique de la carte complète originale de Venise"],
                              "it": ["È formata dal facsimile digitale della mappa completa originale di Venezia"]},
                             {"en": ["The maps were scanned and then georeferenced to allow them to fit as closely as possible to the contemporary map of Venice."],
                              "fr": ["Les cartes ont été scannées puis géoréférencées pour leur permettre de s'adapter le plus possible à la carte contemporaine de Venise."],
                              "it": ["Le mappe sono state scansionate e quindi georeferenziate per consentire loro di adattarsi il più possibile alla mappa contemporanea di Venezia."]},
                              "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2F1834_BGGallo.png/full/max/0/default.jpg",
                              "1.0",
                              tuple_TR,
                              layer_ids,
                              areas_id=[venice_area_uuid]
                             )

save_data_file_if_different('', 'map', [map_obj], '1834_gallo_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', layers, '1834_gallo_layers', RDE.LAYER.value)