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
    DICT = 'dictionary'