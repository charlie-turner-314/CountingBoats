import json
import math
import os
import PIL
import pyproj
import re
import random

from PIL import Image
from osgeo import gdal

gdal.UseExceptions()

class Classification(object):
    """
    This class is used to reference each of the classifications made using labelme that are stored in the output csv
    """

    def __init__(self, left, right, top, bottom, label):
        """
        Instantiate the object.

        Args:
            left: The left edge of the classification
            right: The right edge of the classification
            top: The top edge of the classification
            bottom: The bottom edge of the classification
            label: The label assigned to the classification
        """
        self._left = left
        self._right = right
        self._top = top
        self._bottom = bottom
        self._label = label

    def get_left(self):
        return self._left

    def get_right(self):
        return self._right

    def get_top(self):
        return self._top

    def get_bottom(self):
        return self._bottom

    def get_label(self):
        return self._label

    def in_bounds(self, left: float, right: float, top:float, bottom: float):
        """
        Check if this classification is within a larger bounding box defined by the parameters of this function

        Args:
            left: The left edge of the classification
            right: The right edge of the classification
            top: The top edge of the classification
            bottom: The bottom edge of the classification
        
        Returns
            True if the classification is within the bounding box specified; false otherwise.
        """
        if (self.get_bottom() < bottom and self.get_top() > top and
                self.get_left() > left and self.get_right() < right):
            return True
        else:
            return False

    def serialise(self):
        return {
            "top": self.get_top(),
            "bottom": self.get_bottom(),
            "left": self.get_left(),
            "right": self.get_right(),
            "label": self.get_label()
        }


def add_margin(pil_img: Image , left: int, right: int, top: int, bottom: int, color: tuple) -> Image:
    """
    Pads an OPEN PIL (pillow/python imaging library) image on each edge by the amount specified.

    Args:
        pil_img: The open PIL image to pad.
        left: The number of pixels to pad the left edge of the image by.
        right: The number of pixels to pad the right edge of the image by.
        top: The number of pixels to pad the top edge of the image by.
        bottom: The number of pixels to pad the bottom edge of the image by.
        color: What colour the padding should be as a tuple (0, 0, 0) for black (255, 255, 255) for white.
    
    Returns:
        The open PIL image after the padding has been applied
    """
    width, height = pil_img.size
    new_width = width + right + left
    new_height = height + top + bottom
    result = Image.new(pil_img.mode, (new_width, new_height), color)
    result.paste(pil_img, (left, top))
    return result


