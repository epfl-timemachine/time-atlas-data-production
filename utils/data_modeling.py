import uuid
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon
import numpy as np
from pathlib import Path
from shapely.validation import explain_validity
from datetime import datetime as dt
from typing import Union
from functools import reduce
import json
import io
import os
from functools import reduce 
import typing
from collections import Counter
from datetime import datetime as dt
from .rde import RDE
from .get_terrain_and_building_heights import processing_points

UNIVERSAL_CRS = "EPSG:4326"

# so all areas have the same namespace to generate UUIDs
AREA_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, 'https://timemachine.epfl.ch/areas')

# so all maps have the same namespace to generate UUIDs
VMAP_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, 'https://timemachine.epfl.ch/venice/maps')
LMAP_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, 'https://timemachine.epfl.ch/lausanne/maps')
AMAP_UUID5_NS = uuid.uuid5(uuid.NAMESPACE_URL, 'https://timemachine.epfl.ch/amsterdam/maps')

def union_geom_from_geometry_ids_list(geom_ids:list[str], gdf: gpd.GeoDataFrame) -> Union[Polygon, MultiPolygon]:
    # as there can be multiple geometry_ids per line, we need to unite the geometries into a single one before generating the centroid that will serve as the GPS handle on the map.
    if len(geom_ids) > 1:
        geoms = gdf[gdf['id'].isin(geom_ids)]
        geom = geoms.union_all(method='unary')
    else:
        geom = gdf[gdf['id'] == geom_ids[0]]['geometry'].iloc[0]
    return geom

def find_closest_polygon(point: Point, polygon: MultiPolygon) -> Polygon:
    # we find the closest polygon to the point
    closest_polygon = None
    min_distance = float('inf')
    for p in list(polygon.geoms):
        d = p.distance(point)
        if d < min_distance:
            min_distance = d
            closest_polygon = p
    return closest_polygon

def constraint_point_to_center_of_one_polygon(point: Point, polygon: Union[Polygon, MultiPolygon]) -> Point:
    # if the point is not within the polygon, we move it to the center of the polygon.
    # code to visually test the function constraint_point_to_center_of_one_polygon, left here as debug:
    # import matplotlib.pyplot as plt
    # # plotting in the same plot all the geometries, the centroid and corrected centroid from the v variable
    # v = df[df['centroid'] != df['corrected_centroid']].iloc[0]
    # fig, ax = plt.subplots(figsize=(10, 10))
    # for geom in v.geometries.geoms:    
    #     xs, ys = geom.exterior.xy    
    #     ax.fill(xs, ys, alpha=0.5, fc='r', ec='none')
    # ax.plot(v.centroid.x, v.centroid.y, 'o', color='blue')
    # ax.plot(v.corrected_centroid.x, v.corrected_centroid.y, 'o', color='green')
    if type(polygon) == MultiPolygon:
        for p in list(polygon.geoms):
            if p.contains(point):
                return point
        return find_closest_polygon(point, polygon).centroid
    elif type(polygon) == Polygon:
        # edge case that I don't see happening, but just in case. 
        if not polygon.contains(point):
            return polygon.centroid
    return point


def get_filepath_like(file_prefix:str, extension:str) -> str:
    '''
    Mainly useful to get all the rde file generated that often have the date in the filename.
    Only providing the "stable" part of the file path (without the date) and its extension
    will return the filepath of the latest file generated satisfying the prefix and extension.
    '''
    file_name = file_prefix.split('/')[-1]
    path_prefix = file_prefix.replace(file_name, '')
    p = Path(path_prefix) if len(path_prefix) != 0 else Path('.')
    return sorted(list(p.rglob(f'{file_name}*.{extension}')))[-1]

def get_single_object_uuid(obj_fp:str) -> str:
    '''
    Useful to fetch uuid for object like area, dataset or dictionary.
    '''
    with open(obj_fp) as f:
        return json.load(f)['rde_objects'][0]['uuid']

