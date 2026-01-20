from enum import Enum

class RDE(Enum):
    HR = 'historical_record'
    OBS = 'observation'
    POI = 'point_of_interest'
    GEOM = 'geometry'
    DATASET = 'dataset'
    MAP = 'map'
    LAYER = 'layer'
    AREA = 'area'


CLASS_NAME_TO_RDE = {
    'hr': RDE.HR,
    'obs': RDE.OBS,
    'poi': RDE.POI,
    'geometry': RDE.GEOM,
    'dataset': RDE.DATASET,
    'map': RDE.MAP,
    'layer': RDE.LAYER,
    'area': RDE.AREA
}