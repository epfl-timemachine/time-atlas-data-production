import sys
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BASE_SLUG = 'venice-1808'
MAP_SLUG = f"{BASE_SLUG}-map"
BEGIN_TR = 18080101
END_TR = 18081231
sommarioni_TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
sn_END_TR = 18481231
sn_TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(sn_END_TR, match_to_end=True))
MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
# cadastral layer uuid:
cadaster_slug = f"{MAP_SLUG}-cadaster"
bm_slug = f"{MAP_SLUG}-sommmarioni-base"
cadaster_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, cadaster_slug))
basemap_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, bm_slug))

streetnetwork_slug = f"{BASE_SLUG}-streetnetwork"
streetnetwork_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, streetnetwork_slug))
zoom_lvl= [11,21]

venice_area_uuid = get_single_object_uuid('../../areas/venice-area.json')

sommarioni_bm_layer = produce_layer_obj(basemap_layer_uuid,
                                        bm_slug,
                                         {"en": ["Historical maps of the parcels"],
                                          "fr": ["Cartes historiques des parcelles"],
                                            "it": ["Mappe storiche delle particelle"]},
                                        {"en": ["The historical maps of the parcels are the digital facsimile of the original cadaster map."],
                                         "fr": ["Les cartes historiques des parcelles sont le fac-similé numérique de la carte cadastrale originale."],
                                         "it": ["Le mappe storiche delle particelle sono il facsimile digitale della mappa catastale originale."]},
                                         sommarioni_TR,
                                         MAP_UUID,
                                         is_vector=False,
                                         layer_configs=[produce_layer_config(
                                          str(uuid.uuid5(VMAP_UUID5_NS, f'{bm_slug}-config-1')),
                                          zoom_lvl=zoom_lvl,
                                          access_url="https://geo-timemachine.epfl.ch/geoserver/www/tilesets/venice/sommarioni/{z}/{x}/{y}.png",
                                          format='xyz'
                                          )]
                                        )
 
sommarioni_parcel_layer = produce_layer_obj(cadaster_layer_uuid, 
                                            cadaster_slug,
                                          {"en": ["Parcels of 1808"],
                                           "fr": ["Parcelles de 1808"],
                                           "it": ["Particelle del 1808"]},
                                           {"en": ["The parcels of 1808 are the vectorized representation of the parcels from the original cadaster"],
                                            "fr": ["Les parcelles de 1808 sont la représentation vectorisée des parcelles du cadastre original"],
                                            "it": ["Le particelle del 1808 sono la rappresentazione vettoriale delle particelle del catasto originale"]},
                                            sommarioni_TR,
                                            MAP_UUID,
                                            is_vector=True,
                                            layer_configs=[produce_layer_config(
                                              str(uuid.uuid5(VMAP_UUID5_NS, f'{cadaster_slug}-config-1')),
                                              zoom_lvl=zoom_lvl,
                                              access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{cadaster_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf",
                                              format='mvt'
                                              )]
                                            )

sommarioni_sn_layer = produce_layer_obj(streetnetwork_layer_uuid,
                                        streetnetwork_slug,
                                        {"en": ["Street network of 1808"],
                                         "fr": ["Réseauviaire de 1808"],
                                         "it": ["Rete stradale del 1808"]},
                                        {"en": ["The street network of 1808 is the vectorized representation of the street network from the original cadaster"],
                                         "fr": ["Le réseauviaire de 1808 est la représentation vectorisée du réseau viaire du cadastre original"],
                                         "it": ["La rete stradale del 1808 è la rappresentazione vettoriale della rete stradale del catasto originale"]},
                                         sn_TR,
                                         MAP_UUID,
                                         is_vector=True,
                                         layer_configs=[produce_layer_config(
                                              str(uuid.uuid5(VMAP_UUID5_NS, f'{streetnetwork_slug}-config-1')),
                                              zoom_lvl=zoom_lvl,
                                              access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{streetnetwork_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf",
                                              format='mvt'
                                              )]
                                        )
                                         

layers = [sommarioni_bm_layer, sommarioni_parcel_layer, sommarioni_sn_layer]
layer_ids = [l['uuid'] for l in layers]
eighteen_o_eight_map_obj = produce_map_obj(MAP_UUID, 
                             MAP_SLUG,
                             {"en": ["1808 – Digital Facsimile of the Cadastral Map"],
                              "fr": ["1808 - Fac-similé numérique de la carte cadastrale"],
                              "it": ["1808 - Facsimile digitale della mappa catastale"]},
                             {"en": ["Digitized version of the cadastral map dated around 1808, commonly referred to as the “Napoleonic Cadaster.” Preserves the original visual structure and toponyms for reference and alignment. Dataset created at EPFL."],
                              "fr": ["Version numérisée de la carte cadastrale datée vers 1808, communément appelée « Cadastre napoléonien ». Préserve la structure visuelle originale et les toponymes pour référence et alignement. Jeu de données créé à l'EPFL."],
                              "it": ["Version digitalizzata della mappa catastale datata intorno al 1808, comunemente chiamata « Catasto napoleonico ». Preserva la struttura visiva originale e i toponimi per riferimento e allineamento. Dataset creato all'EPFL."]},
                             {"en": ["The maps were vetcorized into geometries through computer vision techniques and then manually corrected and expanded."],
                              "fr": ["Les cartes ont été vectorisées en géométries grâce à des techniques de vision par ordinateur, puis corrigées et étendues manuellement."],
                              "it": ["Le mappe sono state vettorializzate in geometrie attraverso tecniche di visione artificiale e quindi corrette ed espandere"]},
                              "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2Fsommarioni_rialto.png/full/max/0/default.jpg",
                              "1.0",
                              sn_TR,
                              layer_ids,
                              areas_id=[venice_area_uuid]
                             )

save_data_file_if_different('', 'map', [eighteen_o_eight_map_obj], '1808_sommarioni_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', layers, '1808_sommarioni_layers', RDE.LAYER.value)