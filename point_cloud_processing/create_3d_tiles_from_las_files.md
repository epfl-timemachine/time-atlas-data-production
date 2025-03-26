### Merge all files to one:
//download LASTools https://rapidlasso.de/downloads/

C:\Users\Raimund\Downloads\LAStools\LAStools\bin\lasmerge64 -i *.las -o merge.las

### Reproject vertical and horizontal coordinate system:
//source: https://gis.stackexchange.com/questions/257841/converting-lidar-ellipsoidal-heights-to-orthometric-heights

//source: https://docs.anaconda.com/miniconda/install/#quick-command-line-install
curl https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe -o miniconda.exe
start /wait "" .\miniconda.exe /S
del miniconda.exe

conda install -c conda-forge pdal 

//https://pdal.io/en/stable/stages/filters.reprojection.html
pdal translate "C:\Users\Raimund\Downloads\merge.las" "C:\Users\Raimund\Downloads\merge_transformed.las" reprojection --filters.reprojection.in_srs="EPSG:32633+4326" --filters.reprojection.out_srs="EPSG:32633+3855"

### Create 3D tiles:

"C:\Users\Raimund\Downloads\gocesiumtiler-v2.0.1\gocesiumtiler-win-x64.exe" file -out D:\EPFL\parcels-of-venice\public\pointcloud -crs 32633 "C:\Users\Raimund\Downloads\merge_transformed.las"

"C:\Users\Raimund\Downloads\gocesiumtiler-v2.0.1\gocesiumtiler-win-x64.exe" folder -out C:\Users\Raimund\Downloads\las_out\las_folder2 -crs 32633 -j "C:\Users\Raimund\Downloads\las_files"

### Test to store file ID as attributes:

pdal pipeline pipeline.json

```
{
  "pipeline": [
    {
      "type": "readers.las",
      "filename": "C:\\Users\\Raimund\\Downloads\\las_files\\edifici_963.las"
    },
    {
      "type": "filters.assign",
      "value": "Classification=100"
    },
	{
      "type": "filters.assign",
      "value": "Intensity=200"
    },
    {
      "type": "writers.las",
      "filename": "C:\\Users\\Raimund\\Downloads\\las_selection\\edifici_963.las"
    }
  ]
}

```

See encode_id_in_las_files.py for batch script