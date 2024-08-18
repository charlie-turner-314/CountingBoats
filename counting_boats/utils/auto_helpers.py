"""
This module contains functions which help with the automatic detection pipeline.
"""

import traceback
from utils.config import cfg
import pandas as pd
import os
import datetime
import json
import shutil
from utils import classifier
from utils import planet_utils
from utils import heatmap as hm
from utils import area_coverage as ac
from utils import planet_utils
from utils.image_cutting_support import latlong2coord
import numpy as np
import base64


def get_history(csv_path: str) -> pd.DataFrame:
    """
    Parse and return the csv file at the provided path.
    Creates the file if not exists, with the headings:
    "order_id, AOI, date, order_status, area_coverage, cloud_coverage"

    Args:
        csv_path: path to the csv file

    Returns:
        DataFrame of the csv file, or a new DataFrame with the header if the file does not exist.

    """
    if not os.path.exists(csv_path):
        # write the header line "order_id, AOI, date, order_status, area_coverage, cloud_coverage"
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        open(csv_path, "w").write(
            "order_id,aoi,date,order_status,area_coverage,cloud_coverage\n"
        )
    history = pd.read_csv(csv_path)
    return history


def save_history(history, csv_path):
    history.to_csv(csv_path, index=False)


def search(
    aoi, orders_csv_path, days=14, start_date=None, end_date=None
) -> tuple[list, list]:
    """
    Search for images for a given AOI
    @param aoi: Area of Interest name
    @param orders_csv_path: Path to csv of order history
    @pram days: Number of days to search from
    @param start_date: Start date to search from
    @param end_date: End date to search to
    @return list: list of options
    """
    # First get all the dates that we have for the AOI
    history = get_history(orders_csv_path)
    dates_we_have = history[history["aoi"] == aoi]["date"].unique()
    # If we don't have any, use the default last 14 days
    if start_date is None:
        start_date = datetime.datetime.now() - datetime.timedelta(days=days)
    start_date = start_date.strftime("%Y-%m-%d")
    if end_date is None:
        end_date = datetime.datetime.now()
    end_date = end_date.strftime("%Y-%m-%d")
    # create list of dates between min and max
    daterange = (
        pd.date_range(start=start_date, end=end_date).strftime("%Y-%m-%d").tolist()
    )
    # remove any dates we already have
    dates = [d for d in daterange if d not in dates_we_have]
    # search for images
    polygon = planet_utils.get_polygon_file(aoi)
    if polygon is None:
        print("Could not find polygon file for", aoi)
        exit(1)
    options = []
    try:
        options = planet_utils.PlanetSearch(
            polygon_file=polygon,
            min_date=start_date,
            max_date=end_date,
            cloud_cover=cfg["ALLOWED_CLOUD_COVER"],
        )
    except Exception as e:
        traceback.print_exc()
        print(e)
        return None, None
    # select and order for each date
    if len(options) == 0:
        return None, None
    return options, dates


def select(aoi: str, options: list, dates: list) -> list[list]:
    """
    Select images from the given options that are not in history for the AOI.

    Args:
        aoi: Area of Interest name
        options: list of options
        dates: list of dates that we want to select for

    Returns:
        list of items which
    """
    polygon = planet_utils.get_polygon_file(aoi)
    if polygon is None:
        print("Could not find polygon file for", aoi)
        exit(1)
    # Select images for each date and return them
    items = []
    for date in dates:
        try:
            it = planet_utils.PlanetSelect(
                items=options,
                polygon=polygon,
                date=date,
                area_coverage=cfg["MINIMUM_AREA_COVERAGE"],
            )
        except Exception as e:
            traceback.print_exc()
            print(e)
            continue
        if it is None or len(it) == 0:
            continue
        items.append(it)
    return items