def get_layer_uuid(layer_fp:str, slug_part:str) -> str:
    with open(layer_fp) as f:
        slug_uuids = [(v['slug'], v['uuid']) for v in  json.load(f)['rde_objects']]
        sel = [(k,v) for k, v in slug_uuids if slug_part in k]
        if len(sel) == 0:
            raise Exception(f'No layer with a slug looking like "{slug_part}" found in {layer_fp}')
        if len(sel) > 1:
            layer_slugs = [k for k,v in slug_uuids]
            raise Exception(f'{len(sel)} layers ({layer_slugs}) found with a slug looking like "{slug_part}", use a more precise slug_part.')
        return sel[0][1]

def today_date() -> str: return dt.strftime(dt.today(), COMPACT_DATE_FMT)

def to_wgs84_from_epsg3857(x, y):
    return gpd.GeoSeries({'geometry': Point(x, y)}).set_crs(3857).to_crs('EPSG:4326').geometry.values[0]

def now_ts() -> str: return dt.now().isoformat()


COMPACT_DATE_FMT = '%Y%m%d'
def datetime_obj_from_int_time(date_val: Union[str, int], match_to_end:bool = False) -> str:
    '''
    "match_to_end": when sets to true, the ISO 8601 datetime produced will be match to the last second of the day (i.e. 23h59:59)
    '''
    if type(date_val) is int:
        date_val = str(date_val)
    if len(date_val) == 7 or len(date_val) == 3:
            date_val = '0'+date_val
    if len(date_val) == 8:
        date = dt.strptime(date_val, COMPACT_DATE_FMT)
        return (date.replace(hour=23, minute=59, second=59) if match_to_end else date).isoformat()
    elif len(date_val) == 4:
        return datetime_obj_from_int_time(date_val+'1231', match_to_end) if match_to_end else datetime_obj_from_int_time(date_val+'0101')
    else:
        raise ValueError(f'Invalid date value: {date_val}')

def is_array_like(v) -> bool:
    return isinstance(v, (list, tuple, np.ndarray, pd.Series))

def convert_array_like_to_list(v):
    if isinstance(v, pd.Series):
        return v.tolist()
    elif isinstance(v, (list, tuple, np.ndarray)):
        return list(v)
    else:
        return v

def produce_hr_obj(uuid: str, 
               ds: str,
               obs_uid_list: list[list[str, str]],
               time_range: tuple[str, str],
               tpe: str,
               metadata: dict,
               rights_attribution: str = None,
               paradata: str = 'm') -> tuple[str, dict]:
    # replace all "NaN" values by None in metadata:
    new_md = {}
    for k, v in metadata.items():
        if str(v).lower() != "nan" and (is_array_like(v) or pd.notna(v)):
            if is_array_like(v):
                new_md[k] = convert_array_like_to_list(v)
            else:
                new_md[k] = v
        else:
            new_md[k] = None
    return {
        "uuid": uuid,
        "dataset": ds,
        "rde_type": RDE.HR.value,
        "paradata": paradata,
        "type": tpe,
        "documents": obs_uid_list,
        "start_time": time_range[0],
        "end_time": time_range[1],
        "rights_attribution": rights_attribution,
        "annotated_content": new_md
    }


# so the order is displayed in the type annotation and linting.
LAYER_UUID = str
GEOMETRY_UUID = str
def produce_obs_obj(uuid:str, 
                    time_range: tuple[str, str],
                    ds: str,
                    hr_uuid: str,
                    tpe: str,
                    coords,
                    geometries_links: list[GEOMETRY_UUID],
                    poi_link: str) -> dict:
    '''
    Produces an observation object for the RDE from the given parameters.
    uuid: the UUID of the observation
    ds: a tuple containing the UUID and the slug of the dataset the observation is part of
    hr_uuid: the UUID of the HR object the observation is documented in
    tpe: the type of the observation
    time_range: a tuple of two strings representing the start and end time of the observation
    geometries_links: a list of the UUID of the geometries associated to the current observation
    '''
    return {
        "uuid": uuid,
        "dataset": ds, 
        "rde_type": RDE.OBS.value,
        "type": tpe,
        "start_time": time_range[0], 
        "end_time": time_range[1],
        "coordinate": coords,
        "has_geometry": geometries_links,
        "documented_in": hr_uuid,
        "has_handle": poi_link
    }


def produce_poi_obj(uuid:str, coordinate, obs_uuid:list[str]) -> dict:
    '''
    returns the geometry object created as a dictionary
    uuid: the UUID of the PoI
    coordinate: the coordinate of the geometry
    obs_uuid: the UUID of the observation aggregated under this PoI
    '''
    return {
        "uuid": uuid,
        "rde_type": RDE.POI.value,
        "coordinate": coordinate,
        "represents": obs_uuid
    }


