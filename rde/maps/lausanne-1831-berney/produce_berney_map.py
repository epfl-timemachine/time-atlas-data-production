import sys
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from timeatlas.data_modeling import *
from timeatlas.RDEModel import RDEType

BASE_SLUG = 'lausanne-1831'
MAP_SLUG = f"{BASE_SLUG}-map"
BEGIN_TR = 18310101
END_TR = 18311231
berney_TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
sn_END_TR = 18481231
sn_TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(sn_END_TR, match_to_end=True))
MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
# cadastral layer uuid:
cadaster_slug = f"{MAP_SLUG}-cadaster"
bm_slug = f"{MAP_SLUG}-berney-base"
cadaster_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, cadaster_slug))
basemap_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, bm_slug))

zoom_lvl= [11,21]

lausanne_area_uuids = get_area_uuids_from_slugs('../../areas/data', ['city-lausanne-area', 'country-switzerland-area'])

cadastre_bm_layer = produce_layer_obj(basemap_layer_uuid,
                                        bm_slug,
                                         {"en": ["Historical maps of the parcels"],
                                          "fr": ["Cartes historiques des parcelles"],
                                            "it": ["Mappe storiche delle particelle"]},
                                        {"en": ["The historical maps of the parcels are the digital facsimile of the original cadaster map."],
                                         "fr": ["Les cartes historiques des parcelles sont le fac-similé numérique de la carte cadastrale originale."],
                                         "it": ["Le mappe storiche delle particelle sono il facsimile digitale della mappa catastale originale."]},
                                         berney_TR,
                                         MAP_UUID,
                                         is_vector=False,
                                         layer_configs=[produce_layer_config(
                                          str(uuid.uuid5(VMAP_UUID5_NS, f'{bm_slug}-config-1')),
                                          zoom_lvl=zoom_lvl,
                                          extent= ['POINT (6.5820318420316335 46.60342159950106)','POINT (6.722700332883975 46.5047438639178)'],
                                          access_url="https://geo-timemachine.epfl.ch/geoserver/gwc/service/wmts/rest/TimeMachine:1831_Berney/raster/EPSG:900913x2/EPSG:900913x2:{z}/{y}/{x}?format=image/png",
                                          format='wmts'
                                          )]
                                        )
 
berney_parcel_layer = produce_layer_obj(cadaster_layer_uuid, 
                                            cadaster_slug,
                                          {"en": ["Parcels of 1831"],
                                           "fr": ["Parcelles de 1831"],
                                           "it": ["Particelle del 1831"]},
                                           {"en": ["The parcels of 1831 are the vectorized representation of the parcels from the original cadaster"],
                                            "fr": ["Les parcelles de 1831 sont la représentation vectorisée des parcelles du cadastre original"],
                                            "it": ["Le particelle del 1831 sono la rappresentazione vettoriale delle particelle del catasto originale"]},
                                            berney_TR,
                                            MAP_UUID,
                                            is_vector=True,
                                            layer_configs=[produce_layer_config(
                                              str(uuid.uuid5(VMAP_UUID5_NS, f'{cadaster_slug}-config-1')),
                                              zoom_lvl=zoom_lvl,
                                              extent= ['POINT (6.58255360972122 46.60286672962382)', 'POINT (6.721715790231707 46.504844903558364)'],
                                              access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{cadaster_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf",
                                              format='mvt'
                                              )]
                                            )

                                         

layers = [cadastre_bm_layer, berney_parcel_layer]
eighteen_o_eight_map_obj = produce_map_obj(MAP_UUID, 
                             MAP_SLUG,
                             {"en": ["Digital Facsimile of the Cadastral Map"],
                              "fr": ["Fac-similé numérique de la carte cadastrale"],
                              "it": ["Facsimile digitale della mappa catastale"]},
                             {"en": ["Digitized version of the cadastral map dated around 1831, commonly referred to as the “Napoleonic Cadaster.” Preserves the original visual structure and toponyms for reference and alignment. Dataset created at EPFL."],
                              "fr": ["Version numérisée de la carte cadastrale datée vers 1831, communément appelée « Cadastre napoléonien ». Préserve la structure visuelle originale et les toponymes pour référence et alignement. Jeu de données créé à l'EPFL."],
                              "it": ["Version digitalizzata della mappa catastale datata intorno al 1831, comunemente chiamata « Catasto napoleonico ». Preserva la struttura visiva originale e i toponimi per riferimento e allineamento. Dataset creato all'EPFL."]},
                             {"en": ["The maps were vetcorized into geometries through computer vision techniques and then manually corrected and expanded."],
                              "fr": ["Les cartes ont été vectorisées en géométries grâce à des techniques de vision par ordinateur, puis corrigées et étendues manuellement."],
                              "it": ["Le mappe sono state vettorializzate in geometrie attraverso tecniche di visione artificiale e quindi corrette ed espandere"]},
                              "https://image-timemachine.epfl.ch/iiif/3/lausanne%2Flayer_thumbnails%2Flausanne_berney.png/full/max/0/default.jpg",
                              "1.0",
                              sn_TR,
                              layers,
                              areas_id=lausanne_area_uuids
                             )

save_data_file_if_different('', 'map', [eighteen_o_eight_map_obj], '1831_berney_map', RDEType.MAP.value)
save_data_file_if_different('', 'layers', layers, '1831_berney_layers', RDEType.LAYER.value)