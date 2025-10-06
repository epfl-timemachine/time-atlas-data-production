
from PIL import Image
import os
import sys
import pandas as pd
from tqdm import tqdm

def is_extension_an_img(ext:str) -> bool:
    """
    This function returns True if the extension is an image and False otherwise.
    """
    return ext.lower() in ['jpg', 'png', 'jpeg', 'gif', 'bmp', 'tif', 'tiff', 'svg', 'webp']

def is_filepath_an_img(fp:str) -> bool:
    """
    This function returns True if the file path is an image and False otherwise.
    """
    if is_extension_an_img(fp.split('.')[-1]):
        try:
            _ = Image.open(fp)
            return True
        except:
            return False
    return False

def img_extension_to_media_type(ext:str) -> str:
    """
    This function returns the media type of the image extension.
    """
    if ext == 'jpg':
        return 'image/jpeg'
    elif ext == 'png':
        return 'image/png'
    elif ext == 'jpeg':
        return 'image/jpeg'
    elif ext == 'gif':
        return 'image/gif'
    elif ext == 'bmp':
        return 'image/bmp'
    elif ext == 'tiff' or ext == 'tif':
        return 'image/tiff'
    elif ext == 'webp':
        return 'image/webp'
    elif ext == 'svg':
        return 'image/svg+xml'
    else:
        return 'image'

def filepath_format_and_width_height_of_imgs(folder_path:str) -> pd.DataFrame:
    """
    This function returns a DataFrame with the format of the file path of the images in the folder and the width and height of the images.
    """
    data = []
    files = os.walk(folder_path)
    for f, sf, fs in tqdm(files):
        for file in fs:
            curr_img_fp = os.path.join(f, file)
            if is_filepath_an_img(curr_img_fp):
                img = Image.open(curr_img_fp)
                data.append([curr_img_fp.replace(folder_path, ''), img.size[0], img.size[1], img_extension_to_media_type(curr_img_fp.split('.')[-1])])
    return pd.DataFrame(data, columns=['filename', 'width', 'height', 'media_type'])


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: python images_width_height_extractor.py <path_base> <output_csv>')
        sys.exit(1)
    
    path_base = sys.argv[1]
    output_csv = sys.argv[2]
    if not os.path.exists(path_base):
        print(f'The path "{path_base}" does not exist.')
        sys.exit(1)
    if not os.path.isdir(path_base):
        print(f'The path "{path_base}" is not a directory.')
        sys.exit(1)
    if not output_csv.endswith('.csv'):
        print('The output filename must be a CSV file.')
        sys.exit(1)
    if os.path.exists(output_csv):
        print(f'The output filename "{output_csv}" already exists.')
        sys.exit(1)
    
    df_wh = filepath_format_and_width_height_of_imgs(path_base)
    df_wh.sort_values(by='filename').to_csv(output_csv, index=False)