---
name: timeatlas-post-production-steps
description: 'Pipeline steps to run after generating TimeAtlas dataset output files. Use after datasets.json, historical_records.json, and observations.json have been produced for a dataset. Runs observation-to-POI aggregation (merge_obs.py) and JSON schema validation (validate_data.py). Always run both steps before considering data production complete.'
---

# TimeAtlas Post-Production Pipeline

## When to Use

Run these steps **after** all dataset output JSON files have been generated and saved. They must be executed in order:
1. Aggregate observations into Points of Interest
2. Validate the produced data against JSON schemas

---

## Step 1 — Aggregate Observations into Points of Interest

Run `merge_obs.py` from the `rde/pois/` directory. Use the `--filter` argument to restrict processing to the specific dataset.

```bash
cd rde/pois
source ../../data-production-venv/bin/activate
python merge_obs.py --filter <dataset-slug>
```

Replace `<dataset-slug>` with the dataset folder name (e.g., `amsterdam-1647-1652-housing-rent`).

What this does:
- Reads all `observations.json` files from dataset folders matching the filter
- Groups co-located observations (rounded to 5 decimal degrees) into shared Points of Interest
- Updates `rde/pois/points_of_interest.json` with the aggregated POIs

**Important:** The script uses relative paths (`../datasets/`) and **must be run from the `rde/pois/` directory**.

---

## Step 2 — Validate the Produced Data

Run `validate_data.py` from the `validation/` directory, targeting the specific dataset:

```bash
cd validation
source ../data-production-venv/bin/activate
python validate_data.py -d <dataset-slug>
```

Replace `<dataset-slug>` with the dataset slug (substring match is supported).

What this does:
- Validates all `.json` files in the dataset folder against the JSON schemas in `validation/schemas/`
- Checks that every RDE object conforms to its type schema
- Checks UUID uniqueness across all validated files

Optional flags:
- `--error_interrupt` — stop on the first validation error (useful for debugging)

**Important:** The script uses relative paths (`../rde/datasets/`) and **must be run from the `validation/` directory**.

---

## Expected Outcome

- Step 1 completes without errors and reports the count of observations processed.
- Step 2 prints `Validating <filepath>` for each file and reports any schema errors.
- If Step 2 reports validation errors, fix them in the production script and regenerate the affected files before considering the dataset production complete.