def segment_image(image, json_file, tile_size, stride, metadata_components=None, remove_empty=0.9, im_outdir=None, labels_outdir=None):
    """
    Segments a large .tif file into smaller .png files for use in a neural network. Also created
    files in the IMGtxts directory which contain the annotations present in that sub image.

    Args:
        image: The large .tif that is to be segmented
        json_file: The json file that contains all the classifications for the image that were made in labelme.
        size: The desired size (both length and width) of the segmented images.
        overlap_size: The desired amount of overlap that the segmented images should have
        metadata_components: The metadata of the image - useful if the metadata is stripped out in a previous
            operation on the image/file.

    Returns:
        None
    """
    # Open the image with tifffile - this reads the image in as a 2d array
    openImage = Image.open(image)

    # Get width and height by indexing the image array
    width, height = openImage.size
    width = int(width)
    height = int(height)

    # Open the json classifications file so create a Classification class object for each classification
    if os.path.isfile(json_file):
        with open(json_file, 'r') as f:
            data = json.load(f)

    # Extract the classifications and nothing else
    classifications = data['shapes']

    # Create an empty array which the Classification objects will be added to.
    allImageClassifications = []

    # Iterate through each classification and transform them into Classification class objects.
    for classification in classifications:
        try:
            x1, y1 = classification['points'][0]
            x2, y2 = classification['points'][1]
            top = round(min(y1, y2))
            left = round(min(x1, x2))
            bottom = round(max(y1, y2))
            right = round(max(x1, x2))
            label = classification['label']
            allImageClassifications.append(Classification(left, right, top, bottom, label))
        except:
            raise Exception(
                "Error in sorting classifications from JSON file, likely that one of the classifications is not a square")

    # Ensure that the image is divisible by the desired size with no remainder.
    if width % stride != 0 or height % stride != 0:
        raise Exception("The image is not exactly divisible by the desired size of subset images")

    # Ensure that the desired size is divisible by the desired overlap with no remainder.
    if tile_size % stride != 0:
        raise Exception("The subset image size indicated is not divisible by the input overlap size")

    print("Cropping Image: " + image)

    # Iterate over the original image and segment it into smaller images of the size specified in the parameters to
    # this function.
    for i in range(0, (int(height / stride) - (int(tile_size / stride)))):
        for j in range(0, 1 + int(width / stride) - (int(tile_size / stride))):
            cropImage = openImage.copy()
            left = j * stride
            top = i * stride
            right = left + tile_size
            bottom = top + tile_size

            # Track how many of the image border pixels are "empty". This means it is black/its array index value is
            # (0, 0, 0)
            percentageEmpty = 0
            total = 0

            # Get all classifications in the original image that would be in the smaller image that has just been
            # created.
            subsetClassifications = [classification for classification in allImageClassifications if
                                     classification.in_bounds(left, right, top, bottom)]

            if remove_empty > 0 and (subsetClassifications is None or subsetClassifications == []):
                subsetClassifications = []
                if random.uniform(0, 1) < remove_empty: 
                    continue

            for f in range(0, tile_size - 1, 8):
                # Iterate over the top edge of the image
                if openImage.getpixel((left + f, top)) == (0, 0, 0):
                    percentageEmpty += 1
                    total += 1
                else:
                    total += 1
                # Iterate over the left edge of the image
                if openImage.getpixel((left, top + f)) == (0, 0, 0):
                    percentageEmpty += 1
                    total += 1
                else:
                    total += 1
                # Iterate over the right edge of the image
                if openImage.getpixel((right - 1, top + f)) == (0, 0, 0):
                    percentageEmpty += 1
                    total += 1
                else:
                    total += 1
                # Iterate over the bottom edge of the image
                if openImage.getpixel((left + f, bottom - 1)) == (0, 0, 0):
                    percentageEmpty += 1
                    total += 1
                else:
                    total += 1

            # If more than 93% of the edge of the image is empty/black do NOT create a smaller image.
            # NOTE: This is a magic number and I have no idea why it is this value
            if percentageEmpty / total > 0.93:
                continue

            # Crop image
            croppedImage = cropImage.crop((left, top, right, bottom))

            if im_outdir is None:
                im_outdir = os.path.join(os.getcwd(), "SegmentedImages")

            # Save image
            path = os.path.join(im_outdir, os.path.basename(image).split(".")[0])
            croppedImage.save(path + "_" + str(i) + "_" + str(j) + ".png", quality=100, compress_level=0)

            # Write all of these classifications to a master set containing each time a classification appears in a
            # smaller/segmented image.
            im_name = os.path.basename(image).split(".")[0] + "_" + str(i) + "_" + str(j) + ".txt"

            if labels_outdir is None:
                labels_outdir = os.path.join(os.getcwd(), "Labels")

            path = os.path.join(labels_outdir, im_name)
            outfile = open(path, 'a+')

            if len(subsetClassifications) > 0:
                for elem in subsetClassifications:
                    if type(elem) == type(1):
                        continue
                    if elem.get_label() == 'tanker':
                        continue
                    if elem.get_label() == 'boat':
                        classLabel = 0
                    else:
                        classLabel = 1
                    outfile.write(str(classLabel) + " " +
                                  str((((elem.get_left()+elem.get_right())/2)-j*stride)/tile_size) + " " +
                                  str((((elem.get_top()+elem.get_bottom())/2)-i*stride)/tile_size) + " " +
                                  str((((elem.get_right()) - (elem.get_left())) / 2) / tile_size) + " " +
                                  str(((elem.get_bottom() - elem.get_top()) / 2) / tile_size) + "\n")

            outfile.close()
        print(str("Progress: " + str(int(float(i / ((height / stride) - 5)) * 100)) +
                  "%"), end="\r")
    print()

