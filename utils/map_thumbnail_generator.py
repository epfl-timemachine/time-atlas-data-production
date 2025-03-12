import rasterio
from rasterio.plot import show
from rasterio.windows import from_bounds
from pyproj import Transformer
import argparse
import matplotlib.pyplot as plt


RIALTO_EXTENT_NESW = [45.439886196, 12.339491847, 45.436191552, 12.331912182]


def generate_thumbnail(geotiff_path:str, output_path:str, extent_nesw:list[float], width=1024, height=768):
    with rasterio.open(geotiff_path) as src:
        geotiff_crs = src.crs
        
        # Define the transformer to convert from WGS:84 to the GeoTIFF's CRS
        transformer = Transformer.from_crs("EPSG:4326", geotiff_crs, always_xy=True)
        
        # Reproject the extent to the GeoTIFF's CRS & create a window from the reprojected extent
        west, south = transformer.transform(extent_nesw[3], extent_nesw[2])
        east, north = transformer.transform(extent_nesw[1], extent_nesw[0])
        window = from_bounds(west, south, east, north, src.transform)
        data = src.read(window=window)
        _, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)
        show(data, transform=src.window_transform(window), ax=ax)
        
        # Save the plot as a PNG
        plt.axis('off')
        plt.savefig(output_path, bbox_inches='tight', pad_inches=0)
        plt.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('geotiff_path', help='Path to the input GeoTIFF file')
    parser.add_argument('output_path', help='Path to save the output thumbnail as png')
    args = parser.parse_args()
    if not args.output_path.endswith('.png'):
        print('Output path must be a PNG file')
        exit(-1)
    if not args.geotiff_path.endswith('.tif'):
        print('Input file must be a GeoTIFF file')
        exit(-1)
    generate_thumbnail(args.geotiff_path, args.output_path, RIALTO_EXTENT_NESW)
