import sys
import uuid
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from timeatlas.data_modeling import *
from timeatlas.RDEModel import RDEType

BEGIN_TR = 20240101
END_TR = 20251231
TR_OBJ = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_SLUG = "lausanne-qbuildings-map"
MAP_UUID = str(uuid.uuid5(LMAP_UUID5_NS, MAP_SLUG))
vector_layer_slug = f"{MAP_SLUG}-vector-layer"
vector_layer_uuid = str(uuid.uuid5(LMAP_UUID5_NS, vector_layer_slug))
lausanne_area_uuids = get_area_uuids_from_slugs('../../areas/data', ['city-lausanne-area', 'country-switzerland-area'])
zoom_lvl= [11,21]

layer_name = {"en": ["Footprints of buildings from the Qbuildings project"], "fr": ["Empreintes des bâtiments du projet Qbuildings"], "it": ["Impronte degli edifici del progetto Qbuildings"]}
layer_description = {"en": ["Footprints of the buildings from the Qbuildings project for the city of Lausanne."], "fr": ["Empreintes des bâtiments du projet Qbuildings pour la ville de Lausanne."], "it": ["Impronte degli edifici del progetto Qbuildings per la città di Losanna."]}
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
        extent=['POINT (6.555480158756834 46.56673049135603)', 'POINT (6.699951483951843 46.50001870963192)'],
        format='mvt',
        access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{vector_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf"
    )]
)

map_name = {"en":["Digital Layer – Lausanne Q Buildings"], "fr":["Couche numérique - Bâtiments Q de Lausanne"], "it":["Layer digitale - Edifici Q di Losanna"]}
map_description = {"en":["Vector data of the Q buildings in the city of Lausanne. Dataset created at EPFL."],
                    "fr":["Données vectorielles des bâtiments Q dans la ville de Lausanne. Jeu de données créé à l'EPFL."],
                    "it":["Dati vettoriali degli edifici Q nella città di Losanna. Dataset creato all'EPFL."]}
map_paradata = {"fr":["Les planches du cadastre rénové ont été vectorisées à l'aide de technique de computer vision modernes."], "en": ["The sheets of the renovated cadaster have been vectorized using modern computer vision techniques."], "it": ["Le tavole del catasto rinnovato sono state vettorializzate utilizzando moderne tecniche di computer vision."]}
map_1888 = produce_map_obj(
    MAP_UUID,
    MAP_SLUG,
    map_name,
    map_description,
    map_paradata,
    "https://image-timemachine.epfl.ch/iiif/3/lausanne%2Flayer_thumbnails%2Flausanne-qbuildings-vector.png/full/max/0/default.jpg",
    "1.0",
    TR_OBJ,
    [vector_layer],
    areas_id=lausanne_area_uuids
)

save_data_file_if_different('', 'map', [map_1888], 'lausanne_qbuildings_map', RDEType.MAP.value)
save_data_file_if_different('', 'layers', [vector_layer], 'lausanne_qbuildings_layers', RDEType.LAYER.value)