def segment_image_for_classification(image, data_path, tile_size, stride):
    """
    Segments a large .tif file into smaller .png files for use in a neural network.

    Args:
        image: The large .tif that is to be segmented
        size: The desired size (both length and width) of the segmented images.
        overlap_size: The desired amount of overlap that the segmented images should have
    
    Returns:
        None
    """
    # Open the image with pillow - this reads the image in as a 2d array
    openImage = Image.open(image)

    # Get width and height by indexing the image array
    width, height = openImage.size
    width = int(width)
    height = int(height)

    print(width, height)

    # Ensure that the image is divisible by the desired size with no remainder.
    if width % stride != 0 or height % stride != 0:
        raise Exception("The image is not exactly divisible by the desired size of subset images")

    # Ensure that the desired size is divisible by the desired overlap with no remainder.
    if tile_size % stride != 0:
        raise Exception("The subset image size indicated is not divisible by the input overlap size")

    # Iterate over the original image and segment it into smaller images of the size specified in the parameters to
    # this function.
    for i in range(0, (int(height / stride) - (int(tile_size / stride)))):
        for j in range(0, 1 + int(width / stride) - (int(tile_size / stride))):
            cropImage = openImage.copy()
            left = j * stride
            top = i * stride
            right = left + tile_size
            bottom = top + tile_size

            # Track how many of the image border pixels are "empty". This means it is black/it's array index value is
            # (0, 0, 0)
            percentageEmpty = 0
            total = 0

            for f in range(0, tile_size - 1, 8):
                # Iterate over the top edge of the image
                if openImage.getpixel((left + f, top)) == (0, 0, 0):
                    percentageEmpty += 1
                    total += 1
                else:
                    total += 1
                # Iterate over the left edge of the image
                if openImage.getpixel((left, top + f)) == (0, 0, 0):
                    percentageEmpty += 1
                    total += 1
                else:
                    total += 1
                # Iterate over the right edge of the image
                if openImage.getpixel((right - 1, top + f)) == (0, 0, 0):
                    percentageEmpty += 1
                    total += 1
                else:
                    total += 1
                # Iterate over the bottom edge of the image
                if openImage.getpixel((left + f, bottom - 1)) == (0, 0, 0):
                    percentageEmpty += 1
                    total += 1
                else:
                    total += 1

            # If more than 93% of the edge of the image is empty/black do NOT create a smaller image.
            if percentageEmpty / total > 0.93:
                continue

            # Crop image
            croppedImage = cropImage.crop((left, top, right, bottom))

            # Save image
            # make sure data_path exists
            if not os.path.exists(data_path):
                os.makedirs(data_path)
            savePath = os.path.join(data_path, os.path.basename(image).split('.')[0])
            croppedImage.save(savePath + "_" + str(i) + "_" + str(j) + ".png", quality=100, compress_level=0)

        print(str("Progress: " + str(int(float(i / ((height / stride) - 5)) * 100)) +
                  "%"), end="\r")

def create_padded_png(raw_dir, output_dir, file_name, tile_size=416, stride=104, rename=False):
    """
    Creates an image which is padded for use in training/classifying within a neural network. Note: this images pads
    the images expecting that the size of sub-images created from this images will be 416x416 pixels.

    Args:
        raw_dir: Directory where raw .tif files downloaded from Planet are located
        output_dir: The name of the directory where the padded .png files will be created.
        file_name: The name of the .tif file that is to be padded.

    Returns:
        None
    """
    rawImageDirectory = os.path.join(os.getcwd(), raw_dir)
    os.makedirs(output_dir, exist_ok=True)
    PNGpath = output_dir

    # Set the options for the gdal.Translate() call
    opsString2 = "-ot UInt16 -of png -b 3 -b 2 -b 1 -scale_1 0 2048 0 65535 -scale_2 0 2048 0 65535 -scale_3 0 2048 0 " \
                 "65535"
    # Translate original from tif into png
    gdal.Translate(os.path.join(PNGpath,f"colorCorrected{file_name.split('.')[0]}.png"),
                   os.path.join(rawImageDirectory, file_name),
                   options=opsString2)

    # Open the new color corrected PNG we have just made.
    colorImagePath = os.path.join(PNGpath, f"colorCorrected{file_name.split('.')[0]}.png")
    colourImage = PIL.Image.open(colorImagePath)

    # Get new width and height in preparation of paddingthe image
    width, height = colourImage.size

    # Calculate required padding to make image divisible by 416
    subImageSize = tile_size
    overlapAmount = stride

    # Calculate vertical and horizontal padding
    pad = subImageSize - overlapAmount
    widthPadding = (math.ceil(width / stride) * stride) - width
    heightPadding = (math.ceil(height / stride) * stride) - height

    # Calculate individual padding for each edge
    leftPad = math.floor(widthPadding / 2)
    rightPad = math.ceil(widthPadding / 2)
    topPad = math.floor(heightPadding / 2)
    bottomPad = math.ceil(heightPadding / 2)

    # Pad the edges (add_margin is a function in imageCuttingSupport.py that adds a margin to an opened PIL image.)
    im_new = add_margin(colourImage, pad + leftPad, pad + rightPad, pad + topPad, pad + bottomPad, (0, 0, 0))

    # Save the padded image which is now ready for classification
    if rename != False and type(rename) == str:
        savePath = os.path.join(PNGpath, rename + ".png")
    else:
        savePath = os.path.join(PNGpath, file_name.split('.')[0]+ ".png")
    im_new.save(savePath, quality=100, compress_level=0)

    # Close loose file descriptors
    colourImage.close()
    im_new.close()

    # Cleanup any images that aren't the image that is used for classification
    for filename in os.listdir(PNGpath):
        if filename[0:5] == "color":
            os.remove(os.path.join(PNGpath, filename))