def order(aoi: str, items: list, csv_path: str) -> str:
    """
    Place a Planet order for the given items

    Args:
        aoi: Area of Interest name
        items: list of items to order
        history: DataFrame of the history of orders

    Returns:
        order_id: the ID of the order placed
    """
    polygon = planet_utils.get_polygon_file(aoi)
    if polygon is None:
        print("Could not find polygon file for", aoi)
        exit(1)
    date = items[0]["properties"]["acquired"][:10]
    fs_date = "".join(date.split("-"))  # filesafe date
    try:
        order = planet_utils.PlanetOrder(
            polygon_file=polygon, items=items, name=f"{aoi}_{fs_date}"
        )
    except Exception as e:
        traceback.print_exc()
        print(e)
        return ""
    if "id" not in order:
        print("\033[91mCould not place order for", aoi, date, "\033[0m")
        # json.dump(order, open(f"failed_order_{aoi}_{fs_date}.json", "w"))
        return ""
    order_id = order["id"]
    # add to history
    history = get_history(csv_path)
    history = pd.concat(
        [
            history,
            pd.DataFrame(
                {
                    "order_id": [order_id],
                    "aoi": [aoi],
                    "date": [date],
                    "order_status": ["ordered"],
                    "area_coverage": ["-"],
                    "cloud_coverage": ["-"],
                }
            ),
        ]
    )
    save_history(history, csv_path)
    return order_id


def download(
    csv_path: str, download_path="tempDL", start_date=None, end_date=None
) -> pd.DataFrame:
    """
    Download all completed orders from planet, as per the history csv path
    Places the downloaded files in the download_path.

    Args:
        csv_path: path to the history csv. Will check this to ensure we don't download the same file twice.
        download_path: path to store the downloaded zip files
        download_ids: list of order_ids to download. If None, will attempt download all orders that are in the "ordered" state.

    Returns:
        Remaining orders that haven't been downloaded yet
    """
    history = get_history(csv_path)
    orders = planet_utils.get_orders()
    for order in [o for o in orders if o["state"] == "success"]:
        # check if we have already downloaded (status == downloaded or complete)
        if (
            order["id"]
            in history[history["order_status"].isin(["downloaded", "complete"])][
                "order_id"
            ].tolist()
        ):
            continue
        elif (
            order["id"]
            in history[history["order_status"] == "ordered"]["order_id"].tolist()
        ):
            this_order = history[history["order_id"] == order["id"]].iloc[0]
            if start_date is not None:
                # convert both dates
                start_date = pd.to_datetime(start_date)
                order_date = pd.to_datetime(this_order["date"])
                print(order_date, start_date)
                if order_date < start_date:
                    continue
            if end_date is not None:
                end_date = pd.to_datetime(end_date)
                order_date = pd.to_datetime(this_order["date"])
                print(order_date, end_date)
                if order_date > end_date:
                    continue

            print("Download:: Downloading", order["id"])
            # download
            this_order = history[history["order_id"] == order["id"]].iloc[0]
            try:
                planet_utils.PlanetDownload(
                    order["id"],
                    this_order["aoi"],
                    this_order["date"].replace("-", ""),
                    downloadPath=download_path,
                )
            except Exception as e:
                traceback.print_exc()
                print(e)
                continue
            # update history
            history.loc[history["order_id"] == order["id"], "order_status"] = (
                "downloaded"
            )
            save_history(history, csv_path)
    # return remaining orders
    return history[history["order_status"] == "ordered"]


def extract(download_path):
    """
    Extract any downloaded images we haven't processed.

    Args:
        download_path: path to the downloaded zip files

    Returns:
        None
    """
    for root, dirs, files in os.walk(download_path):
        for f in files:
            if f.endswith(".zip"):
                planet_utils.extract_zip(os.path.join(root, f))


def count(save_coverage=False, days=None) -> None:
    """
    Run the classifier to count boats in the extracted images

    Essentially calls the main function of the classifier module. Most of the time here we will save coverage later.
    """
    classifier.main(save_coverage=save_coverage, days=days)
    # add the aoi column to the classifications and save again
    if os.path.exists(cfg["output_dir"] + "/boat_detections.csv"):
        classifications = pd.read_csv(cfg["output_dir"] + "/boat_detections.csv")
        classifications["aoi"] = classifications["images"].apply(
            lambda im: im.split("_")[1].split(".")[0]
        )
        classifications.to_csv(cfg["output_dir"] + "/boat_detections.csv", index=False)


