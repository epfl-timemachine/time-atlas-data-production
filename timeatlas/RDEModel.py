from dataclasses import dataclass, field
from enum import Enum
from shapely.geometry import Point, LineString, Polygon, MultiLineString, MultiPolygon
import shapely
import json
from typing import Optional, Self
from datetime import datetime
import pandas as pd

type GeometryType = Point | LineString | Polygon | MultiLineString | MultiPolygon
type UUID = str
type ObsReference = Obs | UUID
type HRReference = HR | UUID
type DatasetReference = Dataset | UUID
type POIReference = POI | UUID
type GeometryReference = Geometry | UUID
type AreaReference = Area | UUID
type LayerReference = Layer | UUID
type MapReference = Map | UUID

class RDEType(Enum):
    HR = 'historical_record'
    OBS = 'obs'
    POI = 'poi'
    GEOM = 'geometry'
    DATASET = 'dataset'
    MAP = 'map'
    LAYER = 'layer'
    AREA = 'area'

CLASS_NAME_TO_RDE = {
    'hr': RDEType.HR,
    'historical_record': RDEType.HR,
    'obs': RDEType.OBS,
    'poi': RDEType.POI,
    'geometry': RDEType.GEOM,
    'dataset': RDEType.DATASET,
    'map': RDEType.MAP,
    'layer': RDEType.LAYER,
    'area': RDEType.AREA
}
@dataclass
class UUIDEntity:
    uuid: UUID

    def get_ref(self) -> str:
        return self.uuid

@dataclass
class RDE:

    def to_dict(self) -> dict:
        result = {}
        for field_name, field_value in self.__dict__.items():
            match field_value:
                case RDETimeRange():
                    result['start_time'] = field_value.start_time
                    result['end_time'] = field_value.end_time
                case RDE():
                    result[field_name] = field_value.get_ref()
                case list():
                    result[field_name] = [item.get_ref() if isinstance(item, RDE) else item for item in field_value]
                case _:
                    result[field_name] = field_value

        # dataset configuration and other special cases have no rde_type field, only doing it for main RDE types
        rde_name = self.__class__.__name__.lower()
        if rde_name in CLASS_NAME_TO_RDE:
            result['rde_type'] = CLASS_NAME_TO_RDE[rde_name].value
        return result
    
    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        raise NotImplementedError('This method should be implemented in subclasses')

@dataclass
class RDETimeRange:
    start_time: str
    end_time: str

    def __post_init__(self):
        # Validate time format
        datetime.fromisoformat(self.start_time.replace("Z", "+00:00"))
        datetime.fromisoformat(self.end_time.replace("Z", "+00:00"))
        assert self.start_time <= self.end_time, "start_time must be less than or equal to end_time"

@dataclass
class MultiLingualValue:
    values: dict[str, list[str]]

@dataclass
class DSConfiguration(RDE):
    metadata_field_config: list[dict] = field(default_factory=list)
    main_label: str = ''
    sub_label: str = ''
    display_thumbnail: bool = False
    external_source: bool = False

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            metadata_field_config=json_obj.get('metadata_field_config', []),
            main_label=json_obj.get('dataset_config', {}).get('main_label', ''),
            sub_label=json_obj.get('dataset_config', {}).get('sub_label', ''),
            display_thumbnail=json_obj.get('dataset_config', {}).get('display_thumbnail', False),
            external_source=json_obj.get('dataset_config', {}).get('external_source', False)
        )

@dataclass
class Dataset(RDE, UUIDEntity):
    slug: str
    name: MultiLingualValue
    time_range: RDETimeRange
    configuration: DSConfiguration
    sources: list[str] = field(default_factory=list)
    falls_within: Optional[list[UUID]] = field(default_factory=list)

    # fields that do not exist in the RDE data model, only there to make python processing easier:
    hrs: list['HR'] = field(default_factory=list)
    obs: list['Obs'] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        config_data = json_obj.get('configuration')
        configuration = DSConfiguration.constructor_from_json_obj(config_data) if config_data else None
        return cls(
            uuid=json_obj['uuid'],
            slug=json_obj['slug'],
            name=MultiLingualValue(values=json_obj['name']),
            time_range=RDETimeRange(json_obj['start_date'], json_obj['end_date']),
            configuration=configuration,
            sources=json_obj.get('sources', []),
            falls_within=json_obj.get('falls_within', [])
        )
    
    def instantiate_all_rde_members(self, rde_list: list[RDE]) -> None:
        for rde in rde_list:
            if hasattr(rde, "dataset") and RDEType.dataset == self.uuid:
                match rde:
                    case HR(): self.hrs.append(rde)
                    case Obs(): self.obs.append(rde)

