from shapely.geometry import Point, Polygon
import laspy 
import os
import geopandas as gpd 
from tqdm.notebook import tqdm
tqdm.pandas()

las_files_folder = 'qbuildings_lausanne_las_files/'
output_folder = 'qbuilding_segmented_las'
las_file_prefix = 'qbuilding'
gdf = gpd.read_file('qbuildings-lausanne.geojson')
gdf['geometry_lv95'] = gdf.to_crs(epsg=2056).geometry
gdf['geom_type'] = gdf.apply(lambda row: row.geometry.geom_type, axis=1)

def get_max_nesw_coords(polygon: Polygon) -> tuple[float, float, float, float]:
    '''
    returns the maximum north, east, south and west coordinates of a polygon
    '''
    minx, miny, maxx, maxy = polygon.bounds
    return maxy, maxx, miny, minx

gdf['north'], gdf['east'], gdf['south'], gdf['west'] = zip(*gdf.geometry_lv95.apply(lambda v: v.bounds))

def lv95_coord_to_square_idx(latitude: float, longitude: float) -> str:
    '''
    for its lidar data in LAS format, ch.swisstopo.swisssurface3d uses a square grid of 1km squared, which they are specified in they filename
    by the first 4 digits of the coordinates they hold, so a tuple of coordinates (253678, 1153626) means that the corresponding las data
    for this point will be in the file named "2536_1153.las"
    '''
    return f'{int(latitude/1000)}_{int(longitude/1000)}.las'

def all_possible_file_for_curr_bounds(north:float, east:float, south:float, west:float) -> set[str]:
    '''
    given the north, east, south and west coordinates of a polygon, returns the set of all possible las files that could contain data for this polygon
    '''
    possible_files = set()
    possible_files.add(lv95_coord_to_square_idx(north, east))
    possible_files.add(lv95_coord_to_square_idx(north, west))
    possible_files.add(lv95_coord_to_square_idx(south, east))
    possible_files.add(lv95_coord_to_square_idx(south, west))
    return list(possible_files)

gdf['filenames'] = gdf.apply(lambda r: all_possible_file_for_curr_bounds(r.north, r.east, r.south, r.west),axis=1)


def segment_las_cloudpoint_from_polygon(polygon: Polygon, las: laspy.lasdata.LasData, buffer: int = 1) -> laspy.lasdata.LasData:
    # first segment by the bounds of the polygon:
    polygon = polygon.buffer(buffer) # add a buffer of n meter to the polygon to be sure to include all the points that are close to the border of the polygon
    mask = (las.x >= polygon.bounds[0]-buffer) & (las.x <= polygon.bounds[2]+buffer) & (las.y >= polygon.bounds[1]-buffer) & (las.y <= polygon.bounds[3]+buffer)
    las = las[mask]
    point_array = list(map(lambda point: Point(point[0], point[1]), zip(las.points.x.scaled_array(), las.points.y.scaled_array())))
    point_array_w_index = list(zip(point_array, range(len(point_array))))
    filtered_points = list(map(lambda x: x[1], filter(lambda point: polygon.contains(point[0]), point_array_w_index)))
    # then segment by the polygon itself:
    return las[filtered_points]

def produce_output_filename(filenames:str) -> str:
    # sorting it so we produce the same output filename for all the times we need to generate a fused file for the same las files, independently of the order of the las files in the list
    vs = sorted([f.replace('.las', '') for f in filenames])
    return f'fused_{"_".join(vs)}.las'

def fusion_las_files(input_folder:str, las_files: list[str], output_file: str) -> None:
    '''
    given a list of las files, fuses them into one las file and saves it to the output file path
    '''
    las_data_copy = laspy.read(os.path.join(input_folder, las_files[0]))
    output_filepath = os.path.join(input_folder, output_file)
    las_data_copy.write(output_filepath)    
    with laspy.open(output_filepath, mode='a') as base_las:
        for f in las_files[1:]:
            with laspy.open(os.path.join(input_folder, f)) as las:
                for chunk in las.chunk_iterator(2_000_000):
                    base_las.append_points(chunk)

def segment_cloudpoint_from_polygon(polygon: Polygon, las_files: list[str], building_id:str, input_folder:str, output_folder: str) -> None:
    '''
    given a polygon and the las files, segments the point cloud of the las file to only keep the points that are inside the polygon
    '''
    output_filename = os.path.join(output_folder, f'{las_file_prefix}_{building_id}.las')
    if os.path.exists(output_filename):
        return
    if len(las_files) > 1:
        fused_filename = produce_output_filename(las_files)
        fused_filepath = os.path.join(input_folder, fused_filename)
        if os.path.exists(fused_filepath):
            las = laspy.read(fused_filepath)
        else:
            fusion_las_files(input_folder, las_files, fused_filename)
            las = laspy.read(fused_filepath)
    else:
        las = laspy.read(os.path.join(input_folder, las_files[0]))
    segmented = segment_las_cloudpoint_from_polygon(polygon, las)
    segmented.write(output_filename)

gdf.progress_apply(lambda r: segment_cloudpoint_from_polygon(r['geometry_lv95'], r['filenames'], r['id_building'], las_files_folder, output_folder), axis=1)
