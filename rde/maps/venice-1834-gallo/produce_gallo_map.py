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
zoom_lvl= [11,21]

venice_area_uuids = get_area_uuids_from_slugs('../../areas/data', ['city-venice-area', 'country-italy-area'])

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
                                          extent = ['POINT (12.305245805397046 45.452385260466166)','POINT (12.365777548871057 45.41804260044283)'],
                                          zoom_lvl=zoom_lvl,
                                          access_url="https://geo-timemachine.epfl.ch/geoserver/gwc/service/wmts/rest/TimeMachine:venice-1834-bggallo/raster/EPSG:900913x2/EPSG:900913x2:{z}/{y}/{x}?format=image/png",
                                          format='wmts'
                                          )]
                                        )

layers = [gallo_bm_layer]
map_obj = produce_map_obj(MAP_UUID, 
                             MAP_SLUG,
                             {"en": ["Digital Facsimile of Bertoja’s Map of Venice"],
                              "fr": ["Fac-similé numérique de la carte de Venise de Bertoja"],
                              "it": ["Facsimile digitale della mappa di Venezia di Bertoja"]},
                             {"en": ["Digitized reproduction of the 1834 map of Venice, drawn by Bertoja, engraved by A. Lazzari, and published by D. Gallo in 1831. Preserves the original cartographic detail and historical references. Dataset created at EPFL."],
                             "fr": ["Reproduction numérisée de la carte de Venise de 1834, dessinée par Bertoja, gravée par A. Lazzari et publiée par D. Gallo en 1831. Préserve le détail cartographique original et les références historiques. Jeu de données créé à l'EPFL."],
                             "it": ["Riproduzione digitalizzata della mappa di Venezia del 1834, disegnata da Bertoja, incisa da A. Lazzari e pubblicata da D. Gallo nel 1831. Preserva il dettaglio cartografico originale e i riferimenti storici. Dataset creato all'EPFL."]},
                             {"en": ["The maps were scanned and then georeferenced to allow them to fit as closely as possible to the contemporary map of Venice."],
                              "fr": ["Les cartes ont été scannées puis géoréférencées pour leur permettre de s'adapter le plus possible à la carte contemporaine de Venise."],
                              "it": ["Le mappe sono state scansionate e quindi georeferenziate per consentire loro di adattarsi il più possibile alla mappa contemporanea di Venezia."]},
                              "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2F1834_BGGallo.png/full/max/0/default.jpg",
                              "1.0",
                              tuple_TR,
                              layers,
                              areas_id=venice_area_uuids
                             )

save_data_file_if_different('', 'map', [map_obj], '1834_gallo_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', layers, '1834_gallo_layers', RDE.LAYER.value)