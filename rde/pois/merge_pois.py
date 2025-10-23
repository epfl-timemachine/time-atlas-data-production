from functools import reduce
import os
import json 
import pandas as pd
import uuid

all_datasets = [f for f in os.listdir('../datasets') if os.path.isdir(os.path.join('../datasets', f))]
all_poi_files = [os.path.join('../datasets/', ds, 'data/points_of_interest.json') for ds in all_datasets if os.path.exists(os.path.join('../datasets/', ds, 'data/points_of_interest.json'))]

pois_data = []
all_datasets, all_poi_files
for fp in all_poi_files:
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
        pois_data.extend(data['rde_objects'])

original_count = len(pois_data)
print(f"Loaded {original_count} POIs from {len(all_poi_files)} datasets.")

coords_poi = [[v['geometry']['coordinates'][0], v['geometry']['coordinates'][1], v] for v in pois_data]
df_poi = pd.DataFrame(coords_poi, columns=['lon', 'lat', 'poi_data'])

def merge_pois(pois: list[dict]) -> dict:
    represents = reduce(lambda acc, poi: acc.union(set(poi.get('represents', []))), pois, set() )
    main_poi = pois[0].copy()
    main_poi['represents'] = list(represents)
    return main_poi

def round_up_to_n_decimals(value: float, n: int) -> float:
    factor = 10 ** n
    return round(value * factor) / factor

# rounding up to 5 decimals gives, at worse, a 60 cm loss of precision
df_poi['lon'] = df_poi['lon'].apply(lambda v: round_up_to_n_decimals(v, 5))
df_poi['lat'] = df_poi['lat'].apply(lambda v: round_up_to_n_decimals(v, 5))
df_poi_grouped = df_poi.groupby(by=['lon', 'lat']).agg(lambda x: merge_pois(x.tolist())).reset_index()

def update_and_return(d: dict, updates: dict) -> dict:
    d.update(updates)
    return d

TM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, 'https://timemachine.epfl.ch/operational/pois/')
df_poi_grouped['new_poi_uuid'] = df_poi_grouped.apply(lambda v: str(uuid.uuid5(TM_UUID5_NS, f"poi_{v.lon}_{v.lat}")), axis=1)
df_poi_grouped['new_poi_data'] = df_poi_grouped.apply(lambda v: update_and_return(v.poi_data.copy(), {'uuid': v.new_poi_uuid}), axis=1)
import sys
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import now_ts

final_data_structure = {
 "name": "all_points_of_interest",
 "type_in_file": [
  now_ts()
 ],
 "creation_time": "2025-09-30T14:01:36.019883",
 "rde_objects": df_poi_grouped['new_poi_data'].tolist()
}
new_count = len(final_data_structure['rde_objects'])
print(f"Reduced POIs from {original_count} to {new_count} ({(original_count - new_count) / original_count * 100:.2f}%) by merging PoIs based on rounded coordinates.")

with open('points_of_interest.json', 'w', encoding='utf-8') as f:
    json.dump(final_data_structure, f, ensure_ascii=False, indent=2)