def create_unpadded_png(raw_dir, output_dir, file_name):
    """
    Creates an image which is NOT padded but converts raw .tif to .png files.

    Args:
        raw_dir: Directory where raw .tif files downloaded from Planet are located
        output_dir: The name of the directory where the padded .png files will be created.
        file_name: The name of the .tif file that is to be padded.

    Returns:
        None
    """
    rawImageDirectory = os.path.join(os.getcwd(), raw_dir)
    PNGpath = output_dir

    # Set the options for the gdal.Translate() call
    opsString2 = "-ot UInt16 -of png -b 3 -b 2 -b 1 -scale_1 0 2048 0 65535 -scale_2 0 2048 0 65535 -scale_3 0 2048 0 " \
                 "65535"
    # Translate original from tif into png
    gdal.Translate(os.path.join(PNGpath, file_name.split('.')[0] + ".png"),
                   os.path.join(rawImageDirectory, file_name),
                   options=opsString2)

def get_required_padding(filepath, tilesize=416, stride=104):
    """
    Determines how much padding is required on each edge of an image so that the image lengths and widths will be
    divisible by 416 and that each part of the images will be seen by the neural networm 16 times in either training
    or classification.

    Args:
        filepath: The path of the file to evaluate.
    
    Returns:
        (L, R, T, B) - A tuple containing the padding required on the left (L), right (R), top (T), and bottom (b)
            of the images to make it suitable for use in the neural network.
    """
    ds = gdal.Open(filepath)

    metadata = gdal.Info(ds)
    ds = None
    metadata_components = metadata.split("\n")

    # Get new width and height in preparation of paddingthe image
    height = int(metadata_components[2].split(',')[1])
    width = int(metadata_components[2].split(',')[0].split(' ')[2])

    # Calculate individual padding for each edge
    pad = tilesize - stride
    widthPadding = (math.ceil(width / stride) * stride) - width
    heightPadding = (math.ceil(height / stride) * stride) - height

    leftPad = math.floor(widthPadding / 2)
    rightPad = math.ceil(widthPadding / 2)
    topPad = math.floor(heightPadding / 2)
    bottomPad = math.ceil(heightPadding / 2)
    return leftPad + pad, rightPad + pad, topPad + pad, bottomPad + pad

def get_crs(filepath: str) -> int:
    """
    Get the EPSG code of the coordinate reference system of a .tif file.

    Args:
        filepath: The path of the file to evaluate.

    Returns:
        The EPSG code of the coordinate reference system of the .tif file.
    """
    ds = gdal.Open(filepath)
    metadata = gdal.Info(ds, format='json')
    ds = None
    try:
        crs = metadata['stac']['proj:projjson']['id']['code']
        return crs
    except:
        raise Exception("The coordinate reference system does not exist in the metadata")

def pixel2coord(x: int, y:int, original_image_path: str) -> tuple[float, float]:
    """
    Returns global coordinates to pixel center using base-0 raster index

    Args:
        x: The x coordinate (pixel coordinates) of the object in the image to be converted to global coordinates.
        y: The y coordinate (pixel coordinates) of the object in the image to be converted to global coordinates.
        original_image_path: The path of the file to evaluate - a .tif files should be located here. This file will
            also need geospatial metadata. Images obtained from Planet have the required metadata.
e
    Returns:
        (xp, yp) - A tuple containing the global coordinates of the provided pixel coordinates.
    """
    ds = gdal.Open(original_image_path)
    c, a, b, f, d, e = ds.GetGeoTransform()
    xp = a * x + b * y + a * 0.5 + b * 0.5 + c
    yp = d * x + e * y + d * 0.5 + e * 0.5 + f
    return(xp, yp)