MultiLingualDesc = dict[str, list[str]]

def produce_dataset_obj(
    uuid: uuid.UUID,
    slug: str,
    version: str,
    name: MultiLingualDesc,
    description: MultiLingualDesc,
    paradata: MultiLingualDesc,
    sources: list[str],
    time_range: tuple[str, str],
    transribed_pages_amount: int,
    configuration: dict,
    areas_ids: list[str],
    publish_obj: tuple[str, str] = (None, None)
    ) -> dict:  
    return {  
        "uuid": uuid,
        "slug": slug,
        "version": version,
        "creation_time": now_ts(),
        "name": name,
        "rde_type": RDE.DATASET.value,
        "publish": {"doi": publish_obj[0], "url": publish_obj[1]},
        "description": description,
        "paradata": paradata,
        "sources": sources,
        "start_time": time_range[0],
        "end_time": time_range[1],
        "transcribed_pages_amount": transribed_pages_amount,
        "is_operationally_described_by": configuration,
        "falls_within": areas_ids  
    }


def produce_map_obj(
    uuid: str,
    map_slug: str,
    name: MultiLingualDesc,
    description: MultiLingualDesc,
    paradata: MultiLingualDesc,
    thumbnail: str,
    version: str,
    time_range: tuple[str, str],
    layer_id_list: list[str],
    areas_id: list[str],
    ) -> dict:  
    return {  
        "uuid": uuid,
        "slug": map_slug,
        "rde_type": RDE.MAP.value,
        "name": name,
        "description": description,
        "thumbnail": thumbnail,
        "paradata": paradata,
        "version": version,
        "start_time": time_range[0],
        "end_time": time_range[1],
        "contains": layer_id_list,
        "falls_within": areas_id
    }

def produce_layer_config(
    uuid: str,
    zoom_lvl: tuple[int, int],
    format: str,
    access_url: str,
) -> dict:
    lo_zoom, hi_zoom = zoom_lvl
    if hi_zoom < lo_zoom:
        raise Exception(f'In zoom_lvl tuple, the low zoom value should be lower than the high, provided was the tuple (order should be [low, high]): ', zoom_lvl)
    if lo_zoom < 0:
        raise Exception(f'Zoom levels should be positive numbers')
    if hi_zoom > 23:
        raise Exception(f'Zoom levels should not exceed 23')
    return {  
        "uuid": uuid,
        "zoom_lvl": zoom_lvl,
        "service": {
            "url": access_url,
            "media_type": format
        }
    }


def produce_layer_obj(
    uuid: str,
    layer_slug: str,
    name: MultiLingualDesc,
    description: MultiLingualDesc,
    time_range: tuple[str, str],
    map_uuid: str,
    is_vector: bool,
    layer_configs: list[dict]
    ) -> dict:
    return  {  
        "uuid": uuid,
        "name": name,
        "description": description,
        "slug": layer_slug,
        "map_uuid": map_uuid,
        "type": "vector" if is_vector else "raster",
        "rde_type": RDE.LAYER.value,
        "start_time": time_range[0],
        "end_time": time_range[1],
        "is_operationally_described_by": layer_configs
    }

def produce_area_obj(uuid: str,
    name: str,
    geometry: Polygon,
    slug: str,
    version: str) -> gpd.GeoDataFrame:
    gdf = gpd.GeoDataFrame([{
        "uuid": uuid,
        "rde_type": RDE.AREA.value,
        "name": name,
        "geometry": geometry,
        "slug": slug,
        "version": version
     }]).set_geometry('geometry').set_crs(UNIVERSAL_CRS)
    return [{**f['properties'], **{"geometry": f['geometry']}} for f in geodataframe_to_json(gdf)['features']]

