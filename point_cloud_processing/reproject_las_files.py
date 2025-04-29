"""
reprojects las files from EPSG:32633 to EPSG:4326
puts the point cloud on the ground by using a geoid model
deck.gl can only read las files with version 1.3 (not 1.4)

needs to be run in miniconda with pdal installed

//source: https://docs.anaconda.com/miniconda/install/#quick-command-line-install
curl https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe -o miniconda.exe
start /wait "" .\miniconda.exe /S
del miniconda.exe

conda install -c conda-forge pdal

LAS tools download: https://rapidlasso.de/downloads/

example commands:
pdal translate "D:\EPFL\parcels-of-venice\public\edifici_1522.las" "D:\EPFL\parcels-of-venice\public\edifici_1522_proj.las" reprojection --filters.reprojection.in_srs="EPSG:32633+4326" --filters.reprojection.out_srs="EPSG:4326+3855" --writers.las.scale_x=0.0000001 --writers.las.scale_y=0.0000001
las2las64 -i "D:\EPFL\parcels-of-venice\public\edifici_1522_proj.las" -o "D:\EPFL\parcels-of-venice\public\edifici_1522_proj2.las" -set_version 1.3
"""
import os
import subprocess

input_folder = r"D:\Data\PointCloud\las_files"
tmp_folder = r"D:\Data\PointCloud\las_files_tmp"
output_folder = r"D:\Data\PointCloud\las_files_proj"

las2las_path = r"C:\Program Files\LAStools\bin\las2las64"

for file_name in os.listdir(input_folder):
    print(file_name)
    input_file_path = os.path.join(input_folder, file_name)
    tmp_file_path = os.path.join(tmp_folder, file_name)
    output_file_path = os.path.join(output_folder, file_name)

    subprocess.run(f'pdal translate "{input_file_path}" "{tmp_file_path}" reprojection --filters.reprojection.in_srs="EPSG:32633+4326" --filters.reprojection.out_srs="EPSG:4326+3855" --writers.las.scale_x=0.0000001 --writers.las.scale_y=0.0000001')
    subprocess.run(f'"{las2las_path}" -i "{tmp_file_path}" -o "{output_file_path}" -set_version 1.3')


"""
//tried a LASTools only solution, but only horizontal reprojecting is possible:
las2las64 -i "D:\EPFL\parcels-of-venice\public\edifici_1522.las" -o "D:\EPFL\parcels-of-venice\public\edifici_1522_proj3.las" -epsg 32633 -target_precision 0.000000001 -target_longlat

//vertical reprojection is not working 
download https://www.agisoft.com/downloads/geoids/
gdal_translate C:/Users/Raimund/Downloads/us_nga_egm84_30.tif C:/Users/Raimund/Downloads/us_nga_egm84_30.asc
las2las -i C:/Users/Raimund/Downloads/us_nga_egm84_30.asc -o C:/Users/Raimund/Downloads/us_nga_egm84_30.las

lasheight64 -i "D:\EPFL\parcels-of-venice\public\edifici_1522_proj3.las" -o "D:\EPFL\parcels-of-venice\public\edifici_1522_proj4.las" -ground_points "C:\Users\Raimund\Downloads\us_nga_egm84_30.las" -replace_z -demo
"""