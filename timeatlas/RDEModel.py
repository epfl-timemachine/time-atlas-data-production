from dataclasses import dataclass, field
from shapely.geometry import Point, LineString, Polygon, MultiLineString, MultiPolygon
import shapely
import json
from typing import Optional, Self
from datetime import datetime
import pandas as pd
from TAEnums import *

type GeometryType = Point | LineString | Polygon | MultiLineString | MultiPolygon
type UUID = str
type ObsReference = Observation | UUID
type HRReference = HistoricalRecord | UUID
type DatasetReference = Dataset | UUID
type POIReference = PointOfInterest | UUID
type GeometryReference = Geometry | UUID
type AreaReference = Area | UUID
type LayerReference = Layer | UUID
type MapReference = Map | UUID

@dataclass
class UUIDEntity:
    id: UUID

    def get_ref(self) -> str:
        return self.id

    @classmethod
    def parse_uuid(cls, data_id: str) -> None:
        # in the API, the unique id is often represented as a URL, but in the data model we want to keep only the UUID part, so we parse it here.
        if data_id.startswith('http'):
            return data_id.split('/')[-1]
        return data_id

@dataclass
class RDE:
    def to_dict(self) -> dict:
        result = {}
        for field_name, field_value in self.__dict__.items():
            match field_value:
                case UUIDEntity():
                    result[field_name] = field_value.get_ref()
                case RDE():
                    # works for dataset configuration as well, as it inherits from RDE, but does not have rde_type field, so it will not be added in the final dict
                    result[field_name] = field_value.to_dict()
                case RDETimeRange():
                    result['start_time'] = field_value.start_time
                    result['end_time'] = field_value.end_time
                case HeightInfo():
                    result['terrain_height'] = field_value.terrain
                    result['building_height'] = field_value.building
                case list():
                    result[field_name] = [item.get_ref() if isinstance(item, RDE) else item for item in field_value]
                case Enum():
                    result[field_name] = field_value.value
                case MultiLingualValue():
                    result[field_name] = field_value.values
                case _:
                    result[field_name] = field_value

        # dataset configuration and other special cases have no rde_type field, only doing it for main RDE types
        rde_name = self.__class__.__name__.lower()
        if rde_name in CLASS_NAME_TO_RDE:
            result['rde_type'] = CLASS_NAME_TO_RDE[rde_name].value
        return result
    
    def get_type(self) -> Optional[RDEType]:
        rde_name = self.__class__.__name__.lower()
        return CLASS_NAME_TO_RDE.get(rde_name).value
    
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
class MetadataFieldConfig(RDE):
    id: str
    type: MetadataType
    display_label: MultiLingualValue
    nullable: bool
    indexable: bool
    short_display: bool
    hidden: bool
    tag: Optional[MetadataTag]
    paradata: Optional[ParadataValues]

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            id=json_obj['id'],
            type=METADATA_TYPE_TO_ENUM.get(json_obj['type'], MetadataType.STRING),
            display_label=MultiLingualValue(values=json_obj.get('display_label', {})),
            nullable=json_obj.get('nullable', True),
            indexable=json_obj.get('indexable', False),
            short_display=json_obj.get('short_display', False),
            hidden=json_obj.get('hidden', False),
            tag=METADATA_TAG_TO_ENUM.get(json_obj['tag'], None),
            paradata=PARADATA_VALUE_TO_ENUM.get(json_obj['paradata'], None)
        )

@dataclass
class DatasetConfiguration(RDE):
    metadata_field_config: list[MetadataFieldConfig] = field(default_factory=list)
    main_label: str = ''
    sub_label: str = ''
    display_thumbnail: bool = False
    external_source: bool = False

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            metadata_field_config=[MetadataFieldConfig.constructor_from_json_obj(v) for v in json_obj.get('metadata_field_config', [])],
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
    configuration: DatasetConfiguration
    version: Optional[str] = None
    sources: list[str] = field(default_factory=list)
    has_areas: Optional[list[AreaReference]] = field(default_factory=list)
    # fields that do not exist in the RDE data model, only there to make python processing easier:
    hrs: list['HistoricalRecord'] = field(default_factory=list)
    obs: list['Observation'] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        config_data = json_obj.get('configuration')
        configuration = DatasetConfiguration.constructor_from_json_obj(config_data) if config_data else None
        return cls(
            uuid=UUIDEntity.parse_uuid(json_obj['uuid']),
            slug=json_obj['slug'],
            name=MultiLingualValue(values=json_obj['name']),
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            configuration=configuration,
            version=json_obj.get('version', None),
            sources=json_obj.get('sources', []),
            has_areas=json_obj.get('has_areas', [])
        )
    
    def instantiate_all_rde_members(self, rde_list: list[RDE]) -> None:
        for rde in rde_list:
            if hasattr(rde, "dataset") and RDEType.dataset == self.uuid:
                match rde:
                    case HistoricalRecord(): self.hrs.append(rde)
                    case Observation(): self.obs.append(rde)

