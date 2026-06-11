"""
produce_sommarioni_sn_data_v2.py

Rewrite of produce_sommarioni_sn_data.py using the timeatlas library classes
directly, without procedural wrappers from utils/data_modeling.

UUID generation intentionally replicates the original CSV-serialisation strategy
so that all output UUIDs are byte-for-byte identical to the legacy script.
"""
import json
import os
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
from datetime import datetime as dt
from pathlib import Path
from tqdm import tqdm

# TODO: remove once the library is stable enough for direct installation through pip
parent_dir = os.path.abspath('../../../')
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

timeatlas_dir = os.path.join(parent_dir, 'time-atlas-python')
if timeatlas_dir not in sys.path:
    sys.path.insert(0, timeatlas_dir)

from timeatlas.RDEModel import (
    UUIDManager,
    RDETimeRange,
    HistoricalRecord,
    Observation,
    Geometry,
    Dataset,
)
from timeatlas.helpers import (
    _datetime_from_int,
    _get_layer_uuid,
    _get_filepath_like,
    _clean_metadata,
)
from timeatlas.TimeAtlas import RDECollection

gpd.options.io_engine = "pyogrio"

# ── Configuration ──────────────────────────────────────────────────────────────
with open('dataproduction_config.json') as f:
    DATA_CONFIG = json.load(f)

uuid_mgr = UUIDManager(DATA_CONFIG['UUID_NAMESPACE'])

DS_SLUG = DATA_CONFIG['DATASET_CONFIGURATION']['slug']
DS_UUID = uuid_mgr._generate_uuid(DS_SLUG)

DATA_FOLDER = ''          # current directory (rde/datasets/venice-1808-street-network/)
MAP_FOLDER  = '../../maps/venice-1808-sommarioni/'
TR = RDETimeRange(
    start_time=_datetime_from_int(DATA_CONFIG['TIMERANGE_MINIMUM']),
    end_time=_datetime_from_int(DATA_CONFIG['TIMERANGE_MAXIMUM'], match_to_end=True),
)

# ── Area and layer references ──────────────────────────────────────────────────
sn_layer_uuid = _get_layer_uuid(
    _get_filepath_like(MAP_FOLDER + 'layers', 'json'),
    'street',
)

# ── Source data and cleaning ────────────────────────────────────────────────────────────────
gdf = gpd.read_file('src/1808_TOPONOMASTICA.shp')
gdf = gdf[~gdf.geometry.isna()]
gdf['NAME']   = gdf['NAME'].str.replace('_', ' ')
gdf['length'] = gdf['lenght'].apply(lambda s: str(s) + 'm' if not pd.isna(s) else s)
gdf = gdf.drop(columns=['lenght', 'id']).reset_index()

# ── Build entities ─────────────────────────────────────────────────────────────

# Geometry UUIDs must be seeded from the ORIGINAL CRS (before reprojection),
# matching the order of operations in the legacy script.
orig_geoms = gdf.geometry.tolist()
gdf = gdf.set_geometry('geometry').to_crs('EPSG:4326')

geometries, hrs, obs_list = [], [], []

for i, (_, row) in enumerate(tqdm(gdf.iterrows(), total=len(gdf), desc="Building entities")):
    # Geometry seed: pandas CSV quotes WKT that contains commas (any LineString/Polygon),
    # producing '"WKT"\n'. Centroid (Point) and index (int) need no quoting.
    geom_wkt  = str(orig_geoms[i])
    geom_uuid = uuid_mgr._generate_uuid(f'"{geom_wkt}"\n' if ',' in geom_wkt else f'{geom_wkt}\n')
    centroid  = row.geometry.centroid
    obs_uuid  = uuid_mgr._generate_uuid(str(centroid) + '\n')
    hr_uuid   = uuid_mgr._generate_uuid(str(row['index']) + '\n')

    geometries.append(Geometry(id=geom_uuid, geometry=row.geometry, part_of_layer=sn_layer_uuid))
    obs_list.append(Observation(
        id=obs_uuid,
        historical_record=hr_uuid,
        geometry=centroid,
        has_geometries=[geom_uuid],
        part_of_point_of_interest=True,
    ))
    hrs.append(HistoricalRecord(
        id=hr_uuid,
        dataset=DS_UUID,
        time_range=TR,
        paradata='m',
        has_observations=[obs_uuid],
        metadata=_clean_metadata(row[['NAME', 'length']].to_dict()),
    ))

# ── Build Dataset entity ───────────────────────────────────────────────────────
CONF = DATA_CONFIG['DATASET_CONFIGURATION']
dataset = Dataset.constructor_from_dataconfiguration_file_and_dataframe(
    'dataproduction_config.json',
    gdf,
    ds_id = DS_UUID
)

# ── Validate and save ──────────────────────────────────────────────────────────
# Combine all entities in one collection to validate cross-references
full_collection = RDECollection(hrs + obs_list + [dataset] + geometries)
full_collection.validate_data()
print("Validation passed.")

# Geometry collection → MAP_FOLDER
full_collection.save_rde_to_files(MAP_FOLDER, overwrite=False, rde_types=[Geometry])
print(f"Saved {len(geometries)} geometry objects to {MAP_FOLDER}")

# HR + Obs + Dataset → DATA_FOLDER (current dir)
full_collection.save_rde_to_files(DATA_FOLDER or '.', overwrite=False, rde_types=[HistoricalRecord, Observation, Dataset])
print(
    f"Saved {len(hrs)} HRs, {len(obs_list)} observations, "
    f"and 1 dataset object to {DATA_FOLDER or 'root directory'}"
)
