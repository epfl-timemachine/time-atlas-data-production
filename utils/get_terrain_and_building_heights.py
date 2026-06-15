import os
import geopandas as gpd
import numpy as np
import mercantile
import requests
import shapely
import argparse
from platformdirs import user_cache_dir
from PIL import Image
from mapbox_vector_tile import decode
from shapely.geometry import shape
from dotenv import load_dotenv
from tqdm import tqdm

# environment variable for MapTiler API key
load_dotenv()
maptiler_key = os.getenv("MAPTILER_API_KEY")
if maptiler_key is None:
    raise ValueError("MAPTILER_API_KEY environment variable not set. Please set it to your MapTiler API key.")

# Set up cache directories
cachedir = user_cache_dir("time-atlas-data-production", "time-machine-unit")
TERRAIN_CACHE = os.path.join(cachedir, "maptiler_cache", "terrain")
VECTOR_CACHE = os.path.join(cachedir, "maptiler_cache", "vector")
OS_SEP = os.path.sep
TERRAIN_CACHE_FMT = OS_SEP.join([TERRAIN_CACHE, '{z}', '{x}', '{y}.webp'])
maptiler_terrain_cache_path = lambda x, y, z: TERRAIN_CACHE_FMT.format(z=z, x=x, y=y)
VECTOR_CACHE_FMT = OS_SEP.join([VECTOR_CACHE, '{z}', '{x}', '{y}.pbf'])
maptiler_vector_cache_path = lambda x, y, z: VECTOR_CACHE_FMT.format(z=z, x=x, y=y)

maptiler_terrain_url = lambda x, y, z: f"https://api.maptiler.com/tiles/terrain-rgb-v2/{z}/{x}/{y}.webp?key={maptiler_key}"
maptiler_vector_url = lambda x, y, z: f"https://api.maptiler.com/tiles/v3-openmaptiles/{z}/{x}/{y}.pbf?key={maptiler_key}"

highest_zoom_level = 14
tile0 = mercantile.xy_bounds(0, 0, 0)
tile_size_m = (tile0.top - tile0.bottom) / 2 ** highest_zoom_level
terrain_tile_size_px = 512
vector_tile_size_px = 4096

EPSILON = 0.00001

# fake headers
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Priority": "u=0, i",
    "Upgrade-insecure-requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
}

def get_terrain_tile(x, y, z):
    cache_path = maptiler_terrain_cache_path(x, y, z)

    if not os.path.exists(cache_path):
        url = maptiler_terrain_url(x, y, z)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        # print("Downloading height tile...", url)
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            print(f"Error: {response.status_code} - {response.reason}")
            raise Exception(f"Failed to download terrain tile: {response.status_code} - {response.reason}")

        with open(cache_path, "wb") as f:
            f.write(response.content)

    rgba_img = Image.open(cache_path)

    rgb_img = rgba_img.convert('RGB')
    rgb_img_data = np.array(rgb_img, np.float32)
    return rgb_img_data

def get_vector_tile(x, y, z):
    cache_path = maptiler_vector_cache_path(x, y, z)
    if not os.path.exists(cache_path):
        url = maptiler_vector_url(x, y, z)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        # print("Downloading vector tile...", url)
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            print(f"Error: {response.status_code} - {response.reason}")
            raise Exception(f"Failed to download vector tile: {response.status_code} - {response.reason}")
        data = response.content
        
        with open(cache_path, "wb") as f:
            f.write(response.content)
    with open(cache_path, "rb") as f:
        data = f.read()

    decoded_tile = decode(data)
    try:
        features = decoded_tile['building']['features']
    except KeyError as e:
        if 'building' in e.args:
            print(f"Error decoding vector tile no building found for feature index: ", x, y, z)
        return []
    shapely_features = list(map(lambda feature: {
        "geometry": shape(feature["geometry"]),
        "render_height": feature["properties"]["render_height"]}, features))

    return shapely_features


def rounding_to_n_decimals(value: float, n: int) -> float:
    factor = 10 ** n
    return round(value * factor) / factor