@dataclass
class HistoricalRecord(RDE, UUIDEntity):
    dataset: DatasetReference
    time_range: RDETimeRange
    paradata: ParadataValues
    type: str
    has_observations: list[ObsReference]
    metadata: dict = field(default_factory=dict)
    rights_attribution: Optional[str] = None

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            uuid=UUIDEntity.parse_uuid(json_obj['uuid']),
            dataset=UUIDEntity.parse_uuid(json_obj['dataset']['uuid']),
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            paradata=json_obj.get('paradata', ''),
            type=json_obj.get('type', ''),
            has_observations=json_obj.get('has_observations', []),
            metadata=json_obj.get('metadata', {}),
            rights_attribution=json_obj.get('rights_attribution')
        )
    
    def actualize_observations_references(self, entity_list: dict[UUID, RDE]) -> None:
        self.has_observations = [entity_list[obs_ref] if isinstance(obs_ref, str) and obs_ref in entity_list else obs_ref for obs_ref in self.has_observations]

    def to_dict(self, flatten_metadata:bool = True) -> dict:
        result = super().to_dict()
        # HR specific serialization for documents
        result['has_observations'] = [obs.get_ref() if isinstance(obs, RDE) else obs for obs in self.has_observations]
        if flatten_metadata:
            for k,v in self.metadata.items():
                result[k] = v
            result.pop('metadata', None)
        return result

    @classmethod
    def constructor_from_dataframe_row(cls, row:pd.Series) -> Self:
        metadata_keys = set(row.index).difference({'uuid', 'dataset', 'start_time', 'end_time', 'paradata', 'type', 'has_observations', 'rights_attribution'})
        metadata = {k: row[k] for k in metadata_keys}
        return cls(
            uuid=UUIDEntity.parse_uuid(row['uuid']),
            dataset=UUIDEntity.parse_uuid(row['dataset']),
            time_range=RDETimeRange(row['start_time'], row['end_time']),
            paradata=row.get('paradata', ''),
            type=row.get('type', ''),
            has_observations=row.get('has_observations', []),
            metadata=metadata,
            rights_attribution=row.get('rights_attribution')
        )

@dataclass
class HeightInfo:
    terrain: Optional[float] = None
    building: Optional[float] = None

@dataclass
class PointOfInterest(RDE, UUIDEntity):
    geometry: Point
    height: HeightInfo

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        geom = json_obj.get('geometry')
        json_obj = json_obj.get('properties', json_obj)  # in case the JSON object is a GeoJSON Feature object
        return cls(
            uuid=UUIDEntity.parse_uuid(json_obj['uuid']),
            geometry=shapely.from_geojson(json.dumps(geom)) if geom else None,
            height=HeightInfo(
                terrain=json_obj.get('terrain_height'),
                building=json_obj.get('building_height')
            )
        )

@dataclass
class Observation(RDE, UUIDEntity):
    type: str
    historical_record: HRReference
    has_geometries: GeometryType
    geometry: Point
    # height: HeightInfo
    has_geometries: list[GeometryReference] = field(default_factory=list)
    part_of_point_of_interest: Optional[POIReference] = None

    def actualize_references(self, entity_list: dict[UUID, RDE]) -> None:
        self.has_geometries = [entity_list[geom_ref] if isinstance(geom_ref, str) and geom_ref in entity_list else geom_ref for geom_ref in self.has_geometries]
        self.part_of_point_of_interest = entity_list[self.part_of_point_of_interest] if isinstance(self.part_of_point_of_interest, str) and self.part_of_point_of_interest in entity_list else self.part_of_point_of_interest
        self.historical_record = entity_list[self.historical_record] if isinstance(self.historical_record, str) and self.historical_record in entity_list else self.historical_record

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        geom = json_obj.get('geometry')
        json_obj = json_obj.get('properties', json_obj)  # in case the JSON object is a GeoJSON Feature object
        return cls(
            uuid=UUIDEntity.parse_uuid(json_obj['uuid']),
            type=json_obj.get('type', ''),
            historical_record=json_obj.get('documented_in')[0] if isinstance(json_obj.get('documented_in'), list) and len(json_obj.get('documented_in')) > 0 else None,
            geometry=shapely.from_geojson(json.dumps(geom)) if geom else None,
            # height=HeightInfo(
            #     terrain=json_obj.get('height', {}).get('terrain'),
            #     building=json_obj.get('height', {}).get('building')
            # ),
            has_geometries=json_obj.get('has_geometries', []),
            part_of_point_of_interest=json_obj.get('part_of_point_of_interest', None)
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
    slug: str
    time_range: RDETimeRange
    layers: list[LayerReference] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    thumbnail: Optional[str] = None
    version: Optional[str] = None
    areas: list[AreaReference] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            uuid=UUIDEntity.parse_uuid(json_obj['id']),
            name=MultiLingualValue(values=json_obj['name']),
            layers=json_obj.get('layers', []),
            metadata=json_obj.get('metadata', {}),
            thumbnail=json_obj.get('thumbnail'),
            extent=GeographicalExtent(json_obj.get('extent', [])),
            version=json_obj.get('version'),
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            areas=json_obj.get('areas', [])
        )

