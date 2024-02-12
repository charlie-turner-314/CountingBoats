import requests
import os
import yaml
import json
from dotenv import load_dotenv
from . import area_coverage
import zipfile
load_dotenv()

# api key is either set in the environment variable or config.yml
config = yaml.load(open('config.yml', 'r'), Loader=yaml.FullLoader)
API_KEY = os.environ.get('PLANET_API_KEY', config['planet']['api_key'])
if API_KEY is None or API_KEY == 'ENV':
    raise Exception('Planet API key not found in environment variable or config.yml')

def PlanetSearch(
        polygon_file:str,
        min_date:str,
        max_date:str,
        cloud_cover:float=0.1,
        ):
    """
    Search a given area of interest for Planet imagery
    :param search_path: path to a json file containing search body
    :requires: Planet API key be set in environment variable
    :return: a list of Planet items (json result from API)
    """
    # get the polygon
    polygon = None
    with open(polygon_file, 'r') as f:
        polygon = json.load(f)
    # Get the format-string json file as text
    search_body = SEARCH_BODY.replace('MIN_DATE', min_date)
    search_body = search_body.replace('MAX_DATE', max_date)
    search_body = search_body.replace('CLOUD_COVER', str(cloud_cover))
    search_body = search_body.replace('POLYGON', json.dumps(polygon))
    # parse as json
    headers = {'content-type': 'application/json'}
    auth = (API_KEY, '')
    response = requests.post('https://api.planet.com/data/v1/quick-search',
                                data=search_body, headers=headers, auth=auth)
    if response.status_code != 200:
        print(response.text)
        raise Exception('Planet API returned non-200 status code')
    return response.json()['features']

def PlanetSelect(items:list, polygon:str, date:str|None=None, area_coverage:float=0.9):
    """
    Select a subset of items from a search result
    :param items: the list of items to select from
    :param polygon: the area of interest to check coverage against (polygon file)
    :param date: the date to select
    :param area_coverage: the minimum area coverage to select
    :return: list of selected items
    """
    selected = None
    if date is None:
        coverage = 0
        offset = 1
        while coverage <= area_coverage:
            try:
                items.sort(key=lambda x: x['properties']['acquired'])
                selected = [item for item in items if item['properties']['acquired'] == items[-offset]['properties']['acquired']]
                offset += len(selected)
                # check the area coverage
                coverage = items_area_coverage(selected, polygon)
            except Exception as e:
                print(e)
                selected = None
                break
    else:
        selected = [item for item in items if date in item['properties']['acquired']]
        # check the area coverage
        coverage = items_area_coverage(selected, polygon)
        if coverage < area_coverage:
            selected = None
    return selected


def PlanetOrder(items:list, polygon_file:str, name:str):
    """
    Order a given search result.
    :param itemIDs: a list of item IDs to order
    :param polygon_file: a geojson file containing the area of interest to clip to
        must be of format: {"type": "Polygon", "coordinates": [[[lon, lat], ...]]}
    :param name: the name of the order
    :requires: Planet API key be set in environment variable
    :return: a list of order IDs
    """
    pids = [item['id'] for item in items]
    products = [{
        "item_ids": pids,
        "item_type": "PSScene",
        "product_bundle": "analytic_sr_udm2"
        }]
    # get the polygon
    polygon = None
    with open(polygon_file, 'r') as f:
        polygon = json.load(f)
    # create the order body
    order_body = {
        "name": name,
        "products": products,
        "tools": [
            {
                "clip": {
                    "aoi": polygon
                },
            },
            {
                "harmonize": {
                    "target_sensor": "Sentinel-2"
                },
            },
            {
                "composite": {}
            }
        ],
        "notifications": {
            "email": False
            },
        "metadata": {
            "stac": {}
        },
        "order_type": "partial",
        "delivery": {
            "archive_filename": "planet_image_api",
            "archive_type": "zip",
            "single_archive": True,
        }
    }
    # set the headers
    headers = {'content-type': 'application/json'}
    # make the request
    response = requests.post('https://api.planet.com/compute/ops/orders/v2',
                                data=json.dumps(order_body), headers=headers, auth=(API_KEY, ''))
    # return that
    return response.json()



def PlanetCheckOrder(orderID:str):
    """
    Check the status of a given order
    :param orderID: the order ID to check
    :requires: Planet API key be set in environment variable
    :return: the status of the order
    """
    uri = f"https://api.planet.com/compute/ops/orders/v2/{orderID}"
    response = requests.get(uri, auth=(API_KEY, ''))
    return response.json()['state']