def coord2pixel(x: float, y: float, original_image_path: str) -> tuple[int, int]:
    """
    Returns pixel coordinates to pixel center using base-0 raster index

    Args:
        x: The x coordinate (global coordinates) of the object in the image to be converted to pixel coordinates.
        y: The y coordinate (global coordinates) of the object in the image to be converted to pixel coordinates.
        original_image_path: The path of the file to evaluate - a .tif files should be located here. This file will
            also need geospatial metadata. Images obtained from Planet have the required metadata.

    Returns:
        (xp, yp) - A tuple containing the pixel coordinates of the provided global coordinates.
    """
    ds = gdal.Open(original_image_path)
    c, a, b, f, d, e = ds.GetGeoTransform()
    xp =  (x - b*y - a * 0.5 - b * 0.5 - c) / a
    yp =  (y - d*x - d * 0.5 - e * 0.5 - f) / e
    return(xp, yp)

def coord2latlong(x: float, y: float, crs: int=32756) -> tuple[float, float]:
    """
    Converts global coordinates to latitude/longitude coordinates

    Args:
        x: The x coordinate in a pair of global coordinates.
        y: The y coordinate in a pair of global coordinates.

    Returns:
        (long, lat) - A tuple containing the longitude and latitude at the provided global coordinates.
    """
    proj = pyproj.Transformer.from_crs(crs, 4326, always_xy=True)
    long, lat = proj.transform(x, y)
    return long, lat

def latlong2coord(lat: float, long: float, crs: int=32756) -> tuple[float, float]:
    """
    Converts latitude/longitude coordinates to global coordinates
    
    Args:
        long: The longitude coordinate in a pair of latitude/longitude coordinates.
        lat: The latitude coordinate in a pair of latitude/longitude coordinates.

    Returns:
        (x, y) - A tuple containing the global coordinates at the provided latitude/longitude coordinates.
    """
    proj = pyproj.Transformer.from_crs(4326, crs)
    x, y = proj.transform(long, lat)
    return x, y

def get_date_from_filename(filename: str):
    """
    Get the date from a file. The file must have a date in the format "yyyymmdd_" at the start of the filename .
first 
    Args:
        filename: The name of the file to extract the date from.

    Returns:
        The date in the format "dd/mm/yyyy" from the filename.
    """
    str_date = filename.split("_")[0]
    if len(str_date) != 8:
        return None
    year = str_date[0:4]
    month = str_date[4:6]
    day = str_date[6:8]
    return f"{day}/{month}/{year}"

def get_cartesian_top_left(metadata_components: list[str]) -> tuple[float, float]:
    """
    Calculates the lat long at the top left point of a given satellite image

    Args:
        metadata_components: The metadata components stripped from a .tif file

    Returns: 
        (long, lat) - A tuple containing the longitude and latitude at the top left point of the satellite image.
    """
    for component in metadata_components:
        if len(component) > 20 and component[0:10] == "Upper Left":
            longdms, latdms = component.split("(")[-1][0:-1].split(", ")
            longd = longdms.split("d")[0]
            longm = longdms.split("d")[1].split("'")[0]
            longs = longdms.split("\"")[0].split("'")[1]
            longdirec = longdms.split("\"")[1]
            latd = latdms.split("d")[0]
            latm = latdms.split("d")[1].split("'")[0]
            lats = latdms.split("\"")[0].split("'")[1]
            latdirec = latdms.split("\"")[1]
            long = ((int(longd) * 60 * 60) + (int(longm) * 60) + float(longs)) / (60 * 60)
            lat = ((int(latd) * 60 * 60) + (int(latm) * 60) + float(lats)) / (60 * 60)
            if longdirec == 'S':
                long = long * -1
            if latdirec == 'W':
                lat = lat * -1
            return long, lat
        else:
            pass
    raise Exception("The top left corner coordinates do not exist in the metadata")