@dataclass
class HR(RDE, UUIDEntity):
    dataset: DatasetReference
    time_range: RDETimeRange
    paradata: str
    type: str
    documents: list[ObsReference]
    metadata: dict = field(default_factory=dict)
    rights_attribution: Optional[str] = None

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            uuid=json_obj['uuid'],
            dataset=json_obj['dataset']['uuid'],
            time_range=RDETimeRange(json_obj['start_date'], json_obj['end_date']),
            paradata=json_obj.get('paradata', ''),
            type=json_obj.get('type', ''),
            documents=json_obj.get('documents', []),
            metadata=json_obj.get('metadata', {}),
            rights_attribution=json_obj.get('rights_attribution')
        )
    
    def actualize_observations_references(self, entity_list: dict[UUID, RDE]) -> None:
        self.documents = [entity_list[obs_ref] if isinstance(obs_ref, str) and obs_ref in entity_list else obs_ref for obs_ref in self.documents]

    def to_dict(self, flatten_metadata:bool = True) -> dict:
        result = super().to_dict()
        # HR specific serialization for documents
        result['documents'] = [doc.get_ref() if isinstance(doc, RDE) else doc for doc in self.documents]
        if flatten_metadata:
            for k,v in self.metadata.items():
                result[k] = v
            result.pop('metadata', None)
        return result

    @classmethod
    def constructor_from_dataframe_row(cls, row:pd.Series) -> Self:
        metadata_keys = set(row.index).difference({'uuid', 'dataset', 'start_time', 'end_time', 'paradata', 'type', 'documents', 'rights_attribution'})
        metadata = {k: row[k] for k in metadata_keys}
        return cls(
            uuid=row['uuid'],
            dataset=row['dataset'],
            time_range=RDETimeRange(row['start_time'], row['end_time']),
            paradata=row.get('paradata', ''),
            type=row.get('type', ''),
            documents=row.get('documents', []),
            metadata=metadata,
            rights_attribution=row.get('rights_attribution')
        )

@dataclass
class HeightInfo:
    terrain: Optional[float] = None
    building: Optional[float] = None

@dataclass
class POI(RDE, UUIDEntity):
    geometry: Point
    height: HeightInfo
    contains: list[ObsReference] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        geom = json_obj.get('geometry')
        json_obj = json_obj.get('properties', json_obj)  # in case the JSON object is a GeoJSON Feature object
        return cls(
            uuid=json_obj['uuid'],
            geometry=shapely.from_geojson(json.dumps(geom)) if geom else None,
            height=HeightInfo(
                terrain=json_obj.get('terrain_height'),
                building=json_obj.get('building_height')
            ),
            contains=json_obj.get('contains', [])
        )

@dataclass
class Obs(RDE, UUIDEntity):
    dataset: DatasetReference
    time_range: RDETimeRange
    type: str
    documented_in: HRReference
    geometry: GeometryType
    height: HeightInfo
    has_geometry: list[GeometryReference] = field(default_factory=list)
    has_handle: Optional[POIReference] = None


    def actualize_references(self, entity_list: dict[UUID, RDE]) -> None:
        self.has_geometry = [entity_list[geom_ref] if isinstance(geom_ref, str) and geom_ref in entity_list else geom_ref for geom_ref in self.has_geometry]
        self.has_handle = entity_list[self.has_handle] if isinstance(self.has_handle, str) and self.has_handle in entity_list else self.has_handle

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        geom = json_obj.get('geometry')
        json_obj = json_obj.get('properties', json_obj)  # in case the JSON object is a GeoJSON Feature object
        return cls(
            uuid=json_obj['uuid'],
            dataset=json_obj['dataset']['uuid'],
            time_range=RDETimeRange(json_obj['start_date'], json_obj['end_date']),
            type=json_obj.get('type', ''),
            documented_in=json_obj.get('documented_in')[0] if isinstance(json_obj.get('documented_in'), list) and len(json_obj.get('documented_in')) > 0 else None,
            geometry=shapely.from_geojson(json.dumps(geom)) if geom else None,
            height=HeightInfo(
                terrain=json_obj.get('height', {}).get('terrain'),
                building=json_obj.get('height', {}).get('building')
            ),
            has_geometry=json_obj.get('has_geometry', []),
            has_handle=json_obj.get('part_of')[0] if isinstance(json_obj.get('part_of'), list) and len(json_obj.get('part_of')) > 0 else None
        )
    
@dataclass
class GeographicalExtent:
    coordinates: list[float]

    def __post_init__(self):
        assert len(self.coordinates) == 4, "Extent must have four coordinates: [min_x, min_y, max_x, max_y]"
        assert self.coordinates[0] < self.coordinates[2], "min_x must be less than max_x"
        assert self.coordinates[1] < self.coordinates[3], "min_y must be less than max_y"
        # note that the two asserts above would faile on map that are exactly on limits of the negative 
        # latitude (-0.0) or longitude (-0.0), it is unlikey we ingest map from such zones (and most GIS 
        # software specially avoid it: https://en.wikipedia.org/wiki/180th_meridian)

@dataclass
class Map(RDE, UUIDEntity):
    name: MultiLingualValue
    time_range: RDETimeRange
    contains: list[LayerReference] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    thumbnail: Optional[str] = None
    version: Optional[str] = None
    falls_within: list[AreaReference] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            uuid=json_obj['uuid'],
            name=MultiLingualValue(values=json_obj['name']),
            contains=json_obj.get('contains', []),
            metadata=json_obj.get('metadata', {}),
            thumbnail=json_obj.get('thumbnail'),
            extent=GeographicalExtent(json_obj.get('extent', [])),
            version=json_obj.get('version'),
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            falls_within=json_obj.get('falls_within', [])
        )

@dataclass 
class Layer(RDE, UUIDEntity):
    slug: str
    name: MultiLingualValue
    description: MultiLingualValue
    time_range: RDETimeRange
    map_uuid: Map
    is_vector: bool
    layer_configs: list[dict] = field(default_factory=list)

@dataclass
class Geometry(RDE, UUIDEntity):
    geometry: GeometryType
    layer: Optional[LayerReference] = None

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        # to note, the JSON object is a GeoJSON Feature object
        props = json_obj.get('properties', {})
        geometry = json_obj.get('geometry', {})
        return cls(
            uuid=props.get('uuid', json_obj.get('uuid')),
            layer=props.get('layer_uuid'),
            geometry=shapely.from_geojson(json.dumps(geometry)),
        )

@dataclass
class Area(RDE, UUIDEntity):
    name: MultiLingualValue
    geometry: GeometryType

