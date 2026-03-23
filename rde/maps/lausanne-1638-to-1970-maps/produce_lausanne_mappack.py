import sys
import os
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from timeatlas.data_modeling import *
from timeatlas.RDEModel import RDEType
from ast import literal_eval

df = pd.read_csv('../lausanne_map_pack_with_extents.csv')

# print(len(df))
# removed for now as there is 
df = df[df['slug'] != 'lausanne-1838-berney-centre']
# print(len(df))

layers = []
maps = []
for index, r in df.iterrows():
    slug = r['slug']
    extent = literal_eval(r['extent'])
    begin_tr = int(r['start_time'])*10000 + 101
    end_tr = int(r['end_time'])*10000 + 1231
    BASE_SLUG = slug
    MAP_SLUG = f"{BASE_SLUG}-map"
    BEGIN_TR = begin_tr
    END_TR = end_tr
    tuple_TR = (datetime_obj_from_int_time(BEGIN_TR), datetime_obj_from_int_time(END_TR, match_to_end=True))
    MAP_UUID = str(uuid.uuid5(VMAP_UUID5_NS, MAP_SLUG))
    bm_slug = f"{MAP_SLUG}-base"
    basemap_layer_uuid = str(uuid.uuid5(VMAP_UUID5_NS, bm_slug))
    zoom_lvl= [11,21]

    lausanne_area_uuids = get_area_uuids_from_slugs('../../areas/data', ['city-lausanne-area', 'country-switzerland-area'])

    bm_layer = produce_layer_obj(basemap_layer_uuid,
                                            bm_slug,
                                            {
                                            "en": [f"Historical Map of Lausanne from {r['start_time']}"],
                                            "fr": [f"Carte historique de Lausanne de {r['start_time']}"],
                                            "it": [f"Mappa storica di Losanna dal {r['start_time']}"],
                                            "de": [f"Historische Karte von Lausanne aus dem Jahr {r['start_time']}"]
                                            },
                                            {
                                            "en": [r['paradata_process']],
                                            "fr": [r['paradata_process_fr']],
                                            "it": [r['paradata_process_fr']],
                                            "de": [r['paradata_process_de']]
                                            },
                                            tuple_TR,
                                            MAP_UUID,
                                            is_vector=False,
                                            layer_configs=[produce_layer_config(
                                            str(uuid.uuid5(VMAP_UUID5_NS, f'{bm_slug}-config-1')),
                                            zoom_lvl=zoom_lvl,
                                            extent=extent,
                                            access_url=f"https://geo-timemachine.epfl.ch/geoserver/gwc/service/wmts/rest/TimeMachine:{slug}/raster/EPSG:900913x2/EPSG:900913x2:{{z}}/{{y}}/{{x}}?format=image/png",
                                            format='wmts'
                                            )]
                                            )

    layers.append(bm_layer)
    map_obj = produce_map_obj(MAP_UUID, 
                                MAP_SLUG,
                                {
                                "fr": [r['nom_fr']],
                                "it": [r['nom_it']],
                                "de": [r['nom_de']],
                                "en": [r['nom']]
                                },
                                {
                                "fr": [r['description']],
                                "it": [r['description_it']],
                                "de": [r['description_de']],
                                "en": [r['description_en']]
                                },
                                {
                                "en": [r['paradata_process']],
                                "fr": [r['paradata_process_fr']],
                                "it": [r['paradata_process_it']],
                                "de": [r['paradata_process_de']]
                                }, 
                                f"https://image-timemachine.epfl.ch/iiif/3/lausanne%2Flayer_thumbnails%2F{slug}.png/full/max/0/default.jpg",
                                "1.0",
                                tuple_TR,
                                layers,
                                areas_id=lausanne_area_uuids
                                )
    maps.append(map_obj)

save_data_file_if_different('', 'map', maps, '{slug}_map', RDEType.MAP.value)
save_data_file_if_different('', 'layers', layers, '{slug}_layers', RDEType.LAYER.value)