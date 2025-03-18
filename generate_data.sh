#!/bin/bash

# Step 1: Create and activate the virtual environment
python3 -m venv data-production-venv
source data-production-venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Function to run Python scripts in a directory
run_scripts_in_directory() {
    local dir=$1
    data_type=$(basename "$dir")
    data_type=${data_type%?}
    echo "Generating data for $data_type"
    for folder in "$dir"/*; do
        if [ -d "$folder" ]; then
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

# Step 2: Run scripts in rde/datasets
run_scripts_in_directory "rde/datasets"

# Step 3: Run scripts in rde/maps
run_scripts_in_directory "rde/maps"

# Step 4: Run scripts in rde/areas
cd rde/areas
echo "Generating data for areas"
python produce_areas.py
echo ""
cd - > /dev/null

# Inform success
echo "Data generation completed successfully."


# Step 5: Validate data
pip install -r validation/requirements.txt
cd validation
python validate_data.py


# Deactivate and remove the virtual environment
deactivate
rm -rf data-production-venv

echo "Data validation completed successfully."