def processing_points(points: gpd.GeoDataFrame, format_rde: bool = False) -> gpd.GeoDataFrame:
    '''
    Assigns terrain and building heights to point features.
    Args:
        points (gpd.GeoDataFrame): GeoDataFrame containing point features.
        format_rde (bool): If True, format the output for RDEType. (storing building and terrain height in a single column)
    Returns:
        gpd.GeoDataFrame: GeoDataFrame with terrain and building heights assigned to point features.
    '''
    points = points.to_crs("EPSG:3857")
    # determine the tile coordinates
    points["tile_x"] = np.floor((points.geometry.x - tile0.left) / tile_size_m).astype(np.uint32)
    points["tile_y"] = np.ceil(2 ** highest_zoom_level - 1 - (points.geometry.y - tile0.bottom) / tile_size_m).astype(
        np.uint32)

    # EPSILON needed to avoid rounding issues near the tile borders
    # calculate normalized tile coordinates (0-1)
    points["normalized_left"] = (EPSILON + points.geometry.x - (tile0.left + points.tile_x * tile_size_m)) / tile_size_m
    points["normalized_top"] = (EPSILON + points.geometry.y - (
                tile0.top - (points.tile_y + 1) * tile_size_m)) / tile_size_m

    # scale to terrain tiles (reverse y-coordinates since these are image coordinates)
    points["terrain_x"] = np.floor(points["normalized_left"] * terrain_tile_size_px).astype(int)
    points["terrain_y"] = (terrain_tile_size_px - np.ceil(points["normalized_top"] * terrain_tile_size_px)).astype(int)

    # scale to vector tiles (keep inverted y-coordinates)
    points["vector_x"] = np.floor(points["normalized_left"] * vector_tile_size_px).astype(int)
    points["vector_y"] = np.floor(points["normalized_top"] * vector_tile_size_px).astype(int)

    points = points.sort_values(['tile_x', 'tile_y'], ascending=[True, True])

    previous_tile_x, previous_tile_y = None, None
    terrain_height_values = []
    building_height_values = []

    num_points = len(points)

    for _, row in tqdm(points.iterrows(), desc="Processing elevation data", total=num_points):
        tile_x, tile_y = row.tile_x, row.tile_y

        if (tile_x != previous_tile_x or tile_y != previous_tile_y):
            try:
                rgb_img_data = get_terrain_tile(tile_x, tile_y, highest_zoom_level)
                shapely_features = get_vector_tile(tile_x, tile_y, highest_zoom_level)
            except Exception as e:
                print(f"Error fetching tile data for tile ({tile_x}, {tile_y}): {e}")
                # otherwise mismatch in length assignation later.
                terrain_height_values.append(0)
                building_height_values.append(0)
                continue

        height_rgb = rgb_img_data[row.terrain_y, row.terrain_x]
        # decode height
        height = -10000 + ((height_rgb[0] * 256 * 256 + height_rgb[1] * 256 + height_rgb[2]) * 0.1)
        terrain_height_values.append(height)

        found = False

        for feature in shapely_features:
            # check if the point is inside the building polygon
            if (shapely.intersects_xy(feature["geometry"], row.vector_x, row.vector_y)):
                building_height_values.append(feature["render_height"])
                found = True
                break

        if not found:
            building_height_values.append(0)

        previous_tile_x = tile_x
        previous_tile_y = tile_y

    points["terrain_height"] = [rounding_to_n_decimals(vs, 1) for vs in terrain_height_values]
    points["building_height"] = [rounding_to_n_decimals(vs, 1) for vs in building_height_values]

    # remove temporary columns
    points = points.drop(columns=["tile_x", "tile_y", "normalized_left", "normalized_top", "terrain_x", "terrain_y", "vector_x", "vector_y"])
    if format_rde:
        points['height'] = points.apply(lambda row: {"terrain": row['terrain_height'], "building": row['building_height']}, axis=1)
        points = points.drop(columns=["terrain_height", "building_height"])
        points = points.to_crs("EPSG:4326")
    return points

if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument("--input_file_path", type=str, required=True, help="Path to the input GeoJSON file")
    args.add_argument("--output_file_path", type=str, required=True, help="Path to the output GeoJSON file")
    args = args.parse_args()
    input_file_path = args.input_file_path
    output_file_path = args.output_file_path
    if not os.path.exists(input_file_path):
        raise FileNotFoundError(f"Input file {input_file_path} does not exist.")
    if os.path.exists(output_file_path):
        raise FileExistsError(f"Output file {output_file_path} already exists.")
    
    points = gpd.read_file(input_file_path)
    points = processing_points(points)
    points.to_file(output_file_path, driver="GeoJSON")