#!/usr/bin/env python3
"""
Script to prepare JSON files from the rde folder for upload by copying them
to a timestamped folder. Excludes files under 'src' folders and dataset-level
JSON files (only includes files from dataset/data/ subfolders).
"""

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime


FILENAMES_TO_KEEP = [
    'observations.json',
    'historical_records.json',
    'areas.json',
    'datasets.json',
    'layers.json',
    'map.json',
    'points_of_interest.json'
]


def get_timestamp():
    """Generate timestamp in format YYYYMMDDHHMM."""
    return datetime.now().strftime("%Y%m%d%H%M")


def format_size(bytes_size):
    """Format bytes into human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def should_include_file(file_path, rde_path):
    """
    Determine if a JSON file should be included based on exclusion rules.
    
    Args:
        file_path: Path object for the JSON file
        rde_path: Path to the rde folder
        
    Returns:
        bool: True if file should be included, False otherwise
    """
    # Get relative path from rde folder
    try:
        rel_path = file_path.relative_to(rde_path)
    except ValueError:
        return False
    
    parts = rel_path.parts
    filename = file_path.name
    
    # Skip if any parent directory is named 'src'
    if 'src' in parts:
        return False
    
    # Check if file is in datasets folder
    if len(parts) >= 2 and parts[0] == 'datasets':
        # For datasets, check if file is directly in rde/datasets/<dataset_name>/
        # and matches one of the filenames in FILENAMES_TO_KEEP
        if len(parts) == 3:
            return filename in FILENAMES_TO_KEEP
        
        # Include all files from iiif folders (rde/datasets/<dataset_name>/iiif/...)
        if len(parts) >= 3 and 'iiif' in parts:
            return True
        
        # Any other location in datasets (deeper nesting) should be excluded
        return False
    
    # Check if file is in areas folder
    if len(parts) >= 2 and parts[0] == 'areas':
        # Include files directly in rde/areas/<area>/ that match FILENAMES_TO_KEEP
        if len(parts) == 3:
            return filename in FILENAMES_TO_KEEP
        # Include files from rde/areas/<area>/data/
        if len(parts) >= 4 and parts[2] == 'data':
            return True
        # Any other location in areas should be excluded
        return False
    
    # All other JSON files are included (maps, pois, etc.)
    return True


def find_json_files(rde_path):
    """
    Find all .json files in the rde folder following the inclusion rules.
    
    Args:
        rde_path: Path to the rde folder
        
    Returns:
        List of Path objects for JSON files to copy
    """
    json_files = []
    
    for root, dirs, files in os.walk(rde_path):
        root_path = Path(root)
        
        # Find all .json files in current directory
        for file in files:
            if file.endswith('.json'):
                file_path = root_path / file
                if should_include_file(file_path, rde_path):
                    json_files.append(file_path)
    
    return json_files


def copy_file(file_path, output_folder, rde_path):
    """
    Copy a file to the output folder maintaining the directory structure.
    
    Args:
        file_path: Local file path
        output_folder: Destination folder path
        rde_path: Base path of rde folder (to calculate relative path)
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Calculate relative path from rde folder
    relative_path = file_path.relative_to(rde_path.parent)
    
    # Construct destination path
    dest_path = output_folder / relative_path
    
    try:
        # Create parent directories if they don't exist
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy the file
        shutil.copy2(file_path, dest_path)
        return True
    except Exception as e:
        print(f"✗ Failed to copy {relative_path}: {e}")
        return False


def main():
    """Main function to prepare data for upload."""
    print("=" * 70)
    print("Prepare Data for Upload Script")
    print("=" * 70)
    
    # Setup paths
    repo_root = Path(__file__).parent.parent
    rde_path = repo_root / "rde"
    
    if not rde_path.exists():
        print(f"Error: rde folder not found at {rde_path}")
        sys.exit(1)
    
    # Create s3_dump folder if it doesn't exist
    s3_dump_folder = repo_root / "s3_dump"
    s3_dump_folder.mkdir(parents=True, exist_ok=True)
    
    # Generate timestamp and create output folder
    timestamp = get_timestamp()
    output_folder = s3_dump_folder / timestamp
    
    print(f"\n[1/4] Configuration:")
    print(f"  Source folder: {rde_path}")
    print(f"  Output folder: {output_folder}")
    print(f"  Timestamp: {timestamp}")
    
    # Find JSON files
    print(f"\n[2/4] Scanning for JSON files...")
    print(f"  - Excluding files under 'src' folders")
    print(f"  - Including files from rde/datasets/<dataset>/ matching FILENAMES_TO_KEEP")
    print(f"  - Including all files from rde/datasets/<dataset>/iiif/")
    print(f"  - Including files from rde/areas/<area>/data/")
    json_files = find_json_files(rde_path)
    print(f"✓ Found {len(json_files)} JSON files to copy")
    
    if len(json_files) == 0:
        print("No files to copy. Exiting.")
        return
    
    # Create output folder
    print(f"\n[3/4] Creating output folder...")
    try:
        output_folder.mkdir(parents=True, exist_ok=True)
        print(f"✓ Created folder: {output_folder}")
    except Exception as e:
        print(f"Error creating output folder: {e}")
        sys.exit(1)
    
    # Copy files
    print(f"\n[4/4] Copying files...")
    
    # Calculate total size
    total_size = sum(f.stat().st_size for f in json_files)
    print(f"  Files to copy: {len(json_files)}")
    print(f"  Total volume: {format_size(total_size)}")
    print("-" * 70)
    
    successful_copies = 0
    failed_copies = 0
    
    for file_path in json_files:
        if copy_file(file_path, output_folder, rde_path):
            successful_copies += 1
        else:
            failed_copies += 1
    
    # Summary
    print("-" * 70)
    print("\n" + "=" * 70)
    print("Copy Summary")
    print("=" * 70)
    print(f"Total files: {len(json_files)}")
    print(f"Successful: {successful_copies}")
    print(f"Failed: {failed_copies}")
    print(f"\nOutput location: {output_folder}")
    print("=" * 70)


if __name__ == "__main__":
    main()
