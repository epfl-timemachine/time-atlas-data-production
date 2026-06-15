from functools import reduce
import os
import json 
import pandas as pd
import geopandas as gpd
import uuid
from shapely.geometry import Point
import sys
import argparse
# to retrieve the utils function used by all notebooks
parent_dir = os.path.abspath('../../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.data_modeling import *

# Parse command line arguments
parser = argparse.ArgumentParser(description='Merge observations and create POIs from dataset folders.')
parser.add_argument('--filter', type=str, default=None, 
                    help='Filter for dataset folder names (substring match). If not provided, all datasets are processed.')
args = parser.parse_args()

all_datasets = [f for f in os.listdir('../datasets') if os.path.isdir(os.path.join('../datasets', f))]

def find_all_observations_from_dataset_folder(dataset_folder: str) -> list:
    all_files = os.listdir(dataset_folder)
    obs_files = [os.path.join(dataset_folder, f) for f in all_files if f.endswith('.json') and 'observations' in f]
    return obs_files

# Apply filter if provided
if args.filter:
    all_datasets = [ds for ds in all_datasets if args.filter in ds]
    print(f"Filtering datasets with '{args.filter}': {len(all_datasets)} dataset(s) matched.")
dobs_suffix = 'observations'
all_obs_files = [find_all_observations_from_dataset_folder(os.path.join('../datasets', ds)) for ds in all_datasets]
all_obs_files = [item for sublist in all_obs_files for item in sublist]  # Flatten the list of lists
obs_data = []
all_datasets, all_obs_files
for fp in all_obs_files:
    with open(fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
        obs_data.extend(data['rde_objects'])

def filter_obs_that_needs_poi(obs_data: list) -> list:
    filtered_obs = []
    for obs in obs_data:
        if obs['part_of_point_of_interest'] or obs['part_of_point_of_interest'] == None:
            filtered_obs.append(obs)
    return filtered_obs

obs_data_pre_filtering = obs_data.copy()
obs_data = filter_obs_that_needs_poi(obs_data)
original_count = len(obs_data)
print(f"Loaded {original_count} Obs needing poi from {len(all_obs_files)} datasets.")

for obs in obs_data:
    if 'geometry' not in obs or not obs['geometry']:
        print(f"Observation {obs['id']} is missing geometry. Skipping.")
        continue

coords_obs = [[v['geometry']['coordinates'][0], v['geometry']['coordinates'][1], v] for v in obs_data]
df_obs = pd.DataFrame(coords_obs, columns=['lon', 'lat', 'obs_data'])

def round_up_to_n_decimals(value: float, n: int) -> float:
    factor = 10 ** n
    return round(value * factor) / factor

# rounding up to 5 decimals gives, at worse, a 60 cm loss of precision
df_obs['lon'] = df_obs['lon'].apply(lambda v: round_up_to_n_decimals(v, 5))
df_obs['lat'] = df_obs['lat'].apply(lambda v: round_up_to_n_decimals(v, 5))
df_obs_grouped = df_obs.groupby(by=['lon', 'lat']).agg(list).reset_index()

TM_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, 'https://timemachine.epfl.ch/operational/pois/')
df_obs_grouped['new_poi_uuid'] = df_obs_grouped.apply(lambda v: str(uuid.uuid5(TM_UUID5_NS, f"poi_{v.lon}_{v.lat}")), axis=1)
df_obs_grouped['obs_uuids'] = df_obs_grouped.apply(lambda v: [obs['id'] for obs in v.obs_data], axis=1)
new_count = len(df_obs_grouped)

gdf = gpd.GeoDataFrame(df_obs_grouped, geometry=gpd.points_from_xy(df_obs_grouped.lon, df_obs_grouped.lat), crs='EPSG:4326')
gdf_height = processing_points(gdf).to_crs('EPSG:4326')
gdf_poi = gpd.GeoDataFrame([produce_poi_obj(row.new_poi_uuid, row.geometry, row.terrain_height, row.building_height) for _, row in gdf_height.iterrows()])
# gdf_poi = gdf_poi.set_geometry('coordinate').set_crs('EPSG:4326')

QA_check_uuid_are_unique(gdf_poi.reset_index())
save_data_file_if_different('', 'points_of_interest', gdf_poi, f'all_pois', RDEType.POI.value)
print(f"Produced {len(gdf_poi)} PoIs from {original_count} Obs (aggregation rate of {(original_count - new_count) / original_count * 100:.2f}%) by aggregating Obs based on rounded coordinates.")

obs_uuid_to_poi_uuid = {}
for _, row in df_obs_grouped.iterrows():
    for obs_uuid in row.obs_uuids:
        obs_uuid_to_poi_uuid[obs_uuid] = row.new_poi_uuid

def update_obs_file(obs_fp:str, obs_uuid_to_poi_uuid: dict[str, str]) -> None:
    with open(obs_fp, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for obs in data['rde_objects']:
            if obs['id'] in obs_uuid_to_poi_uuid:
                obs['part_of_point_of_interest'] = obs_uuid_to_poi_uuid[obs['id']]
            else:
                obs['part_of_point_of_interest'] = None  # meaning this is an obs without a PoI
    with open(obs_fp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

for obs_file in all_obs_files:
    update_obs_file(obs_file, obs_uuid_to_poi_uuid)