def make_uuid_from_row_selection(uuid_ns: uuid.UUID, pandas_row:pd.Series, col_sel:list[str], ad_hoc_seed: str = '') -> str: 
    '''
    Generates a UUID from the values of the columns selected in the pandas row given as argument.
    uuid_ns: the namespace to use to generate the UUID
    pandas_row: the row from which to extract the values
    col_sel: the list of columns to use to generate the UUID
    ad_hoc_seed: an ad-hoc seed to add to the string to generate the UUID. By default is the empty string so that only the values from the row are used to generate the uuid.
    '''
    # weirdly from a performance POV, creating an ad-hoc string_buffer and then deleting it is more efficient than reusing the same one and flushing it.
    string_buffer = io.StringIO()
    # to note: removing the index and header boolean flag will keep the (likely) unique index as data
    pandas_row[col_sel].to_csv(string_buffer, index=False, header=False)
    row_val = string_buffer.getvalue()
    del string_buffer
    return str(uuid.uuid5(uuid_ns, row_val+ad_hoc_seed))

def QA_check_uuid_are_unique(df:pd.DataFrame) -> None:
    '''
    raises an Exception if the values in the column "uuid" of
    the dataframe given as argument are not unique. Doesn't do 
    anything otherwise.
    '''
    duplicates_entry = df[df.duplicated('uuid', keep=False) == True]
    n = len(duplicates_entry)
    if n != 0:
        non_unique_ids = duplicates_entry.uuid.unique()
        raise Exception(f'There was {n} non unique uuid generated: {non_unique_ids}')

def open_and_anonymize_geojson_file(fp: str) -> dict:
    '''
    In the "name" field of geojson files, there is often the name of the file itself,
    this function reads the file and removes the name field from the json object so 
    comparison can be done on data alone et not the file name.
    '''
    with open(fp, 'r') as f:
        data = json.loads(f.read())

    data['name'] = ''
    return data

def geodataframe_to_json(gdf: gpd.GeoDataFrame) -> dict:
    '''
    To make sure comparison between a disk version of the geodataframe and the one in memory is possible,
    this saves the memory one in a temporary file, then reads it back using the same reading 
    routine as the one used to read the disk version, then deletes the tmp file.
    '''
    tmp_fn = 'tmp.geojson'
    gdf.to_file(tmp_fn, encoding='utf-8')
    g = open_and_anonymize_geojson_file(tmp_fn)
    os.remove(tmp_fn)
    return g


DATA = Union[gpd.GeoDataFrame, list]
def save_data_file_if_different(fp:str,
                                filename:str, 
                                data:DATA,
                                name: str,
                                tpe: Union[str, list],
                                is_dataset_obj:bool = False) -> None:
    '''
    Saves the dataframe to the file path given as argument only if the file doesn't exist and
    the dataframe is different from the one in the file. If saved, the previous file is also deleted.
    (or overwritten if both were produced the same day)
    
    Parameters:
        fp: the directory where to save the file
        data: the data to save, either a GeoDataFrame, a DataFrame or a JSON Object (expressed as a dict)
        name: shorthand name given to the data
        tpe: the type of the data. Will appear in the file name. 
        is_dataset_obj: a boolean indicating whether the data is a dataset object or not. If it is, the function has to remove the "creation_time" field from the object before making the comparison
    '''
    def saving_routine(d:list[dict], f:str):
        obj = {
            "name": name,
            "type_in_file": tpe if type(tpe) is list else [tpe],
            "creation_time": now_ts(),
            "rde_objects": d
        }
        with open(f, 'w+', encoding='utf-8') as f:
            f.write(json.dumps(obj, indent=1, ensure_ascii=False))
    filename_with_ext = f'{filename}.json'
    filepath = os.path.join(fp, filename_with_ext)
    if isinstance(data, gpd.GeoDataFrame):
        if tpe == RDE.POI.value or tpe == RDE.OBS.value:
            data = processing_points(data, format_rde=True)
        t_data = geodataframe_to_json(data)
        t_data = t_data['features']
        # flattening the geojson object to only keep the features
        t_data = [{**f['properties'], **{"geometry": f['geometry']}} for f in t_data]
    elif isinstance(data, list):
        t_data = data
    else:
        raise ValueError(f'Data type not supported: {type(data)}')
    matching_files = list(map(str, Path(fp).glob("*"+filename_with_ext)))
    if len(matching_files) == 1:
        curr_file = list(matching_files)[0]
        with open(curr_file, 'r', encoding='utf-8') as f:
            curr_data = json.loads(f.read())['rde_objects']
        
        if is_dataset_obj:
            # removing the creation_time field from the object before making the comparison
            if len(curr_data) > 1:
                raise ValueError(f'Multiple objects found in dataset file: {curr_data}')
            curr_data[0].pop('creation_time')
            ts = t_data[0].pop('creation_time')
            if json.dumps(curr_data) == json.dumps(t_data):
                return
            else:
                t_data[0]['creation_time'] = ts
        # only removing the previous version of the file if it is differnt (the new version is saved at the end of the function)
        elif curr_data == t_data:
            # the dumps is a way to do a deep equality check of the object, as list comparison can sometimes returns false when both objects are actually equals.
            return
        else:
            os.remove(curr_file)
    
    elif len(matching_files) > 1:
        raise ValueError(f'Multiple files found with the same prefix: {matching_files}')
    #it no matching file, directly saving the new file.
    # saving the file if no other point of termination happened.
    saving_routine(t_data, filepath)

