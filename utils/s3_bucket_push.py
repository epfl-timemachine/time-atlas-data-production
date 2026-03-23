#!/usr/bin/env python3
"""
Script to push JSON files from the rde folder to an Amazon S3 bucket.
Excludes files under 'src' folders and maintains the tree structure.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv


def load_s3_credentials():
    """Load S3 credentials from .env file."""
    # Load .env file from the repository root
    repo_root = Path(__file__).parent.parent
    env_path = repo_root / ".env"
    
    if not env_path.exists():
        print(f"Error: .env file not found at {env_path}")
        sys.exit(1)
    
    load_dotenv(env_path)
    
    access_key = os.getenv("S3_RW_KEY")
    secret_key = os.getenv("S3_RW_SECRET")
    
    if not access_key or not secret_key:
        print("Error: S3_RW_KEY or S3_RW_SECRET not found in .env file")
        sys.exit(1)
    
    return access_key, secret_key


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


def find_json_files(rde_path):
    """
    Find all .json files in the rde folder that are not under 'src' folders.
    
    Args:
        rde_path: Path to the rde folder
        
    Returns:
        List of Path objects for JSON files to upload
    """
    json_files = []
    
    for root, dirs, files in os.walk(rde_path):
        # Skip if current directory or any parent is named 'src'
        root_path = Path(root)
        if 'src' in root_path.parts:
            continue
        
        # Find all .json files in current directory
        for file in files:
            if file.endswith('.json'):
                json_files.append(Path(root) / file)
    
    return json_files


def upload_to_s3(file_path, s3_client, bucket_name, base_s3_path, rde_path):
    """
    Upload a file to S3 maintaining the directory structure.
    
    Args:
        file_path: Local file path
        s3_client: Boto3 S3 client
        bucket_name: S3 bucket name
        base_s3_path: Base path in S3 bucket (includes timestamp subfolder)
        rde_path: Base path of rde folder (to calculate relative path)
    """
    # Calculate relative path from rde folder
    relative_path = file_path.relative_to(rde_path.parent)
    
    # Construct S3 key
    s3_key = f"{base_s3_path}/{relative_path}"
    
    try:
        # Read file and upload using put_object to avoid multipart upload checksums
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=file_content,
            ContentType='application/json'
        )
        print(f"✓ Uploaded: {relative_path} -> s3://{bucket_name}/{s3_key}")
        return True
    except ClientError as e:
        print(f"✗ Failed to upload {relative_path}: {e}")
        return False
    except Exception as e:
        print(f"✗ Failed to upload {relative_path}: {e}")
        return False


def main():
    """Main function to push files to S3."""
    # Disable checksums for S3 uploads (for EPFL S3 compatibility)
    os.environ['AWS_METADATA_SERVICE_NUM_ATTEMPTS'] = '0'
    
    print("=" * 70)
    print("S3 Bucket Push Script")
    print("=" * 70)
    
    # Load credentials
    print("\n[1/5] Loading S3 credentials...")
    access_key, secret_key = load_s3_credentials()
    print("✓ Credentials loaded successfully")
    
    # Setup paths
    repo_root = Path(__file__).parent.parent
    rde_path = repo_root / "rde"
    
    if not rde_path.exists():
        print(f"Error: rde folder not found at {rde_path}")
        sys.exit(1)
    
    # S3 configuration
    s3_endpoint = "https://s3.epfl.ch"
    bucket_name = "13070-9df47f33956a41c58fc3f043d6f2e9e1"
    base_path = "time-atlas/data-ingestion-test"
    timestamp = get_timestamp()
    full_s3_path = f"{base_path}/{timestamp}"
    
    print(f"\n[2/5] Configuration:")
    print(f"  Local folder: {rde_path}")
    print(f"  S3 Endpoint: {s3_endpoint}")
    print(f"  S3 Bucket: {bucket_name}")
    print(f"  S3 Path: {full_s3_path}")
    print(f"  Timestamp: {timestamp}")
    
    # Find JSON files
    print(f"\n[3/5] Scanning for JSON files (excluding 'src' folders)...")
    json_files = find_json_files(rde_path)
    print(f"✓ Found {len(json_files)} JSON files to upload")
    
    if len(json_files) == 0:
        print("No files to upload. Exiting.")
        return
    
    # Initialize S3 client
    print(f"\n[4/5] Connecting to S3...")
    try:
        # Configure S3 client to disable checksums for compatibility with EPFL S3
        s3_config = Config(
            signature_version='s3v4',
            s3={'payload_signing_enabled': False}
        )
        s3_client = boto3.client(
            's3',
            endpoint_url=s3_endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=s3_config
        )
        print("✓ Connected to S3")
    except Exception as e:
        print(f"Error connecting to S3: {e}")
        sys.exit(1)
    
    # Upload files
    print(f"\n[5/5] Uploading files...")
    
    # Calculate total size
    total_size = sum(f.stat().st_size for f in json_files)
    print(f"  Files to upload: {len(json_files)}")
    print(f"  Total volume: {format_size(total_size)}")
    print("-" * 70)
    
    successful_uploads = 0
    failed_uploads = 0
    
    for file_path in json_files:
        if upload_to_s3(file_path, s3_client, bucket_name, full_s3_path, rde_path):
            successful_uploads += 1
        else:
            failed_uploads += 1
    
    # Summary
    print("-" * 70)
    print("\n" + "=" * 70)
    print("Upload Summary")
    print("=" * 70)
    print(f"Total files: {len(json_files)}")
    print(f"Successful: {successful_uploads}")
    print(f"Failed: {failed_uploads}")
    print(f"\nS3 Location: s3://{bucket_name}/{full_s3_path}/")
    print("=" * 70)


if __name__ == "__main__":
    main()
