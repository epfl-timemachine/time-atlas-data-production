import re
import os
from pathlib import Path


def clean_old_versions_of_dataset(data_folder: str) -> None:    
    vs = list(map(str, Path(data_folder).glob('*son')))
    for s in {v.replace(isolate_date_string_from_fn(v), '').split('.')[0] for v in vs}:
        hit_vals = [v for v in vs if s in v]
        dates = [isolate_date_string_from_fn(h) for h in hit_vals]
        if len(dates) > 1:
            # removing the "max date" which is the most recent file, we want to keep it.
            dates.remove(max(dates)) 
            # I'm trying to practice my double for loop in one-liner style
            to_remove = [h for d in dates for h in hit_vals if d in h]
            for p in to_remove:
                os.remove(p)

def isolate_date_string_from_fn(fn: str) -> str:
    matches = [v for v in re.findall('[0-9]{8}', fn) if len(v) == 8]
    if len(matches) == 0:
        return ''
    if len(matches) != 1:
        raise Exception(f'Too many dates in the file string:', matches)
    return matches[0]

if __name__ == '__main__':
    all_data_folder = list(map(str,Path('.').glob("data_configuration/*/data"))) + ['data_configuration/dictionaries', 'data_configuration/aggregated_data'] + ['1740_Catastici', '1808_Sommarioni', '1808_Sommarioni/aggregated']
    for f in all_data_folder:
        clean_old_versions_of_dataset(f)