dictionary_template = {
    "uuid": "",
    "rde_type": RDE.DICT.value,
    "slug": "",
    "name": None,
    "entries": None
}

def save_dictionary(fp_prefix:str, uuid:str, slug: str, name:MultiLingualDesc, vals:dict) -> None:
    d = dictionary_template.copy()
    d['entries'] = vals
    d['slug'] = slug
    d['name'] = name
    d['uuid'] = uuid
    save_data_file_if_different(fp_prefix, slug, [d], slug, RDE.DICT.value)

def get_likely_type_of_series(s:pd.Series) -> str:
    tpe = str(s.dtype)
    if tpe == 'object':
        for v in s.values:
            if v:
                return type(v)
        return None
    return tpe

def python_type_to_ad_hoc_conf_type(tpe: type) -> str:
    if tpe == int or str(tpe).startswith('int'): 
        return "INTEGER"
    if tpe == str:
        return "STRING"
    if tpe == float or str(tpe).startswith('float'):
        return "FLOAT"
    if tpe == list:
        return "LIST"
    return str(tpe)
    #TODO: add CATEGORY; also the type of the list, URL and timedate entities. 

def quick_display_label(label:str) -> str:
    vs = label.replace('_', ' ').replace('-', '').split(' ')
    capitalized_vs = [v[0].upper() + v[1:] for v in vs]
    return ' '.join(capitalized_vs) 


def all_caps_val(v:str) -> bool:
    return reduce(lambda a, b: a and (not b.isalnum() or b.isupper()), v, True)

# generally having an all caps value mean it is a standardized value.
def is_all_caps(s: pd.Series) -> bool:
    for v in s.values:
        if v and type(v) is str:
            if not all_caps_val(v): 
                print(v)
                return False 
    return True

def is_empty_or_null(x):
    if isinstance(x, np.ndarray) or isinstance(x, pd.Series):
        return x.size == 0 or np.any(pd.isna(x))
    elif isinstance(x, list):
        return len(x) == 0 or any(pd.isna(x))
    elif isinstance(x, str):
        return x.strip() == ""
    else:
        return np.any(pd.isna(x))

