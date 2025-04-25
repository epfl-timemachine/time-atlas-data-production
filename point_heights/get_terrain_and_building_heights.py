"""
assigns terrain and building heights retrieved from tiles from the MapTiler API to point features
"""

import os
import geopandas as gpd
import numpy as np
import mercantile
import rasterio
import requests
import shapely
from PIL import Image
from mapbox_vector_tile import decode
from shapely.geometry import shape

# file format can be anything which is supported by geopandas
input_file_path = r"D:\Data\TimeAtlas\lausanne_point_sample.geojson"
# file format can be anything which is supported by geopandas
output_file_path = input_file_path.replace(".geojson", "_height.geojson")

maptiler_key = "XXXXXXXXXXXXX"

maptiler_terrain_cache_path = lambda x, y, z: rf"D:\Data\TimeAtlas\maptiler_cache\terrain\{z}\{x}\{y}.webp"
maptiler_vector_cache_path = lambda x, y, z: rf"D:\Data\TimeAtlas\maptiler_cache\vector\{z}\{x}\{y}.pbf"

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

    if (not os.path.exists(cache_path)):
        url = maptiler_terrain_url(x, y, z)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        print("Downloading height tile...", url)
        response = requests.get(url, headers=HEADERS)

        with open(cache_path, "wb") as f:
            f.write(response.content)

    rgba_img = Image.open(cache_path)

    rgb_img = rgba_img.convert('RGB')
    rgb_img_data = np.array(rgb_img, np.float32)

    """
    # debug height image
    height_img = -10000 + ((rgb_img_data[..., 0] * 256 * 256 + rgb_img_data[..., 1] * 256 + rgb_img_data[..., 2]) * 0.1)

    bbox = mercantile.xy_bounds(x, y, z)

    tf = rasterio.transform.from_bounds(
        bbox.left,
        bbox.bottom,
        bbox.right,
        bbox.top,
        width=512,
        height=512
    )

    with rasterio.open(cache_path.replace(".webp", ".tif"), "w", count=1, driver="GTiff", crs="EPSG:3857",
                       transform=tf, width=512, height=512, dtype=np.uint16) as dst:
        dst.write(height_img, 1)
    """
    return rgb_img_data


def get_vector_tile(x, y, z):
    cache_path = maptiler_vector_cache_path(x, y, z)

    if (not os.path.exists(cache_path)):
        url = maptiler_vector_url(x, y, z)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)

        print("Downloading vector tile...", url)
        response = requests.get(url, headers=HEADERS)

        with open(cache_path, "wb") as f:
            f.write(response.content)

    with open(cache_path, "rb") as f:
        data = f.read()

    decoded_tile = decode(data)

    features = decoded_tile['building']['features']

    shapely_features = list(map(lambda feature: {
        "geometry": shape(feature["geometry"]),
        "render_height": feature["properties"]["render_height"]}, features))

    return shapely_features


def main():
    points = gpd.read_file(input_file_path)
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

    for index, (_, row) in enumerate(points.iterrows()):
        print(f"Processing point {index + 1}/{num_points}...")

        tile_x, tile_y = row.tile_x, row.tile_y

        if (tile_x != previous_tile_x or tile_y != previous_tile_y):
            rgb_img_data = get_terrain_tile(tile_x, tile_y, highest_zoom_level)
            shapely_features = get_vector_tile(tile_x, tile_y, highest_zoom_level)

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

        if (not found):
            building_height_values.append(0)

        previous_tile_x = tile_x
        previous_tile_y = tile_y

    points["terrain_height"] = terrain_height_values
    points["building_height"] = building_height_values

    points = points[["_id", "geometry", "terrain_height", "building_height"]]
    points.to_file(output_file_path, driver="GeoJSON")


if __name__ == '__main__':
    main()