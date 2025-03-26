import math
import os
import laspy

input_folder = r"C:\Users\Raimund\Downloads\las_files"
output_folder = r"C:\Users\Raimund\Downloads\las_files_with_id"

for file_name in os.listdir(input_folder):
    file_id = file_name.replace("edifici_", "").replace(".las", "")
    file_id = int(file_id)

    classification_id = math.floor(file_id / 255)
    intensity_id = file_id % 255

    if file_name.endswith(".las"):
        las = laspy.read(f"{input_folder}/{file_name}")
        las.classification = [classification_id] * len(las.points)
        las.intensity = [intensity_id] * len(las.points)
        las.write(f"{output_folder}/{file_name}")