import sys
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BASE_SLUG = 'venice-1838-clarke'
MAP_SLUG = f"{BASE_SLUG}-map"
BEGIN_TR = 18380101
END_TR = 18381231
tuple_TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
bm_slug = f"{MAP_SLUG}-base"
basemap_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, bm_slug))
zoom_lvl= [11,21]

venice_area_uuids = get_area_uuids_from_slugs('../../areas/data', ['city-venice-area', 'country-italy-area'])

clarke_bm_layer = produce_layer_obj(basemap_layer_uuid,
                                        bm_slug,
                                         {"en": ["Historical map of Venice from 1838"],
                                          "fr": ["Carte historique de Venise de 1838"],
                                            "it": ["Mappa storica di Venezia del 1838"]},
                                        {"en": ["The historical maps of the parcels are the digital facsimile of the original map."],
                                         "fr": ["Les cartes historiques des parcelles sont le fac-similé numérique de la carte originale."],
                                         "it": ["Le mappe storiche delle particelle sono il facsimile digitale della mappa originale."]},
                                         tuple_TR,
                                         MAP_UUID,
                                         is_vector=False,
                                         layer_configs=[produce_layer_config(
                                          str(uuid.uuid5(VMAP_UUID5_NS, f'{bm_slug}-config-1')),
                                          zoom_lvl=zoom_lvl,
                                          access_url="https://geo-timemachine.epfl.ch/geoserver/gwc/service/wmts/rest/TimeMachine:venice-1838-wbclarke/raster/EPSG:900913x2/EPSG:900913x2:{z}/{y}/{x}?format=image/png",
                                          format='wmts'
                                          )]
                                        )

layers = [clarke_bm_layer]
layer_ids = [l['uuid'] for l in layers]
map_obj = produce_map_obj(MAP_UUID, 
                             MAP_SLUG,
                             {"en": ["Digital Facsimile of Clarke’s Map of Venice"],
                              "fr": ["Fac-similé numérique de la carte de Venise de Clarke"],
                              "it": ["Facsimile digitale della mappa di Venezia di Clarke"]},
                             {"en": ["Digitized reproduction of the 1838 map of Venice by William Branwhite Clarke. Preserves original geographic and cartographic details for reference and comparison. Dataset created at EPFL."],
                             "fr": ["Reproduction numérisée de la carte de Venise de 1838 par William Branwhite Clarke. Préserve les détails géographiques et cartographiques originaux pour référence et comparaison. Jeu de données créé à l'EPFL."],
                             "it": ["Riproduzione digitalizzata della mappa di Venezia del 1838 di William Branwhite Clarke. Preserva i dettagli geografici e cartografici originali per riferimento e confronto. Dataset creato all'EPFL."]},
                             {"en": ["The maps were scanned and then georeferenced to allow them to fit as closely as possible to the contemporary map of Venice."],
                              "fr": ["Les cartes ont été scannées puis géoréférencées pour leur permettre de s'adapter le plus possible à la carte contemporaine de Venise."],
                              "it": ["Le mappe sono state scansionate e quindi georeferenziate per consentire loro di adattarsi il più possibile alla mappa contemporanea di Venezia."]},
                              "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2F1838_WBClarke.png/full/max/0/default.jpg",
                              "1.0",
                              tuple_TR,
                              layer_ids,
                              areas_id=venice_area_uuids
                             )

save_data_file_if_different('', 'map', [map_obj], '1838_clarke_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', layers, '1838_clarke_layers', RDE.LAYER.value)