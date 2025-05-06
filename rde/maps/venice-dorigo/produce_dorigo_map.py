import sys
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BASE_SLUG = 'venice-dorigo'
MAP_SLUG = f"{BASE_SLUG}-map"
BEGIN_TR = 9460101
END_TR = 14081231
TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
# cadastral layer uuid:
dorigo_zone_slug = f"{MAP_SLUG}-zones"
zones_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, dorigo_zone_slug))

# the two corners of the bounding box of the area.
extent =  [1370421.2197, 5692718.6843, 1376129.1641, 5689219.1288]

# transforming those two corners into a closed polygon.
extent_as_point = list(zip(extent, extent[1:] + extent[:1]))
extent_as_point = extent_as_point + [extent_as_point[0]]
wgs84_extent = [[p.x, p.y] for p in [to_wgs84_from_epsg3857(e[0], e[1]) for e in extent_as_point]]
zoom_lvl= [11,21]

venice_area_uuid = get_single_object_uuid('../../areas/venice-area.json')
 
contemporary_edifici_layer = produce_layer_obj(zones_layer_uuid, 
                                            dorigo_zone_slug,
                                          {"en": ["Ownership zones of medieval building from Venice according to Dorigo's study"],
                                           "fr": ["Zones de propriété des bâtiments médiévaux de Venise selon l'étude de Dorigo"],
                                            "it": ["Zone di proprietà degli edifici medievali di Venezia secondo lo studio di Dorigo"]},
                                           {"en": ["The footprints of Dorigo zones are the vectorized representation of the zones of ownership of the city of Venice during the medieval period."],
                                            "fr": ["Les empreintes des zones de Dorigo sont la représentation vectorisée des zones de propriété de la ville de Venise pendant la période médiévale."],
                                            "it": ["Le impronte delle zone di Dorigo sono la rappresentazione vettoriale delle zone di proprietà della città di Venezia durante il periodo medievale."]},
                                            TR,
                                            MAP_UUID,
                                            is_vector=True,
                                            layer_configs=[produce_layer_config(
                                              str(uuid.uuid5(VMAP_UUID5_NS, f'{dorigo_zone_slug}-config-1')),
                                              zoom_lvl=zoom_lvl,
                                              extent=wgs84_extent,
                                              access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{zones_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf",
                                              format='mvt'
                                              )]
                                            )

layers = [contemporary_edifici_layer]
layer_ids = [l['uuid'] for l in layers]
contemporary_map = produce_map_obj(MAP_UUID, 
                             MAP_SLUG,
                             {"en": ["Digital Layer - 1000–1414 – Virtual Zoning from Secondary Sources"],
                              "fr": ["Couche numérique - 1000–1414 - Zonage virtuel à partir de sources secondaires"],
                              "it": ["Strato digitale - 1000–1414 - Zonizzazione virtuale da fonti secondarie"]},
                             {"en": ["Vector layer representing zones of property ownership in medieval Venice, based on interpretations from Dorigo’s study Venezia Romanica. Digitally reconstructed from textual analysis of historical sources. Information geolocated by machine learning algorithms. Automatic checking.  Dataset created at EPFL."],
                              "fr": ["Couche vectorielle représentant les zones de propriété à Venise médiévale, basée sur des interprétations de l'étude de Dorigo Venezia Romanica. Reconstruit numériquement à partir d'une analyse textuelle de sources historiques. Informations géolocalisées par des algorithmes d'apprentissage automatique. Vérification automatique. Jeu de données créé à l'EPFL."],
                              "it": ["Layer vettoriale che rappresenta le zone di proprietà a Venezia medievale, basata su interpretazioni dello studio di Dorigo Venezia Romanica. Ricostruito digitalmente da un'analisi testuale di fonti storiche. Informazioni geolocalizzate da algoritmi di apprendimento automatico. Verifica automatica. Dataset creato all'EPFL."]},
                             {"en": ["Extracted using cutting edge computer vision techniques."],
                              "fr": ["Extraites à l'aide de techniques de vision par ordinateur de pointe."],
                              "it": ["Estratto utilizzando tecniche di visione artificiale all'avanguardia."]},
                              "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2Fdorigo_zones.png/full/max/0/default.jpg",
                              "1.0",
                              TR,
                              layer_ids,
                              areas_id=[venice_area_uuid]
                             )

save_data_file_if_different('', 'map', [contemporary_map], 'dorigo_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', layers, 'dorigo_layers', RDE.LAYER.value)