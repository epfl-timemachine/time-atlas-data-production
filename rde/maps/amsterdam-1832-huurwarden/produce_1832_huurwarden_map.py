import sys
import uuid
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *
from utils.rde import RDE

BEGIN_TR = 18320101
END_TR = 18881231
TR_OBJ = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
MAP_SLUG = "amsterdam-1832-huurwarden-map"
MAP_UUID = str(uuid.uuid5(LMAP_UUID5_NS, MAP_SLUG))
vector_layer_slug = f"{MAP_SLUG}-vector-layer"
vector_layer_uuid = str(uuid.uuid5(AMAP_UUID5_NS, vector_layer_slug))
amsterdam_area_uuids = get_area_uuids_from_slugs('../../areas/data', ['city-amsterdam-area', 'country-kingdom-of-the-netherlands-area'])
zoom_lvl= [11,21]

layer_name = {"en": ["Cadastral vectors of 1888"], "fr": ["Vecteurs cadastraux de 1832"], "it": ["Vettori catastali del 1832"]}
layer_description = {"en": ["Vectors of the cadaster of 1832 for the city of Amsterdam."], "fr": ["Vecteurs du cadastre de 1832 pour la ville de Amsterdam."], "it": ["Vettori del catasto del 1832 per la città di Amsterdam."]}
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
        extent=['POINT (4.76151909680581 52.44411863756021)', 'POINT (5.078830875630967 52.24253392900561)'],
        format='mvt',
        access_url=f"https://geo-timemachine.epfl.ch/geoserver/TimeMachine/gwc/service/tms/1.0.0/TimeMachine:{vector_layer_uuid}@EPSG:900913@pbf/{{z}}/{{x}}/{{-y}}.pbf"
    )]
)

map_name = {"en":["Digital Layer – Amsterdam Cadastral Footprints"],
            "fr":["Couche numérique - Empreintes cadastrales d'Amsterdam"],
            "it":["Layer digitale - Impronte catastali di Amsterdam"]}
map_description = {"en":["Vector data extracted from the cadastral map of Amsterdam, dated 1832. Dataset created at EPFL."],
                    "fr":["Données vectorielles extraites de la carte cadastrale d'Amsterdam, datée de 1832. Jeu de données créé à l'EPFL."],
                    "it":["Dati vettoriali estratti dalla mappa catastale di Amsterdam, datata 1832. Dataset creato all'EPFL."]}
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
    areas_id=amsterdam_area_uuids
)

save_data_file_if_different('', 'map', [map_1888], 'amsterdam_huurwarden_1832_map', RDE.MAP.value)
save_data_file_if_different('', 'layers', [vector_layer], 'amsterdam_huurwarden_1832_layers', RDE.LAYER.value)