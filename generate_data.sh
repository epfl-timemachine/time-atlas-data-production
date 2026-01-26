#!/bin/bash

# Step 1: Create and activate the virtual environment
python3 -m venv data-production-venv
source data-production-venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Function to run Python scripts in a directory
run_scripts_in_directory() {
    local dir=$1
    shift
    local exception_array=("$@")
    data_type=$(basename "$dir")
    echo "Generating data for $data_type"
    data_type=${data_type%?} # Remove the trailing 's'
    for folder in "$dir"/*; do
        if [ -d "$folder" ]; then
            folder_name=$(basename "$folder")
            # Check if folder is in exception array
            skip=false
            for exception in "${exception_array[@]}"; do
                if [ "$folder_name" = "$exception" ]; then
                    skip=true
                    echo "Skipping $folder_name (in exception list)"
                    break
                fi
            done
            if [ "$skip" = true ]; then
                continue
            fi
            cd "$folder"
            script=$(ls *.py 2>/dev/null)
            if [ -n "$script" ]; then
                echo "Running script for $data_type: $folder"
                python "$script"
                if [ $? -ne 0 ]; then
                    echo "Error: Script $script in $folder failed."
                    deactivate
                    rm -rf data-production-venv
                    exit 1
                fi
            fi
            echo ""
            cd - > /dev/null
        fi
    done
}


# Step 2: Run scripts in rde/maps
run_scripts_in_directory "rde/maps"

# Step 3: Run scripts in rde/datasets
run_scripts_in_directory "rde/datasets" "amsterdam-1832-huurwarden" "europeana-pipeline-postcards" "venice-1740-catastici" "venice-1808-sommarioni" "dresden-4d-browser-data" "lausanne-mhl-iconographie" "lausanne-1888-cadastre-renove" "venice-contemporary-cloudpoint"

# Step 4: Run scripts in rde/areas
cd rde/areas
echo "Generating data for areas"
python produce_areas.py
echo ""
cd - > /dev/null

# Step 4: Run script in rde/pois
cd rde/pois
echo "Generating Points of Interests object from the observations"
python merge_obs.py
echo ""
cd - > /dev/null

# Inform success
echo "Data generation completed successfully."

# Step 5: Validate data
pip install -r validation/requirements.txt
cd validation
python validate_data.py

# Deactivate and remove the virtual environment
cd - > /dev/null
deactivate
rm -rf data-production-venv

echo "Data validation completed successfully."
