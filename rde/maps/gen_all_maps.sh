#!/bin/bash

# Find the directory where the script is located
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find and run all Python scripts in the same folder and its subfolders
find "$script_dir" -name "*.py" -type f | while read -r script; do
    script_dir="$(dirname "$script")"
    script_name="$(basename "$script")"
    echo "Running $script_name in $script_dir"
    # the "cd" so that relative imports in the python script works correctly with the script's directory
    (cd "$script_dir" && python3 "$script_name")
done