@dataclass
class LayerConfigurationService:
    url: str
    type: str

@dataclass 
class LayerConfiguration(RDE, UUIDEntity):
    service: LayerConfigurationService
    min_zoom_level: int
    max_zoom_level: int
    extent: Optional[GeographicalExtent] = None

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        service_data = json_obj.get('service', {})
        service = LayerConfigurationService(
            url=service_data.get('url', ''),
            type=service_data.get('type', '')
        )
        return cls(
            uuid=UUIDEntity.parse_uuid(json_obj['uuid']),
            service=service,
            min_zoom_level=json_obj.get('min_zoom_level', 0),
            max_zoom_level=json_obj.get('max_zoom_level', 22),
            extent=GeographicalExtent(json_obj.get('extent', [])) if 'extent' in json_obj else None
        )

@dataclass 
class Layer(RDE, UUIDEntity):
    slug: str
    name: MultiLingualValue
    description: MultiLingualValue
    time_range: RDETimeRange
    map: MapReference
    type: LayerType
    layer_configurations: list[LayerConfiguration] = field(default_factory=list)

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            uuid=UUIDEntity.parse_uuid(json_obj['uuid']),
            slug=json_obj['slug'],
            name=MultiLingualValue(values=json_obj['name']),
            description=MultiLingualValue(values=json_obj.get('description', {})),
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            map=UUIDEntity.parse_uuid(json_obj['map']['uuid']) if 'map' in json_obj and isinstance(json_obj['map'], dict) else None,
            type=LAYER_TYPE_TO_ENUM.get(json_obj.get('type', '').upper(), LayerType.RASTER),
            layer_configurations=[LayerConfiguration.constructor_from_json_obj(lc) for lc in json_obj.get('layer_configurations', [])]
        )

@dataclass
class Geometry(RDE, UUIDEntity):
    geometry: GeometryType
    layer: Optional[LayerReference] = None

    def __post_init__(self):
        if not self.geometry.is_valid:
            raise ValueError(f'Invalid geometry, because  {shapely.validation.explain_validity(self.geometry)}')

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        # to note, the JSON object is a GeoJSON Feature object
        props = json_obj.get('properties', {})
        geometry = json_obj.get('geometry', {})
        return cls(
            uuid=UUIDEntity.parse_uuid(props.get('uuid', json_obj.get('uuid'))),
            layer=UUIDEntity.parse_uuid(props.get('layer_uuid')) if 'layer_uuid' in props else None,
            geometry=shapely.from_geojson(json.dumps(geometry)),
        )
    
    @classmethod
    def constructor_from_raw_geojson_line(cls, geojson_line: str, uuid: str, layer_uuid: str) -> Self:
        json_obj = json.loads(geojson_line)
        return cls(
            uuid=UUIDEntity.parse_uuid(uuid),
            layer=UUIDEntity.parse_uuid(layer_uuid),
            geometry=shapely.from_geojson(json.dumps(json_obj.get('geometry', {}))),
        )
    
    def to_dict(self) -> dict:
        result = super().to_dict()
        result['geometry'] = json.loads(shapely.to_geojson(self.geometry))
        return result

@dataclass
class Area(RDE, UUIDEntity):
    slug: str
    name: MultiLingualValue
    geometry: GeometryType

    @classmethod
    def constructor_from_json_obj(cls, json_obj: dict) -> Self:
        return cls(
            uuid=UUIDEntity.parse_uuid(json_obj['uuid']),
            name=MultiLingualValue(values=json_obj['name']),
            geometry=shapely.from_geojson(json.dumps(json_obj.get('geometry', {})))
        )

