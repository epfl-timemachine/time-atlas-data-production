import sys
import uuid
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BEGIN_TR = 18880101
END_TR = 18881231
TR_OBJ = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_SLUG = "lausanne-1888-cadastre-renove-map"
MAP_UUID = str(uuid.uuid5(LMAP_UUID5_NS, MAP_SLUG))
vector_layer_slug = f"{MAP_SLUG}-vector-layer"
vector_layer_uuid = str(uuid.uuid5(LMAP_UUID5_NS, vector_layer_slug))

lausanne_area_uuid = get_single_object_uuid('../../areas/lausanne-area.json')
# the list(map(list)) thing makes it so the result of the function compoisition is a list of list instead of tuples (prevents an issue when saving the file to json format)
zoom_lvl= [11,21]

layer_name = {"en": ["Cadastral vectors of 1888"], "fr": ["Vecteurs cadastraux de 1888"], "it": ["Vettori catastali del 1888"]}
layer_description = {"en": ["Vectors of the renovated cadaster of 1888 for the city of Lausanne."], "fr": ["Vecteurs du cadastre rénové de 1888 pour la ville de Lausanne."], "it": ["Vettori del catasto rinnovato del 1888 per la città di Losanna."]}
vector_layer = produce_layer_obj(
    vector_layer_uuid,
    vector_layer_slug,
    layer_name,
    layer_description,
    TR_OBJ,
    MAP_UUID,
    is_vector=True,
    layer_configs=[produce_layer_config(
        str(uuid.uuid5(LMAP_UUID5_NS, f'{vector_layer_slug}-config-1')),
        zoom_lvl=zoom_lvl,
        format='mvt',
        access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{vector_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf"
    )]
)

map_name = {"en":["Digital Layer – 1808 Cadastral Footprints"],
            "fr":["Couche numérique - Empreintes cadastrales de 1808"],
            "it":["Layer digitale - Impronte catastali del 1808"]}
map_description = {"en":["Vector data extracted from the cadastral map of Lausanne, dated 1888. Dataset created at EPFL."],
                    "fr":["Données vectorielles extraites de la carte cadastrale de Lausanne, datée de 1888. Jeu de données créé à l'EPFL."],
                    "it":["Dati vettoriali estratti dalla mappa catastale di Losanna, datata 1888. Dataset creato all'EPFL."]}
map_paradata = {"fr":["Les planches du cadastre rénové ont été vectorisées à l'aide de technique de computer vision modernes."], "en": ["The sheets of the renovated cadaster have been vectorized using modern computer vision techniques."], "it": ["Le tavole del catasto rinnovato sono state vettorializzate utilizzando moderne tecniche di computer vision."]}
map_1888 = produce_map_obj(
    MAP_UUID,
    MAP_SLUG,
    map_name,
    map_description,
    map_paradata,
    "https://image-timemachine.epfl.ch/iiif/3/venice%2Flayer_thumbnails%2Flausanne-1888-cadastre-vector.png/full/max/0/default.jpg",
    "1.0",
    TR_OBJ,
    [vector_layer_uuid],
    areas_id=[lausanne_area_uuid]
)

save_data_file_if_different('', 'map', [map_1888], 'lausanne_cadastre_renove_1888_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', [vector_layer], 'lausanne_cadastre_renove_1888_layers', RDE.LAYER.value)