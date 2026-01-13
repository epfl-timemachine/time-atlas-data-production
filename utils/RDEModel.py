
from dataclasses import dataclass, field
from shapely.geometry import Point, LineString, Polygon, MultiLineString, MultiPolygon
from typing import Union, Optional

type GeometryType = Union[Point, LineString, Polygon, MultiLineString, MultiPolygon]
type UUID = str

@dataclass
class RDE:
    uuid: UUID

@dataclass
class RDETimeRange:
    start_time: str
    end_time: str

@dataclass
class MultiLingualValue:
    values: dict[str, str]

@dataclass
class DSConfiguration(RDE):
    metadata: dict = field(default_factory=dict)

@dataclass
class Dataset(RDE):
    slug: str
    name: MultiLingualValue
    time_range: RDETimeRange
    configuration: DSConfiguration
    sources: list[str] = field(default_factory=list)
    falls_within: Optional[list[UUID]] = field(default_factory=list)

@dataclass
class HR(RDE):
    dataset: UUID
    time_range: RDETimeRange
    paradata: str
    obs_list: list['Obs']
    metadata: dict = field(default_factory=dict)
    rights_attribution: Optional[str] = None

@dataclass
class POI(RDE):
    coordinate: list[float]
    height: float

@dataclass
class Obs(RDE):
    dataset: UUID
    time_range: RDETimeRange
    hr_uuid: HR
    geometries: list[UUID] = field(default_factory=list)
    has_handle: POI = None

@dataclass
class Geometry(RDE):
    geometry: GeometryType
    layer: Optional[UUID] = None

@dataclass
class Area(RDE):
    name: MultiLingualValue
    geometry: GeometryType