def get_cartesian_top_right(metadata_components):
    """
    Calculates the lat long at the top right point of a given satellite image
    :param metadata_components: The metadata components stripped from a .tif file
    :return: (long, lat) - A tuple containing the longitude and latitude at the top right point of the satellite image.
    """
    for component in metadata_components:
        if len(component) > 20 and component[0:11] == "Upper Right":
            longdms, latdms = component.split("(")[-1][0:-1].split(", ")
            longd = longdms.split("d")[0]
            longm = longdms.split("d")[1].split("'")[0]
            longs = longdms.split("\"")[0].split("'")[1]
            longdirec = longdms.split("\"")[1]
            latd = latdms.split("d")[0]
            latm = latdms.split("d")[1].split("'")[0]
            lats = latdms.split("\"")[0].split("'")[1]
            latdirec = latdms.split("\"")[1]
            long = ((int(longd) * 60 * 60) + (int(longm) * 60) + float(longs)) / (60 * 60)
            lat = ((int(latd) * 60 * 60) + (int(latm) * 60) + float(lats)) / (60 * 60)
            if longdirec == 'S':
                long = long * -1
            if latdirec == 'W':
                lat = lat * -1
            return long, lat
        else:
            pass
    raise Exception("The top right corner coordinates do not exist in the metadata")


def get_cartesian_bottom_left(metadata_components: list[str]) -> tuple[float, float]:
    """
    Calculates the lat long at the bottom left point of a given satellite image

    Args:
        metadata_components: The metadata components stripped from a .tif file

    Returns: 
        (long, lat) - A tuple containing the longitude and latitude at the bottom left point of the satellite image
    """
    for component in metadata_components:
        if len(component) > 20 and component[0:10] == "Lower Left":
            longdms, latdms = component.split("(")[-1][0:-1].split(", ")
            longd = longdms.split("d")[0]
            longm = longdms.split("d")[1].split("'")[0]
            longs = longdms.split("\"")[0].split("'")[1]
            longdirec = longdms.split("\"")[1]
            latd = latdms.split("d")[0]
            latm = latdms.split("d")[1].split("'")[0]
            lats = latdms.split("\"")[0].split("'")[1]
            latdirec = latdms.split("\"")[1]
            long = ((int(longd) * 60 * 60) + (int(longm) * 60) + float(longs)) / (60 * 60)
            lat = ((int(latd) * 60 * 60) + (int(latm) * 60) + float(lats)) / (60 * 60)
            if longdirec == 'S':
                long = long * -1
            if latdirec == 'W':
                lat = lat * -1
            return long, lat
        else:
            pass
    raise Exception("The bottom left corner coordinates do not exist in the metadata")

def get_cartesian_bottom_right(metadata_components: list[str]) -> tuple[float, float]:
    """
    Calculates the lat long at the bottom right point of a given satellite image

    Args:
        metadata_components: The metadata components stripped from a .tif file

    Returns:
        (long, lat) - A tuple containing the longitude and latitude at the bottom right point of the
            satellite image.
    """
    for component in metadata_components:
        if len(component) > 20 and component[0:11] == "Lower Right":
            longdms, latdms = component.split("(")[-1][0:-1].split(", ")
            longd = longdms.split("d")[0]
            longm = longdms.split("d")[1].split("'")[0]
            longs = longdms.split("\"")[0].split("'")[1]
            longdirec = longdms.split("\"")[1]
            latd = latdms.split("d")[0]
            latm = latdms.split("d")[1].split("'")[0]
            lats = latdms.split("\"")[0].split("'")[1]
            latdirec = latdms.split("\"")[1]
            long = ((int(longd) * 60 * 60) + (int(longm) * 60) + float(longs)) / (60 * 60)
            lat = ((int(latd) * 60 * 60) + (int(latm) * 60) + float(lats)) / (60 * 60)
            if longdirec == 'S':
                long = long * -1
            if latdirec == 'W':
                lat = lat * -1
            return long, lat
        else:
            pass
    raise Exception("The bottom right corner coordinates do not exist in the metadata")


def metadata_get_w_h(metadata_components: list[str]) -> tuple[int, int]:
    """
    Obtains the width and height of a given satellite image

    Args:
        metadata_components: The metadata components stripped from a .tif file

    Returns: 
        (width, height) - A tuple containing the width and height of a given satellite image.
    """
    for component in metadata_components:
        if component[0:4] == "Size":
            width = int(component.split(" ")[2].split(",")[0])
            height = int(component.split(" ")[3])
            return width, height
