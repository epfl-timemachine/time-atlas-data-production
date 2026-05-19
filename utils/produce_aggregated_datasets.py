import os
from pathlib import Path
import json
from utils.data_modeling import save_data_file_if_different
from utils.data_modeling import today_date

ROOTS = ['1740_Catastici', '1808_Sommarioni', 'Garzoni']
DATA_FOLDER = 'aggregated_data'

# viva la programación funcional
flat_map = lambda f, xs: (y for ys in xs for y in f(ys))
all_data_files = list(map(str, flat_map(lambda r: Path(os.path.join(r, 'data')).rglob('*json'), ROOTS)))
geoms_types = ['_geometries_', '_obs_', '_poi_']

def aggregate_geojson_into_a_single_file(fps: list[str], save_fp:str, rde_type:str) -> None:
    geojson_fps = list(filter(lambda s: rde_type in s, fps))
    objs = list(map(lambda f: json.load(open(f, 'r')), geojson_fps))
    obj_header = objs[0].copy()
    features = list(flat_map(lambda s: s['features'], objs))
    obj_header['features'] = features
    obj_header['name'] = save_fp.split('/')[-1].replace('.geojson', '')
    with open(save_fp, 'w+', encoding='utf-8') as fp:
        json.dump(obj_header, fp, ensure_ascii=False)

if __name__ == '__main__':
    for g in geoms_types:
        aggregate_geojson_into_a_single_file(all_data_files, os.path.join(DATA_FOLDER, f'all_venice{g}{today_date()}.geojson'), g)

    all_hrs = list(flat_map(lambda f: json.load(open(f, 'r'))['rde_objects'], list(filter(lambda s: '_hr_' in s, all_data_files))))
    save_data_file_if_different(os.path.join(DATA_FOLDER, f'all_venice_hr_'), {'rde_objects':all_hrs})
    

    all_ds = list(map(lambda f: json.load(open(f, 'r')), list(filter(lambda s: '_dataset_' in s, all_data_files))))
    save_data_file_if_different(os.path.join(DATA_FOLDER, f'all_venice_dataset_'), {'rde_objects':all_ds})
    

    all_maps = list(map(lambda f: json.load(open(f, 'r')), list(filter(lambda s: '_map_' in s, all_data_files))))
    save_data_file_if_different(os.path.join(DATA_FOLDER, f'all_venice_maps_'), {'rde_objects':all_maps})
        