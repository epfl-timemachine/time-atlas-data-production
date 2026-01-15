import sys
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BASE_SLUG = 'venice-1729-ughi'
MAP_SLUG = f"{BASE_SLUG}-map"
BEGIN_TR = 17290101
END_TR = 17291231
tuple_TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
bm_slug = f"{MAP_SLUG}-base"
basemap_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, bm_slug))
zoom_lvl= [11,21]

venice_area_uuids = get_area_uuids_from_slugs('../../areas/data', ['city-venice-area', 'country-italy-area'])

ughi_bm_layer = produce_layer_obj(basemap_layer_uuid,
                                        bm_slug,
                                         {"en": ["Historical map of Venice from 1729"],
                                          "fr": ["Carte historique de Venise de 1729"],
                                            "it": ["Mappa storica di Venezia del 1729"]},
                                        {"en": ["The historical maps of the parcels are the digital facsimile of the original map."],
                                         "fr": ["Les cartes historiques des parcelles sont le fac-similé numérique de la carte originale."],
                                         "it": ["Le mappe storiche delle particelle sono il facsimile digitale della mappa originale."]},
                                         tuple_TR,
                                         MAP_UUID,
                                         is_vector=False,
                                         layer_configs=[produce_layer_config(
                                          str(uuid.uuid5(VMAP_UUID5_NS, f'{bm_slug}-config-1')),
                                          zoom_lvl=zoom_lvl,
                                          extent=['POINT (12.29960873939344 45.45578743012642)','POINT (12.371319068712321 45.41554116969911)'],
                                          access_url="https://geo-timemachine.epfl.ch/geoserver/gwc/service/wmts/rest/TimeMachine:venice-1729-lughi/raster/EPSG:900913x2/EPSG:900913x2:{z}/{y}/{x}?format=image/png",
                                          format='wmts'
                                          )]
                                        )

layers = [ughi_bm_layer]
layer_ids = [l['uuid'] for l in layers]
map_obj = produce_map_obj(MAP_UUID, 
                             MAP_SLUG,
                             {"en": ["Digital Facsimile of Ughi’s Map of Venice"],
                              "fr": ["Fac-similé numérique de la carte de Venise d'Ughi"],
                              "it": ["Facsimile digitale della mappa di Venezia di Ughi"]},
                             {"en": ["Digitized reproduction of Ludovico Ughi’s map of Venice, dated around 1729. Preserves the original cartographic detail and historical toponyms. Dataset created at EPFL."],
                              "fr": ["Reproduction numérisée de la carte de Venise de Ludovico Ughi, datée vers 1729. Préserve le détail cartographique original et les toponymes historiques. Jeu de données créé à l'EPFL."],
                              "it": ["Riproduzione digitalizzata della mappa di Venezia di Ludovico Ughi, datata intorno al 1729. Preserva il dettaglio cartografico originale e i toponimi storici. Dataset creato all'EPFL."]},
                             {"en": ["The maps were scanned and then georeferenced to allow them to fit as closely as possible to the contemporary map of Venice."],
                              "fr": ["Les cartes ont été scannées puis géoréférencées pour leur permettre de s'adapter le plus possible à la carte contemporaine de Venise."],
                              "it": ["Le mappe sono state scansionate e quindi georeferenziate per consentire loro di adattarsi il più possibile alla mappa contemporanea di Venezia."]},
                              "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2F1729_LUghi.png/full/max/0/default.jpg",
                              "1.0",
                              tuple_TR,
                              layer_ids,
                              areas_id=venice_area_uuids
                             )

save_data_file_if_different('', 'map', [map_obj], '1729_ughi_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', layers, '1729_ughi_layers', RDE.LAYER.value)