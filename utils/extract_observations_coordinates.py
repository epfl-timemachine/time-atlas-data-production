#!/usr/bin/env python3
"""
Extract coordinates from all RDE dataset observations.
This script processes all datasets in the rde/datasets directory,
reads their observations.json files, and extracts coordinates into a DataFrame.
"""

import json
import os
from pathlib import Path
import pandas as pd


def extract_coordinates_from_datasets(rde_base_path):
    """
    Extract coordinates from all dataset observations.
    
    Args:
        rde_base_path: Path to the rde directory
        
    Returns:
        pandas.DataFrame: DataFrame with columns: dataset_name, longitude, latitude
    """
    results = []
    datasets_path = Path(rde_base_path) / "datasets"
    
    # Iterate through all dataset directories
    for dataset_dir in datasets_path.iterdir():
        if not dataset_dir.is_dir() or dataset_dir.name.startswith('.'):
            continue
            
        dataset_name = dataset_dir.name
        observations_file = dataset_dir / "data" / "observations.json"
        
        # Check if observations.json exists
        if not observations_file.exists():
            print(f"⚠️  No observations.json found for {dataset_name}")
            continue
        
        # Read and parse the JSON file
        try:
            with open(observations_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract rde_objects array
            rde_objects = data.get('rde_objects', [])
            
            if not rde_objects:
                print(f"⚠️  No rde_objects found in {dataset_name}")
                continue
            
            # Process each observation object
            for obj in rde_objects:
                geometry = obj.get('geometry')
                
                if geometry and geometry.get('type') == 'Point':
                    coordinates = geometry.get('coordinates')
                    if coordinates and len(coordinates) >= 2:
                        longitude, latitude = coordinates[0], coordinates[1]
                        results.append((dataset_name, longitude, latitude))
                elif geometry and geometry.get('type') in ['Polygon', 'MultiPolygon', 'LineString']:
                    # For non-point geometries, we could extract centroids or skip
                    # For now, we'll skip them
                    pass
            
            print(f"✓ Processed {dataset_name}: {len([r for r in results if r[0] == dataset_name])} observations")
            
        except json.JSONDecodeError as e:
            print(f"❌ Error reading JSON for {dataset_name}: {e}")
        except Exception as e:
            print(f"❌ Error processing {dataset_name}: {e}")
    
    # Convert results to DataFrame
    df = pd.DataFrame(results, columns=['dataset_name', 'longitude', 'latitude'])
    
    return df


def main():
    """Main function to execute the script."""
    # Get the script directory and navigate to rde
    script_dir = Path(__file__).parent
    rde_path = script_dir.parent / "rde"
    
    if not rde_path.exists():
        print(f"❌ RDE directory not found at {rde_path}")
        return
    
    print(f"Extracting coordinates from datasets in: {rde_path}")
    print("=" * 80)
    
    # Extract coordinates
    df = extract_coordinates_from_datasets(rde_path)
    
    print("=" * 80)
    print(f"\n📊 Summary:")
    print(f"Total observations: {len(df)}")
    print(f"Datasets processed: {df['dataset_name'].nunique()}")
    print(f"\nObservations per dataset:")
    print(df['dataset_name'].value_counts().to_string())
    
    # Display first few rows
    print(f"\n📋 First 10 rows:")
    print(df.head(10).to_string(index=False))
    
    # Optionally save to CSV
    output_file = script_dir / "observations_coordinates.csv"
    df.to_csv(output_file, index=False)
    print(f"\n💾 Saved to: {output_file}")
    
    return df


if __name__ == "__main__":
    df = main()
