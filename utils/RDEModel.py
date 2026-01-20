from dataclasses import dataclass, field
from shapely.geometry import Point, LineString, Polygon, MultiLineString, MultiPolygon
from typing import Union, Optional
from datetime import datetime
from rde import CLASS_NAME_TO_RDE

type GeometryType = Union[Point, LineString, Polygon, MultiLineString, MultiPolygon]
type UUID = str
type ObsReference = Obs | UUID
type HRReference = HR | UUID
type DatasetReference = Dataset | UUID
type POIReference = POI | UUID
type GeometryReference = Geometry | UUID
type AreaReference = Area | UUID

@dataclass
class RDE:
    uuid: UUID

    def to_dict(self) -> dict:
        result = {}
        for field_name, field_value in self.__dict__.items():
            if isinstance(field_value, RDETimeRange):
                result['start_time'] = field_value.start_time
                result['end_time'] = field_value.end_time
            elif isinstance(field_value, RDE):
                result[field_name] = field_value.get_ref()
            elif isinstance(field_value, list):
                result[field_name] = [item.get_ref() if isinstance(item, RDE) else item for item in field_value]
            else:
                result[field_name] = field_value

        # dataset configuration and other special cases have no rde_type field, only doing it for main RDE types
        rde_name = self.__class__.__name__.lower()
        if rde_name in CLASS_NAME_TO_RDE:
            result['rde_type'] = CLASS_NAME_TO_RDE[rde_name].value
        return result
    
    def get_ref(self) -> str:
        return self.uuid

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
    hr_config: list[dict] = field(default_factory=list)

    def constructor_from_json_obj(json_obj: dict) -> 'Dataset':
        return DSConfiguration(
            uuid=json_obj['uuid'],
            metadata_field_config=json_obj['dataset_config'].get('metadata_field_config', []),
            hr_config=json_obj.get('hr_config', [])
        )

@dataclass
class Dataset(RDE):
    slug: str
    name: MultiLingualValue
    time_range: RDETimeRange
    configuration: DSConfiguration
    sources: list[str] = field(default_factory=list)
    falls_within: Optional[list[UUID]] = field(default_factory=list)

    @staticmethod
    def constructor_from_json_obj(json_obj: dict) -> 'Dataset':
        config_data = json_obj.get('configuration')
        configuration = DSConfiguration.constructor_from_json_obj(config_data) if config_data else None
        return Dataset(
            uuid=json_obj['uuid'],
            slug=json_obj['slug'],
            name=MultiLingualValue(values=json_obj['name']),
            time_range=RDETimeRange(json_obj['start_date'], json_obj['end_date']),
            configuration=configuration,
            sources=json_obj.get('sources', []),
            falls_within=json_obj.get('falls_within', [])
        )

@dataclass
class HR(RDE):
    dataset: DatasetReference
    time_range: RDETimeRange
    paradata: str
    type: str
    documents: list[ObsReference]
    annotated_content: dict = field(default_factory=dict)
    rights_attribution: Optional[str] = None

    @staticmethod
    def constructor_from_json_obj(json_obj: dict) -> 'HR':
        return HR(
            uuid=json_obj['uuid'],
            dataset=json_obj['dataset']['uuid'],
            time_range=RDETimeRange(json_obj['start_date'], json_obj['end_date']),
            paradata=json_obj.get('paradata', ''),
            type=json_obj.get('type', ''),
            documents=json_obj.get('documents', []),
            annotated_content=json_obj.get('annotated_content', {}),
            rights_attribution=json_obj.get('rights_attribution')
        )
    
@dataclass
class HeightInfo:
    terrain: Optional[float] = None
    building: Optional[float] = None

@dataclass
class POI(RDE):
    coordinate: list[float]
    height: HeightInfo



@dataclass
class Obs(RDE):
    dataset: DatasetReference
    time_range: RDETimeRange
    hr_uuid: HRReference
    type: str
    documented_in: HRReference
    geometry: GeometryType
    height: HeightInfo
    has_geometry: list[GeometryReference] = field(default_factory=list)
    has_handle: Optional[POIReference] = None

    @staticmethod
    def constructor_from_json_obj(json_obj: dict) -> 'Obs':
        return Obs(
            uuid=json_obj['uuid'],
            dataset=json_obj['dataset']['uuid'],
            time_range=RDETimeRange(json_obj['start_time'], json_obj['end_time']),
            hr_uuid=json_obj.get('hr_uuid'),
            type=json_obj.get('type', ''),
            documented_in=json_obj.get('documented_in'),
            geometry=json_obj.get('geometry'),
            height=HeightInfo(
                terrain=json_obj.get('height', {}).get('terrain'),
                building=json_obj.get('height', {}).get('building')
            ),
            has_geometry=json_obj.get('has_geometry', []),
            has_handle=json_obj.get('has_handle')
        )

@dataclass
class Geometry(RDE):
    geometry: GeometryType
    layer: Optional[UUID] = None

@dataclass
class Area(RDE):
    name: MultiLingualValue
    geometry: GeometryType