def save(csv_path) -> None:
    """
    Confirm completion of the process and archive the raw data.
    Saves the csv with everything updated.

    Args:
        csv_path: path to the history csv

    Returns:
        None
    """
    history = get_history(csv_path)
    new = history[history["order_status"] == "downloaded"]
    if len(new) == 0:
        print("Save:: No new orders this run. Exiting.")
    # make a list of new file names (row["date"]_row["aoi"] for each row in new)
    new_files = [
        f"{row['date'].replace('-','')}_{row['aoi']}" for _, row in new.iterrows()
    ]
    # update to complete if file does not exist in rawimages.
    # the classifier will have moved the files if complete
    for new_file in new_files:
        if not os.path.exists(os.path.join("data", "RawImages", new_file)):
            date = new_file[:4] + "-" + new_file[4:6] + "-" + new_file[6:8]
            aoi = "_".join(new_file.split("_")[1:])
            right_aoi = history[history["aoi"] == aoi]
            right_date = right_aoi[right_aoi["date"] == date]
            if len(right_date) == 0:
                print(f"Save:: Could not find {new_file} in history. Skipping.")
                continue
            order_id = right_date["order_id"].iloc[0]
            history.loc[history["order_id"] == order_id, "order_status"] = "complete"
    # save the history
    save_history(history, csv_path)


groups = [
    {"name": "moreton_bay", "aois": ["peel", "tangalooma", "south_bribie", "moreton"]},
    # {"name": "gbr", "aois": ["whitsundays", "keppel", "capricorn", "haymen", "heron"]},
]
""" Groups of AOIs for analysis"""


def analyse(boat_csv_path, coverage_path, start_date=None, end_date=None, id=None):
    """
    do a series of analyses on the data and save it in the output directory

    Args:
        csv_path: path to the history csv
        coverage_path: path to the coverage csv (should be generated when images are archived)
        kwargs: additional arguments to skip or alter steps (look at the code for details)

    Returns:
        None
    """
    #
    all_coverage = pd.read_csv(coverage_path)
    all_coverage["date"] = pd.to_datetime(all_coverage["date"])
    boats = pd.read_csv(boat_csv_path)
    boats["date"] = pd.to_datetime(boats["date"], dayfirst=True)
    # filter by date (day only, inclusive)
    # time doesn't matter
    if start_date is not None:
        start_date = pd.to_datetime(start_date).floor("D")
        coverage = all_coverage[
            (all_coverage["date"] >= start_date) & (all_coverage["date"] <= end_date)
        ]
        boats = boats[(boats["date"] >= start_date) & (boats["date"] <= end_date)]
    if end_date is not None:
        end_date = pd.to_datetime(end_date).ceil("d")
        coverage = all_coverage[
            (all_coverage["date"] >= start_date) & (all_coverage["date"] <= end_date)
        ]
        boats = boats[(boats["date"] >= start_date) & (boats["date"] <= end_date)]

    prefix = f"{id}_" if id is not None else ""

    print("Analysing data from ", start_date, " to ", end_date)

    heatmap_txt = os.path.join(cfg["output_dir"], f"{prefix}heatmap.txt")
    dates = []
    if not os.path.exists(heatmap_txt):
        with open(heatmap_txt, "w") as f:
            f.write("")
    with open(heatmap_txt, "r") as f:
        dates = f.readlines()
    dates = [pd.to_datetime(d.strip()) for d in dates]

    if coverage.empty:
        print("No new coverage data to analyse")
    else:
        # - coverage heatmap raster for each group
        for g in groups:
            print("Making full coverage raster")
            full_heatmap_path = os.path.join(
                cfg["output_dir"], f"{g['name']}_full_coverage.tif"
            )

            if os.path.exists(full_heatmap_path):
                # grab any polygons from dates we don't have
                # all_coverage where date is not in dates
                new_coverage = all_coverage[~all_coverage["date"].isin(dates)]
                polygons = hm.get_polygons_from_df(
                    new_coverage 
                )  
                if len(polygons) == 0:
                    continue
                hm.add_to_heatmap(full_heatmap_path, polygons)
            else:
                new_coverage = all_coverage
                polygons = hm.get_polygons_from_df(
                    all_coverage
                )  # Get the polygons from this batch
                if len(polygons) == 0:
                    continue
                hm.create_heatmap_from_polygons(
                    polygons=polygons,
                    save_file=full_heatmap_path,
                    size=cfg["HEATMAP_SIZE"],
                )
            # save a file heatmap.txt that has the images if they are in the heatmap
            dates = all_coverage["date"].unique()
            print("Saving heatmap.txt")
            with open(heatmap_txt, "w") as f:
                f.write("\n".join([str(d) for d in dates]))


            print("Saved", full_heatmap_path)


