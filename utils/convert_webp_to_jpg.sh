#!/bin/bash

# Check if folder path argument is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <folder_path>"
    exit 1
fi

FOLDER_PATH="$1"

# Check if the folder exists
if [ ! -d "$FOLDER_PATH" ]; then
    echo "Error: Folder '$FOLDER_PATH' does not exist"
    exit 1
fi

# Check if ImageMagick convert command is available
if ! command -v convert &> /dev/null; then
    echo "Error: ImageMagick 'convert' command not found"
    exit 1
fi

# Convert all .webp files to .jpg
for webp_file in "$FOLDER_PATH"/*.webp; do
    # Check if any .webp files exist
    if [ ! -e "$webp_file" ]; then
        echo "No .webp files found in '$FOLDER_PATH'"
        exit 0
    fi
    
    # Get the base filename without extension
    base_name=$(basename "$webp_file" .webp)
    
    # Create output filename
    jpg_file="$FOLDER_PATH/$base_name.jpg"
    
    echo "Converting: $webp_file -> $jpg_file"
    
    # Convert the file
    convert "$webp_file" "$jpg_file"
    
    if [ $? -eq 0 ]; then
        echo "✓ Successfully converted: $base_name.webp"
    else
        echo "✗ Failed to convert: $base_name.webp"
    fi
done

echo "Conversion complete!"
