import re
import os
from pathlib import Path

filenames_to_remove = [
    'observations.json',
    'historical_records.json',
    'areas.json',
    'datasets.json',
    'layers.json',
    'map.json',
    'points_of_interest.json'
]

if __name__ == '__main__':
    rde_path = Path('../')
    for dataset_dir in rde_path.glob('datasets/*'):
        if dataset_dir.is_dir():
            for filename in filenames_to_remove:
                file_to_remove = dataset_dir / filename
                if file_to_remove.exists():
                    os.remove(file_to_remove)

    for map_dir in rde_path.glob('maps/*'):
        if map_dir.is_dir():
            file_to_remove = map_dir / filename
            if file_to_remove.exists():
                os.remove(file_to_remove)
    for area_file in rde_path.glob('areas/data/*'):
        if area_file.is_file() and area_file.suffix in ['.json', '.geojson']:
            file_to_remove = area_file
            if file_to_remove.exists():
                os.remove(file_to_remove)