def produce_configuration_file_from_metadata_df(
        uuid_ns: uuid.UUID,
        df: pd.DataFrame,
        indexable_array: list[str],
        short_display: list[str],
        hidden: list[str],
        dictionaries: dict[str, str],
        tagged_fields: dict[str, str],
        labels: dict[str,str],
        main_label: str = '',
        sub_label: str = '',
        display_thumbnail: bool = False,
        external_source: bool = False) -> dict:
    '''
    Returns a configuration file for the dataset based on the values from the dataframe and 
    various configuration object given as parameters.

    Parameters:
        uuid_ns: the namespace to use to generate the UUIDs
        df: the dataframe containing the metadata, the order of the columns directly impacts the display order in the configuration file
        indexable_array: an array of the columns that should be indexed
        short_display: an array of the columns that should be displayed in a short version of the data entry
        hidden: an array of the columns that should be hidden in the frontend
        dictionaries: a dictionary of the columns and the dictionaries they should be associated with
        tagged_fields: a dictionary of the columns and the tags they should be associated with
        labels: a dictionary of the columns and the labels they should have in the configuration file
        main_label: a formatting string indicating how for each data entry, its main label should be formatted on the frontend using the values of the dataset.
        sub_label: a formatting string indicating how for each data entry, its sub label should be formatted on the frontend using the values of the dataset.
    Returns:
        the configuration file as a dictionary
    '''
    base = {
        "hr_config": {
            "main_label": "",
            "sub_label": "",
            "display_thumbnail": False,
            "external_source": False,
            "metadata_field_config": []
        }
    }
    if main_label:
        base['hr_config']['main_label'] = main_label

    if sub_label:
        base['hr_config']['sub_label'] = sub_label
    
    if display_thumbnail:
        base['hr_config']['display_thumbnail'] = True

    if external_source:
        base['hr_config']['external_source'] = True

    base["uuid"] = str(uuid.uuid5(uuid_ns, 'dataset_configuration'))
    field_template = {
        "id": "",
        "type": None,
        "display_label": "",
        "nullable": True,
        "indexable": False,
        "short_display": False,
        "hidden": False,
        "tag": None,
        "display_order": -1
    }
    display_order = 0
    for col in df.columns:
        if not 'uid' in col:
            vals = df[col]
            curr_conf = field_template.copy()
            curr_conf['uuid'] = str(uuid.uuid5(uuid_ns, col))
            curr_conf["id"] = col
            nullable = is_empty_or_null(vals)
            curr_conf["nullable"] = bool(nullable)
            if col in indexable_array:
                curr_conf['indexable'] = True
            if col in hidden:
                curr_conf['hidden'] = True
            if col in short_display:
                curr_conf['short_display'] = True
            if col in tagged_fields:
                curr_conf['tag'] = tagged_fields[col]
            curr_conf["type"] = python_type_to_ad_hoc_conf_type(get_likely_type_of_series(vals))
            if col in dictionaries:
                curr_conf['dictionary'] = dictionaries[col] 
                curr_conf["type"] = "LIST[CATEGORY]" if curr_conf["type"].startswith("LIST") else "CATEGORY"
            curr_conf["display_order"] = (display_order := display_order + 1)
            curr_conf["display_label"] = labels[col] if col in labels else quick_display_label(col)
            base["hr_config"]["metadata_field_config"].append(curr_conf)
    return base


def QA_check_unique_uuid_in_uuid_array(df: pd.DataFrame, uuid_array_col_name:str, raise_exception:bool = True) -> bool:
    '''
    Checks that all the UUIDs listed in df[uuid_array_colname] are unique, throw an exception otherwise.
    '''
    def are_unique_values_in_this_array(irow: tuple[typing.Hashable, pd.Series]) -> bool:
        s = irow[1]
        uuid_row = s[uuid_array_col_name]
        if not uuid_row:
            # we could very well have no values, in such case the QA check was succesful
            return True
        bool_val = len(uuid_row) == len(set(uuid_row))
        if not bool_val and raise_exception:
            dups = {item for item, count in Counter(uuid_row).items() if count > 1}
            raise Exception(f'For object {s.uuid}, there was duplicated entries in relation "{uuid_array_col_name}":{dups}')
        # je sais j'aurais just pu retourner "True" vu que si False ya l'exception, mais chais pas ça faisait bizarre.
        return bool_val
    
    if type(df[uuid_array_col_name].iloc[0][0]) == list:
        df = df.copy()
        df[uuid_array_col_name] = df[uuid_array_col_name].apply(lambda x: [i[1] for i in x])
    return reduce(lambda a,b: a and are_unique_values_in_this_array(b), df.iterrows(), True)

def QA_check_all_geometries_are_valid(gdf: gpd.GeoDataFrame, raise_exception:bool = True) -> bool:
    '''
    Checks that all geometries from the geodataframe (column "geometry") are valid according to shapely ruleset.
    Raise an exception when unvalid geometries are found if `raise_exception` is set to True, otherwise
    returns a boolean indicating whether all geometries are valid.
    '''
    unvalid_geoms = [k for k,v in gdf.set_index('uuid').geometry.is_valid.to_dict().items() if not v]
    if unvalid_geoms and raise_exception:
        explanations = {k: explain_validity(g) for k, g in gdf[~gdf.geometry.is_valid].set_index('uuid').geometry.to_dict().items()}
        raise Exception(f'There were {len(unvalid_geoms)} unvalid geometries detected of following uuids and reasons: {explanations}')
    return len(unvalid_geoms) == 0