def PlanetDownload(orderID:str):
    """
    Download a given order and move the tif file to the raw tiffs directory
    """
    uri = f"https://api.planet.com/compute/ops/orders/v2/{orderID}"
    response = requests.get(uri, auth=(API_KEY, ''))
    if response.status_code != 200:
        raise Exception('Planet API returned non-200 status code')
    # grab the location uri
    links = response.json()['_links']['results']
    download_link = [link['location'] for link in links if "manifest" not in link['name']][0]
    # make the directory if it doesn't exist
    downloadPath = os.path.join(os.getcwd(), "tempDL")
    downloadFile = os.path.join(downloadPath, "DLZip.zip")
    os.makedirs(downloadPath, exist_ok=True)
    # clear the directory
    for f in os.listdir(downloadPath):
        os.remove(os.path.join(downloadPath, f))
    # download the file
    progress = 0
    with requests.get(download_link, stream=True) as r:
        with open(downloadFile, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                if chunk:
                    f.write(chunk)
                    progress += len(chunk)
                    print(f"{orderID} \t Downloaded {progress} bytes", end='\r') 
    print()
    # unzip the file
    with zipfile.ZipFile(downloadFile, 'r') as zip_ref:
        zip_ref.extractall(downloadPath)
    # delete the zip file
    os.remove(downloadFile)
    # move the tif file to the raw tiffs directory
    newfname = ['_'.join(f.split('_')[:-2]) for f in os.listdir(downloadPath) if f.endswith('.xml')][0]
    tif = [f for f in os.listdir(downloadPath) if f == "composite.tif"][0]
    os.rename(os.path.join(downloadPath, tif), 
              os.path.join(config['tif_dir'], newfname + '.tif' ))
    # also move the composite_metadata.json file:
    os.rename(os.path.join(downloadPath, 'composite_metadata.json'),
              os.path.join(config['tif_dir'], newfname + '_metadata.json'))
    return downloadPath

def get_orders():
    """
    Get all orders from the Planet API
    """
    uri = f"https://api.planet.com/compute/ops/orders/v2"
    response = requests.get(uri, auth=(API_KEY, ''))
    # write the response to a file
    with open('orders.json', 'w') as f:
        f.write(response.text)
    return response.json()['orders']

def get_aois():
    """
    Get all the areas of interest
    """
    return [f.split('.')[0] for f in os.listdir(config['planet']['polygons']) if f.endswith('json')]

def get_polygon(aoi):
    """
    Get the polygon for a given area of interest
    """
    files = os.listdir(config['planet']['polygons'])
    file = [f for f in files if f.split('.')[0] == aoi][0]
    return os.path.join(config['planet']['polygons'], file)

def items_area_coverage(items, AOI):
    """
    Given all the items for a particular day, and a polygon, compute the area coverage
    """
    item_polys = [item['geometry'] for item in items]
    # combine the polygons
    combined = area_coverage.combine_polygons(item_polys)
    # get the coverage
    coverage, _ = area_coverage.area_coverage_poly(AOI, combined)
    return coverage


if __name__ == "__main__":
    # prompt for what to do
    print('What would you like to do?')
    print('1. Check Order')
    print('2. Download')
    choice = input('Enter a number: ')
    if choice == '1':
        orderID = input('Enter the order ID: ')
        state = PlanetCheckOrder(orderID)
        print(f'Order {orderID} is {state}')
    elif choice == '2':
        orderID = input('Enter the order ID: ')
        downloadPath = input('Enter the path to download to: ')
        PlanetDownload(orderID)
    else:
        print('Not implemented yet')


SEARCH_BODY = """
        {
    "filter": {
        "type": "AndFilter",
        "config": [
            {
                "type": "GeometryFilter",
                "field_name": "geometry",
                "config": POLYGON
            },
            {
                "type": "OrFilter",
                "config": [
                    {
                        "type": "DateRangeFilter",
                        "field_name": "acquired",
                        "config": {
                            "gte": "MIN_DATET00:00:00.000Z",
                            "lte": "MAX_DATET23:59:59.999Z"
                        }
                    }
                ]
            },
            {
                "type": "OrFilter",
                "config": [
                    {
                        "type": "AndFilter",
                        "config": [
                            {
                                "type": "AndFilter",
                                "config": [
                                    {
                                        "type": "StringInFilter",
                                        "field_name": "item_type",
                                        "config": [
                                            "PSScene"
                                        ]
                                    },
                                    {
                                        "type": "AndFilter",
                                        "config": [
                                            {
                                                "type": "AssetFilter",
                                                "config": [
                                                    "basic_analytic_4b"
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "type": "RangeFilter",
                                "config": {
                                    "gte": 0,
                                    "lte": CLOUD_COVER
                                },
                                "field_name": "cloud_cover"
                            },
                            {
                                "type": "StringInFilter",
                                "field_name": "publishing_stage",
                                "config": [
                                    "standard",
                                    "finalized"
                                ]
                            }
                        ]
                    },
                    {
                        "type": "AndFilter",
                        "config": [
                            {
                                "type": "StringInFilter",
                                "field_name": "item_type",
                                "config": [
                                    "SkySatCollect"
                                ]
                            },
                            {
                                "type": "RangeFilter",
                                "config": {
                                    "gte": 0,
                                    "lte": CLOUD_COVER
                                },
                                "field_name": "cloud_cover"
                            }
                        ]
                    }
                ]
            },
            {
                "type": "PermissionFilter",
                "config": [
                    "assets:download"
                ]
            }
        ]
    },
    "item_types": [
        "PSScene",
        "SkySatCollect"
    ]
}
"""