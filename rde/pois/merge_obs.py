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
parser.add_argument('--output-dir', type=str, default='',
                    help='Directory for points_of_interest.json. Defaults to the shared rde/pois directory.')
parser.add_argument('--skip-height-enrichment', action='store_true',
                    help='Do not send coordinates to MapTiler; store neutral 0.0 terrain/building heights instead.')
parser.add_argument('--only-boolean-candidates', action='store_true',
                    help=(
                        'Aggregate only observations whose part_of_point_of_interest is the '
                        'raw boolean true. This makes dataset-local post-production idempotent '
                        'and leaves already-resolved UUID references untouched.'
                    ))
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
        poi_reference = obs['part_of_point_of_interest']
        if args.only_boolean_candidates:
            needs_poi = poi_reference is True
        else:
            # Legacy behavior supports older raw files that used null as the
            # unresolved marker. Boolean-only mode is safer for producers that
            # use false/null to designate spatial-only observations.
            needs_poi = bool(poi_reference) or poi_reference is None
        if needs_poi:
            filtered_obs.append(obs)
    return filtered_obs

obs_data_pre_filtering = obs_data.copy()
obs_data = filter_obs_that_needs_poi(obs_data)
original_count = len(obs_data)
print(f"Loaded {original_count} Obs needing poi from {len(all_obs_files)} datasets.")
if original_count == 0:
    normalised = 0
    if args.only_boolean_candidates:
        for obs_fp in all_obs_files:
            with open(obs_fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            changed = False
            for obs in data['rde_objects']:
                if obs['part_of_point_of_interest'] is False:
                    obs['part_of_point_of_interest'] = None
                    changed = True
                    normalised += 1
            if changed:
                with open(obs_fp, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
    print(
        'No unresolved observations found; '
        f'normalised {normalised} spatial-only references and left existing PoIs unchanged.'
    )
    sys.exit(0)

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
if args.skip_height_enrichment:
    gdf_height = gdf.copy()
    gdf_height['terrain_height'] = 0.0
    gdf_height['building_height'] = 0.0
    print('Height enrichment skipped; using neutral 0.0 terrain/building heights.')
else:
    gdf_height = processing_points(gdf).to_crs('EPSG:4326')

poi_data = [
    produce_poi_obj(
        row.new_poi_uuid,
        row.geometry,
        float(row.terrain_height),
        float(row.building_height),
    )
    for _, row in gdf_height.iterrows()
]

QA_check_uuid_are_unique(pd.DataFrame(poi_data))
if args.output_dir:
    os.makedirs(args.output_dir, exist_ok=True)
save_data_file_if_different(
    args.output_dir,
    'points_of_interest',
    poi_data,
    'all_pois',
    RDEType.POI.value,
    related_dataset_slugs=all_datasets if args.output_dir else None,
)
print(f"Produced {len(poi_data)} PoIs from {original_count} Obs (aggregation rate of {(original_count - new_count) / original_count * 100:.2f}%) by aggregating Obs based on rounded coordinates.")

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
            elif not args.only_boolean_candidates or obs['part_of_point_of_interest'] is False:
                obs['part_of_point_of_interest'] = None  # meaning this is an obs without a PoI
    with open(obs_fp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

for obs_file in all_obs_files:
    update_obs_file(obs_file, obs_uuid_to_poi_uuid)
