# Data Validation

## RDE
Custom [JSON Schemas](https://json-schema.org/) have been designed to validate the data produced for ingestion in a Time Atlas instance according to the RDE Data Model. 

To run local validation of data, create and activate a python virtual environment
```bash
python3 -m venv validation_venv
source validation_venv/bin/activate
```

Install the dependencies

```bash
pip3 install -r requirements.txt
```

Run the validation

```bash
python3 validate_data.py
```

The script runs through all the JSON data files under `../rde/datasets` and validate each according to the corresponding schema, displaying any validation issue in the process, but does not interrupts itself until all data file are read and validate. In the case you want to script to interrupts in any validation error, the argument `--error_interrupt` can be passed through the script. No error messages means the data is valid. 

## IIIF
 IIIF data validation has already been designed by the [IIIF consortium itself](https://github.com/IIIF/presentation-validator), based on JSON Schema. Unfortunately they break some of the rules of the JSON Schema, so they have dedicated code to parse true IIIF validation issues to assumed issues in their modeling. Hence the IIIF validation can be run separately from the RDE validation in this repository, using a slighty modified version of the IIIF validator python to make it work in this context of pre-backend ingested data. To run validation only on IIIF data, follow the same steps as previously, while adding the argument "--only_iiif" to the python script invokation.

```bash
python3 validate_data.py --only_iiif
```