def archive(path: str, coverage_path: str):
    """
    Deal with folder of raw data after processing. Send zip files to archive,
    delete the folders, update coverage file.

    Args:
        path: path to the folder of raw data
        coverage_path: path to the coverage csv

    Returns:
        None
    """
    # We want to delete any folders, but keep zip folders
    if not os.path.exists(coverage_path):
        # create it
        open(coverage_path, "w").write(
            "date,aoi,area_coverage,cloud_coverage,polygon,x,y\n"
        )
    coverage = pd.read_csv(coverage_path)
    import shutil

    print("Sending all ZIP files to storage (NOT IMPLEMENTED)")
    archive_dir = "U:\\Research\\Projects\\sef\\livingplayingmb\\Boat Detection TMBF\\PlanetArchive"
    if not os.path.exists(archive_dir):
        raise FileNotFoundError("Archive directory not found")

    for root, dirs, files in os.walk(path):
        for f in files:
            if f.endswith(".zip"):
                # Move to ../archive/{whatever}
                if os.path.exists(os.path.join(archive_dir, f)):
                    print(f"Already have {f} in archive. Skipping.")
                    os.remove(os.path.join(root, f))
                else:
                    shutil.move(os.path.join(root, f), os.path.join(archive_dir, f))
                continue
        for d in dirs:
            # Directories that are unzipped need to have their coverage recorded then deleted (zips still exist)
            # save the polygon to the coverage file
            # load composite_metadata.json from the directory if it exists
            if "composite_metadata.json" in os.listdir(os.path.join(root, d)):
                meta = json.load(open(os.path.join(root, d, "composite_metadata.json")))
                polygon = meta["geometry"]
                aoi = "_".join(d.split("_")[0:-1])
                date = d.split("_")[-1]
                date = date[:4] + "-" + date[4:6] + "-" + date[6:8]
                # check to see if exists in coverage file already
                if (
                    len(coverage[(coverage["date"] == date) & (coverage["aoi"] == aoi)])
                    > 0
                ):
                    print(f"Already have {date}, {aoi} in coverage. Skipping.")
                else:
                    # Get area coverage percentage
                    cov_amount = ac.area_coverage_poly(
                        planet_utils.get_polygon_file(aoi), polygon
                    )
                    # get cloud coverage percentage and polygon from tif UDM.
                    udm_file = os.path.join(root, d, "composite_udm2.tif")
                    if not os.path.exists(udm_file):
                        print(
                            "Could not find UDM file for",
                            d,
                            "Options:",
                            os.listdir(os.path.join(root, d)),
                        )
                        cloud_cover = None
                    else:
                        cloud_cover, _ = ac.cloud_coverage_udm(udm_file)
                        # create the clear tif file
                        # ac.add_udm_clear_to_tif(
                        #     udm_file, os.path.join(cfg["output_dir"], "clear.tif")
                        # )
                        filesafe_date = date.replace("-", "")
                        if not os.path.exists(os.path.join(cfg["output_dir"], "UDM")):
                            os.makedirs(os.path.join(cfg["output_dir"], "UDM"))

                        # save the udm to the output directory
                        shutil.copy(
                            udm_file,
                            os.path.join(
                                cfg["output_dir"],
                                "UDM",
                                f"{aoi}_{filesafe_date}_udm.tif",
                            ),
                        )

                    # add to coverage
                    coverage = pd.concat(
                        [
                            coverage,
                            pd.DataFrame(
                                {
                                    "aoi": [aoi],
                                    "date": [date],
                                    "area_coverage": [cov_amount],
                                    "cloud_coverage": [cloud_cover],
                                    "polygon": [json.dumps(polygon)],
                                }
                            ),
                        ]
                    )
                    # save the coverage
                    coverage.to_csv(coverage_path, index=False)
            shutil.rmtree(os.path.join(root, d))
