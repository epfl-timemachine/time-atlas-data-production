import json
from referencing.jsonschema import DRAFT202012
from referencing import Registry
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pathlib import Path
from os.path import join
import sys
from argparse import ArgumentParser, BooleanOptionalAction
import os
from iiif_validation.schemavalidator import validate

def validate_iiif_file_and_report(fp:str, raise_error=False):
    try:
        err_reports = validate(open(fp).read())
        if err_reports['warnings'] and len(err_reports['warnings']) > 0:
            print(f"{len(err_reports['warnings'])} warnings found in {fp}:")
            for w in err_reports['warnings']:
                print('Warning:', w)
            
        if err_reports['errorList'] and len(err_reports['errorList']) > 0:
            print(f"{len(err_reports['errorList'])} errors found in {fp}:")
            for w in err_reports['errorList']:
                print('Error:', w)
            if raise_error:
                raise Exception('Validation errors found: ', err_reports['errorList'])
    except Exception as e:
        print(f"Error validating {fp}: {e}")
        raise e

parent_dir = os.path.abspath('../')
if parent_dir not in sys.path: sys.path.insert(0, parent_dir)
from utils.rde import RDE

all_resources_name = ["file", 
                RDE.HR.value,
                RDE.OBS.value,
                RDE.POI.value,
                RDE.GEOM.value, 
                RDE.DATASET.value,
                RDE.DATASET.value + '_configuration',
                "multilingual_data",
                RDE.AREA.value,
                RDE.LAYER.value,
                RDE.LAYER.value + '_configuration',
                RDE.MAP.value]
all_schemas = {k: json.load(open(f'schemas/{k}.schema.json')) for k in all_resources_name}
schema_store = [(s['$id'], DRAFT202012.create_resource(s)) for _,s in all_schemas.items()]

uuid_store = {}

def validate_file(fp:str, validator:Draft202012Validator, raise_error=False):
    with open(fp) as f:
        cont = json.load(f)
        try:
            validator.validate(cont)
        except ValidationError as e:
            uuids = []
            #the validationError launched from $ref tag with jsonschema is unfortunately very vague, so we need to check the error message by directly validating the object
            rde_type = cont['type_in_file'][0]
            corr_schema = all_schemas[rde_type]
            rde_validator = Draft202012Validator(schema=corr_schema, registry=registry)
            try:
                for obj in cont['rde_objects']:
                    rde_validator.validate(obj)
                    uuids.append(obj['uuid'])
            except ValidationError as e:
                if raise_error:
                    raise e
                else:
                    print(f'Error in {fp}, on obj {obj}: {e}')
                    uuid_store[fp] = uuids
                    return
            uuid_store[fp] = uuids
                

file_schema = all_schemas['file']
registry = Registry().with_resources(schema_store)
validator = Draft202012Validator(schema=file_schema, registry=registry)

if __name__ == '__main__':
    args = ArgumentParser()
    args.add_argument('-d', '--dataset', default=None, help='Dataset to validate (does no support maps and areas)')
    args.add_argument('--only_iiif', default=False, action=BooleanOptionalAction, help='Only validate IIIF files')
    args.add_argument('--error_interrupt', default=False, action=BooleanOptionalAction, help='Interrupts the script if any validation fails')
    args = args.parse_args()

    DATASET_ROOT = '../rde/datasets'
    dataset_list = os.listdir(DATASET_ROOT)
    if args.dataset:
        new_dataset_list = [d for d in dataset_list if args.dataset in d]
        if len(new_dataset_list) == 0:
            print(f'Dataset {args.dataset} not found in {DATASET_ROOT}')
            sys.exit(1)
        dataset_list = new_dataset_list
    if not args.only_iiif:
        for d in dataset_list:
            # not validating pois, as they will be validated separately.
            all_files_to_validate = [v for v in list(Path(join(DATASET_ROOT, d, 'data')).rglob('*.json')) if 'iiif' not in str(v) and 'points_of_interest.json' not in str(v)]
            for fp in all_files_to_validate:
                print(f'Validating {fp}')
                validate_file(fp, validator, raise_error=args.error_interrupt)
        
        MAP_ROOT = '../rde/maps'
        map_list = os.listdir(MAP_ROOT)
        for m in map_list:
            all_files_to_validate = [v for v in list(Path(join(MAP_ROOT, m)).rglob('*.json'))]
            for fp in all_files_to_validate:
                print(f'Validating {fp}')
                validate_file(fp, validator)

        AREA_ROOT = '../rde/areas/data'
        for a in list(Path(AREA_ROOT).rglob('*.json')):
            print(f'Validating {a}')
            validate_file(a, validator)

        POIS_ROOT = '../rde/pois'
        for p in list(Path(POIS_ROOT).rglob('*.json')):
            print(f'Validating {p}')
            validate_file(p, validator)

    print('Checking unicity of UUIDs')
    uuid_file = {}
    for k, vs in uuid_store.items():
        for v in vs:
            if v not in uuid_file:
                uuid_file[v] = k
            else:
                print(f'UUID {v} found in multiple files: {uuid_file[v]} and {k}')
                if args.error_interrupt:
                    raise Exception(f'UUID {v} found in multiple files: {uuid_file[v]} and {k}')

    for ds in dataset_list:
        if 'catastici' in ds:
            continue
        iiif_loc_path = os.path.join(DATASET_ROOT, ds, 'data', 'iiif')
        if os.path.exists(iiif_loc_path):
            coll_list = [f for f in  os.listdir(os.path.join(iiif_loc_path, 'collections')) if f.endswith('.json')]
            if len(coll_list) > 1:
                print('Multiple collections found in', ds, ' is this expected?')
                print('Validating collection manifests of', ds)
            else:
                print('Validating collection manifest of', ds)
            for c in coll_list:
                validate_iiif_file_and_report(os.path.join(iiif_loc_path, 'collections', c))
            man_list = os.listdir(os.path.join(iiif_loc_path, 'manifests'))
            print('Validating ', len(man_list), ' manifests of ', ds)
            man_list = [m for m in man_list if m.endswith('.json')]
            for m in man_list:
                try:
                    validate_iiif_file_and_report(os.path.join(iiif_loc_path, 'manifests', m))
                except Exception as e:
                    print(f"Error validating {m}: {e}")
