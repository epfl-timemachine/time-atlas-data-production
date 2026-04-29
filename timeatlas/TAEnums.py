from enum import Enum

class LayerType(Enum):
    RASTER = 'raster'
    VECTOR = 'vector'

LAYER_TYPE_TO_ENUM = {
    "RASTER": LayerType.RASTER,
    "VECTOR": LayerType.VECTOR,
}

class MetadataTag(Enum):
    PEOPLE = "PEOPLE"
    PLACE = "PLACE"
    LAND_USE = "LAND_USE"

METADATA_TAG_TO_ENUM = {
    "PEOPLE": MetadataTag.PEOPLE,
    "PLACE": MetadataTag.PLACE,
    "LAND_USE": MetadataTag.LAND_USE
}

class MetadataType(Enum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    LIST = "LIST"

METADATA_TYPE_TO_ENUM = {
    "STRING": MetadataType.STRING,
    "INTEGER": MetadataType.INTEGER,
    "FLOAT": MetadataType.FLOAT,
    "LIST": MetadataType.LIST
}

class ParadataValues(Enum):
    MANUAL = 'm'
    AUTOMATIC = 'a'
    SEMIAUTOMATIC = 'sa'
    AI = 'ai'

PARADATA_VALUE_TO_ENUM = {
    "m": ParadataValues.MANUAL,
    "a": ParadataValues.AUTOMATIC,
    "sa": ParadataValues.SEMIAUTOMATIC,
    "ai": ParadataValues.AI,
    "MANUAL": ParadataValues.MANUAL,
    "AUTOMATIC": ParadataValues.AUTOMATIC,
    "SEMIAUTOMATIC": ParadataValues.SEMIAUTOMATIC,
    "AI": ParadataValues.AI
}

class RDEType(Enum):
    HR = 'historical_record'
    OBS = 'observation'
    POI = 'point_of_interest'
    GEOM = 'geometry'
    DATASET = 'dataset'
    MAP = 'map'
    LAYER = 'layer'
    LAYER_CONFIGURATION = 'layer_configuration'
    AREA = 'area'

CLASS_NAME_TO_RDE = {
    # the short version are left here for compatibility in certain previous version of the API/Data model, to be removed eventually
    'hr': RDEType.HR,
    'obs': RDEType.OBS,
    'poi': RDEType.POI,
    'historical_record': RDEType.HR, 
    'historicalrecord': RDEType.HR,
    'observation': RDEType.OBS,
    'point_of_interest': RDEType.POI,
    'pointofinterest': RDEType.POI,
    'geometry': RDEType.GEOM,
    'dataset': RDEType.DATASET,
    'map': RDEType.MAP,
    'layer': RDEType.LAYER,
    'layer_configuration': RDEType.LAYER_CONFIGURATION,
    'layerconfiguration': RDEType.LAYER_CONFIGURATION,
    'area': RDEType.AREA
}