See @README.md for data structure details
See @time-atlas-python for documentation about the official python library of the TimeAtlas.

You are working as a data engineer in the TimeAtlas project whose task is to analyze diverse sources of culturage heritage data and fit them into the data structure expected of the platform.
- Always use ```source data-production-venv``` for running and testing code.
Rely on existing libraries and functions whenever possible, including pandas, geopandas and shapely.


## Project folder structure
.
├── README.md                          # Main documentation
├── AGENTS.md                          # Agent instructions for AI assistants
├── CHANGELOG.md                       # Version history and changes
├── generate_data.sh                   # Main execution script for data production pipeline
├── requirements.txt                   # Python dependencies
├── TimeAtlasDataModelV2.png          # Data model diagram
├── python_wrapper_demo.ipynb         # Demo notebook for Python library usage
│
├── data_modeling_tuto/               # Tutorial and examples for data modeling
│   ├── README.md                     # Modeling guide and CSV format specifications
│   └── example/                      # Sample data production workflow
│       ├── produce_sample_data.ipynb # Example notebook
│       ├── sommarioni_sample.csv     # Sample CSV data
│       ├── sommarioni_sample.geojson # Sample geometries
│       └── sommarioni_sample.json    # Sample configuration
│
├── data-lausanne/                    # Lausanne-specific datasets and processing
│   ├── README.md
│   ├── 1831-cadastre-berney/        # 1831 Berney cadastre data
│   │   ├── formatting.ipynb         # Data formatting notebook
│   │   ├── *.geojson                # Cadastral geometries
│   │   └── wh_images.csv            # Image metadata
│   ├── 1888-cadastre-renove/        # 1888 renovated cadastre
│   │   ├── formatting.ipynb
│   │   ├── *.geojson                # Cadastral geometries
│   │   ├── *.csv                    # Registry data
│   │   └── src/                     # Source processing scripts
│   ├── annuaire-tables/             # Historical directory tables
│   │   └── *.csv, *.json            # Geocoded address data
│   └── icono-data-processing/       # Iconographic data processing
│       ├── check-duplicates.py
│       ├── download-images.py
│       ├── generate-iiif-manifests.py
│       └── *.csv, *.json            # Image metadata and matching
│
├── data-venice/                      # Venice-specific datasets and processing
│   ├── README.md
│   ├── 1740_Catastici/              # 1740 Catastici cadastre
│   ├── 1808_Sommarioni/             # 1808 Napoleonic cadastre
│   ├── Dorigo/                       # Dorigo's Venice study data
│   ├── contemporary_maps/           # Modern Venice vectorizations (OSM-derived)
│   ├── data-alignment/              # Data cleaning and reconciliation notebooks
│   ├── data-vizualisation/          # Venice data visualization notebooks
│   ├── named_entity_standardisation/ # NER standardization results
│   └── deprecated/                   # Legacy data and code (reference only)
│
├── rde/                              # Output: Generated Research Data Entities
│   ├── areas/                        # Area entity JSON files
│   ├── datasets/                     # Dataset entity JSON files
│   ├── maps/                         # Map entity JSON files
│   └── pois/                         # Point of Interest entity JSON files
│
├── utils/                            # Utility scripts and tools
│   ├── data_modeling.py             # Core data modeling functions
│   ├── prepare_data_for_upload.py   # Upload preparation script
│   ├── produce_aggregated_datasets.py # Dataset aggregation
│   ├── iiif.py                      # IIIF manifest utilities
│   ├── map_thumbnail_generator.py   # Map thumbnail generation
│   ├── get_terrain_and_building_heights.py # Elevation data extraction
│   ├── extract_observations_coordinates.py # Coordinate extraction
│   ├── s3_bucket_push.py            # S3 bucket operations
│   ├── clean_old_datasets.py        # Dataset cleanup
│   ├── images_width_height_format_extractor.py # Image metadata
│   ├── segment_swiss3d_lidar.py     # LiDAR segmentation
│   ├── convert_webp_to_jpg.sh       # Image format conversion
│   └── mini_manifest_server.py      # Local IIIF manifest server
│
├── validation/                       # Data validation tools
│   ├── README.md
│   ├── validate_data.py             # Main validation script
│   ├── bootstraping_schema.ipynb    # Schema development notebook
│   ├── schemas/                     # JSON schemas for RDE validation
│   ├── iiif_validation/             # IIIF-specific validation
│   └── requirements.txt
│
├── point_cloud_processing/          # LiDAR point cloud processing
│   ├── create_3d_tiles_from_las_files.md # 3D tiles documentation
│   ├── encode_id_in_las_files.py    # ID encoding in LAS format
│   └── reproject_las_files.py       # CRS reprojection
│
├── time-atlas-python/               # Official Python library (submodule)
│   ├── README.md
│   ├── documentation/               # Library documentation
│   └── timeatlas/                   # Python package source
│
└── data-production-venv/            # Python virtual environment

## Coding, documentation, and logging
- you may use all the scripts written in "rde/dataset/<dataset-name>/produce_<dataset-name>_data.py" as inspiration, however note they are legacy script, using procedural function. You should as much as possible work in a more streamlined way, by directly instantiating the python library classes straight from the data.
- generally, the uuid should be deterministic and as such sourced from a unique identifier stemming from the data, don't forget to instantiate a UUIDManager with a dedicated namespace per dataset and use that coupled with the unique identifier to generate deterministic UUID.
