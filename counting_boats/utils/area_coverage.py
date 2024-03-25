"""
This module provides functions for calculating the coverage of polygons and TIFF files.

The main functions in this module are:
- `area_coverage_tif`: Calculates the intersection of a polygon and a TIFF file, as a percentage of the polygon area.
- `area_coverage_poly`: Computes the intersection of a polygon and a reference polygon, as a percentage of the reference polygon area.
- `combine_polygons`: Combines two or more polygons into one.
- `polygons_to_32756`: Converts a polygon from latitude-longitude coordinates to EPSG:32756 coordinate system.

These functions are useful for analyzing and measuring the coverage of geographic areas by polygons and TIFF files.

Author: Charlie Turner
Date: 18/3/24
"""

import json
import numpy as np
from osgeo import gdal, ogr
import rasterio

from . import image_cutting_support as ics

def area_coverage_tif(polygon, tif):
    """
    Calculate the intersection of a polygon and a tif, as a percentage of the polygon area.
    To be used when calculating the coverage of a tif file for an AOI, after the TIF has already
    been obtained. Assumes the tif is clipped to the polygon (does not check whether the tif is 
    actually inside the polygon, just calculates the areas).
    :param polygon: path to polygon file (geojson format)
    :param tif: path to tif file (from Planet)
    :return: coverage (decimal), area of polygon, area of tif
    """
# Area of polygon:
    poly = polygons_to_32756(polygon)[0]
    area = poly.Area()
# Same idea with the tif. Get the area of the tif
    with rasterio.open(tif) as src:
        array = src.read()
        meta = gdal.Info(tif)
        coords = meta.split("Corner Coordinates")[1].split("\n")[1:5]
        # Each looks like:
        # 'Upper Left  (  523650.000, 6961995.000) (153d14\'21.71"E, 27d27\'55.37"S)'
        # we want just the numbers in the first brackets
        coords = [x.split("(")[1].split(")")[0].split(",") for x in coords]
        # upper left, lower left, upper right, lower right
        coords = [(float(x), float(y)) for x, y in coords]
        real_w = coords[2][0] - coords[0][0]
        real_h = coords[0][1] - coords[1][1]
        # flatten array as average of all bands
        array = np.mean(array, axis=0)
        array[array > 0] = 1
        # get the area of the tif (taking into account the real world size)
        tif_area = np.sum(array) * real_w * real_h / array.shape[0] / array.shape[1]
        coverage = tif_area/area
        return coverage, area, tif_area

def area_coverage_poly(reference, polygon):
    """
    Computes the intersection of a polygon and a reference polygon, as a percentage of the reference polygon area.
    :param reference: path to reference polygon file (geojson format)
    :param polygon: path to polygon file (geojson format)
    :return: coverage (decimal), intersection polygon
    """
    ref_poly = polygons_to_32756(reference)[0]
    poly = polygons_to_32756(polygon)[0]
    # intersection
    intersection = ref_poly.Intersection(poly)
    if intersection is None:
        raise ValueError("Polygons do not intersect")
    # area of intersection
    area = intersection.Area()
    # area of reference polygon
    ref_area = ref_poly.Area()
    # coverage
    coverage = area/ref_area
    return coverage, intersection

def combine_polygons(polygons):
    """
    Combines two or more polygons into one
    :param polygons: list of paths to polygon file (geojson format) or polygon strings
    :return: combined polygon in EPSG:32756
    """
    # convert to ogr polygons
    ogr_polys = [polygons_to_32756(poly)[0] for poly in polygons]
    if len(ogr_polys) == 0:
        print("No polygons to combine")
        print(ogr_polys)
        print(polygons)
        exit()
    # combine
    poly = ogr_polys[0]
    if len(ogr_polys) == 1:
        return poly
    for i in range(1, len(ogr_polys)):
        poly = poly.Union(ogr_polys[i])
    if poly is None:
        raise ValueError("Polygons do not intersect")
    return poly

def polygons_to_32756(polygon:str|dict|ogr.Geometry) -> list[ogr.Geometry]:
    """
    Converts a polygon from lat long to EPSG:32756
    :param polygon: path to polygon file (geojson format) or polygon string
        e.g "{ "type": "Polygon", "coordinates": [...]}"
    :return: polygon in EPSG:32756
    """
    if type(polygon) == ogr.Geometry:
        return [polygon]
    geoJSON:dict = {}
    if type(polygon) != str and type(polygon) != dict:
        raise ValueError("polygons_to_32756: Received polygon of type {}, must be string or dict to convert".format(type(polygon)))
    # check if the polygon is a string or a path
    if type(polygon) == str and polygon[0] == "{": # } <- obligatory bracket to fix linting
        # if string, convert to json
        geoJSON = json.loads(polygon)
    elif type(polygon) == str:
        with open(polygon) as f:
            # read as json
            geoJSON = json.load(f)
    elif type(polygon) == dict:
        geoJSON = polygon
# convert from lat long to EPSG:32756
    if 'geometry' in geoJSON:
        geoJSON = geoJSON['geometry']
    polygons = []
    for i, poly in enumerate(geoJSON['coordinates']):
        if geoJSON['type'] == "MultiPolygon":
            poly = poly[0]
        poly_dict = {
                "coordinates": [[None] * len(poly)],
                "type": "Polygon"
                }
        for i, val in enumerate(poly):
            lat, long = val
            x, y = ics.latlong2coord(lat, long)
            poly_dict['coordinates'][0][i] = [x, y]
        polygons.append(ogr.CreateGeometryFromJson(json.dumps(poly_dict)))
    return polygons











