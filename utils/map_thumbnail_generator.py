import rasterio
from rasterio.plot import show
from rasterio.windows import from_bounds
from pyproj import Transformer
import os
import argparse
import matplotlib.pyplot as plt
import owslib.wms


extent_dict = {
    'rialto': [45.439886196, 12.339491847, 45.436191552, 12.331912182],
    'lausanne_cathedral': [46.527416320, 6.642246776, 46.517441929, 6.627888480]
}
def generate_thumbnail_from_geotiff(geotiff_path:str, output_path:str, extent_nesw:list[float], width=1024, height=768):
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

def generate_thumbnail_from_wms_url(wms_url:str, output_path:str, extent_nesw:list[float], width=1024, height=768):
    
    wms = owslib.wms.WebMapService(wms_url, version='1.3.0')
    layer_name = list(wms.contents)[0]
    img = wms.getmap(
        layers=[layer_name],
        srs='EPSG:4326',
        bbox=(extent_nesw[3], extent_nesw[2], extent_nesw[1], extent_nesw[0]),
        size=(width, height),
        format='image/png',
        transparent=True
    )
    with open(output_path, 'wb') as out:
        out.write(img.read())

def generate_thumbnail_from_wmts_url(wmts_url:str, output_path:str, extent_nesw:list[float], width=1024, height=768):
    pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', help='Either a path to the input GeoTIFF file, or the URL of a WMTS service')
    parser.add_argument('output_path', help='Path to save the output thumbnail as png')
    parser.add_argument('extent', help=f'Available extents, zone offered are: {", ".join(extent_dict.keys())}')
    args = parser.parse_args()
    if not args.output_path.endswith('.png'):
        print('Output path must be a PNG file')
        exit(-1)
    if args.extent not in extent_dict:
        print(f'Extent "{args.extent}" not recognized. Available extents are: {", ".join(extent_dict.keys())}')
        exit(-1)
    if args.source.endswith('.tif'):
        if not os.path.exists(args.source):
            print(f'GeoTIFF file "{args.source}" does not exist.')
            exit(-1)
        generate_thumbnail_from_geotiff(args.source, args.output_path, extent_dict[args.extent])
    elif 'http' in args.source and ('wmts' in args.source or 'wms' in args.source):
        if 'wmts' in args.source:
            generate_thumbnail_from_wmts_url(args.source, args.output_path, extent_dict[args.extent])
        elif 'wms' in args.source:
            generate_thumbnail_from_wms_url(args.source, args.output_path, extent_dict[args.extent])
