# Rest of the code...
import numpy as np
import os
import os.path as path
import scipy.cluster
import scipy.spatial
import utils.image_cutting_support as ics
from utils.config import cfg

"""
Intended usage:
    Processes the outputs
    Saves the results to a csv file. 

Usage: python classifier.py -d <.tif directory> -o <output file name>
"""

TEMP = os.path.join(os.getcwd(), "Boat_Temp")
""" Temporary directory for storing images """

TEMP_PNG = os.path.join(os.getcwd(), "Boat_Temp_PNG")
""" Temporary directory for storing png version of tif images """

TILE_SIZE = cfg['TILE_SIZE']
STRIDE = cfg['STRIDE']

def main():
    """
    Run the classifier on each image in the directory given in the configuration.
    Return the name of each directory which is successfully processed.
    @require cfg: The configuration file
    """
    classify_directory(cfg["tif_dir"])
    remove(TEMP)
    remove(TEMP_PNG)



def process_tif(
        file: str, 
        stat_cutoff: int, 
        moving_cutoff: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Processes a single tif file

    Args:
        file: The tif file to process
        img_path: The path to the directory to store the data in
        stat_cutoff: The cutoff for static boats (pixels)
        moving_cutoff: The cutoff for moving boats (pixels)

    Returns:
        A tuple of the static boats and moving boats
        With boats as a list of: [x, y, filename]
    """
    classifications, _ = detect_from_tif(file, cfg["tif_dir"], 
                                         cfg["yolo_dir"], cfg["python"], 
                                         cfg["weights"], 
                                         cfg["CONFIDENCE_THRESHOLD"])
    if len(classifications) == 0:
        return np.array([]), np.array([])
    # split into moving and static boats
    static = classifications[classifications[:, 3].astype(float) == 0]
    moving = classifications[classifications[:, 3].astype(float) == 1]
    # cluster each set separately
    static_clusters = cluster(static, stat_cutoff)
    moving_clusters = cluster(moving, moving_cutoff)
    # process each set separately
    static_boats = process_clusters(static_clusters)
    moving_boats = process_clusters(moving_clusters)
    # convert pixel coordinates to lat/long
    # tif file should have coord details
    static_boats = pixel2latlong(static_boats, os.path.join(cfg["tif_dir"], file))
    moving_boats = pixel2latlong(moving_boats, os.path.join(cfg["tif_dir"], file))
    # add the image name to each classification (as the last column)
    static_boats = np.c_[static_boats, [file] * len(static_boats)]
    moving_boats = np.c_[moving_boats, [file] * len(moving_boats)]
    # move the tif into the processed folder
    os.makedirs(path.join(cfg["tif_dir"], "processed"), exist_ok=True)
    os.rename(path.join(cfg["tif_dir"], file), path.join(cfg["tif_dir"], "processed", file))
    return static_boats, moving_boats

def process_day(
        files: list[str], 
        stat_cutoff: int, 
        moving_cutoff: int, 
        day: str, 
        i: int, 
        n_days: int) -> tuple[np.ndarray, np.ndarray, str]:
    """
    Process a day's images. Runs process_tif for each of the given files, 
    and then clusters and processes the results.

    Args:
        files: The files to process
        img_path: The path to the directory to store the data in
        stat_cutoff: The cutoff for static boats (pixels)
        moving_cutoff: The cutoff for moving boats (pixels)
        day: The day to process
        i: The index of the day
        n_days: The total number of days
    
    Returns:
        A tuple of the static boats, moving boats, and the day
        With boats as a list of: [x, y, confidence, class, width, height, filename]
    """
    print(f"Classifying day {i+1} of {n_days} - {day} ({i/n_days*100:.2f}%)")

    all_static_boats, all_moving_boats = zip(*[process_tif(file, 
                                                           stat_cutoff,
                                                           moving_cutoff)
                                               for file in files])
    all_static_boats = all_static_boats[0]
    all_moving_boats = all_moving_boats[0]
    # once a day has been classified, need to cluster again
    static_boats = cluster(np.array(all_static_boats), 
                           cfg["STAT_DISTANCE_CUTOFF_LATLONG"])
    moving_boats = cluster(np.array(all_moving_boats), 
                           cfg["MOVING_DISTANCE_CUTOFF_LATLONG"])
    # process again
    static_boats = process_clusters(static_boats)
    moving_boats = process_clusters(moving_boats)
    return (static_boats, moving_boats, day)

def classify_directory(directory):
    """
    Use for directory of tiff images. Preprocesses, classifies, clusters.
    Writes the results to a csv file called boat_detections.csv in the output directory

    Args:
        directory: The directory to classify
    
    Returns:
        None
    """
    days = {ics.get_date_from_filename(file) for file in os.listdir(directory)}
    days.discard(None)
    allFiles = os.listdir(directory)
    # list of files, and the day they belong to
    daily_data = (( [file for file in allFiles 
                    if ics.get_date_from_filename(file) == day], day) 
                  for day in days)
    daily_results = (process_day(files, 
                                 cfg["STAT_DISTANCE_CUTOFF_PIX"], 
                                 cfg["MOVING_DISTANCE_CUTOFF_PIX"], 
                                 day, i, len(days)) 
                     for i, (files, day) in enumerate(daily_data))
    # write to csv
    for static_boats, moving_boats, day in daily_results:
        write_to_csv(static_boats, day, "boat_detections")
        write_to_csv(moving_boats, day, "boat_detections")

def classify_images(images_dir, STAT_DISTANCE_CUTOFF_PIX, OUTFILE):
    """
    Use when images are already split into tiled images.
    Simply runs the classifier and clusters.

    Args:
        images_dir: The directory containing the images
        STAT_DISTANCE_CUTOFF_PIX: The cutoff for static boats (pixels)
        OUTFILE: The output file name

    Returns:
        None
    """
    dirs = [path.join(images_dir, dir) for dir in os.listdir(images_dir)]
    # read a day of images at a time
    for dir in dirs:
        day = path.basename(dir)
        day = "/".join(day.split("_"))
        classifications, _ = detect_from_dir(dir, cfg["yolo_dir"], 
                                             cfg["python"], 
                                             cfg["weights"], 
                                             cfg["CONFIDENCE_THRESHOLD"])
        # cluster
        clusters = cluster(classifications, STAT_DISTANCE_CUTOFF_PIX)
        # process
        boats = process_clusters(clusters)
        # write to csv
        write_to_csv(boats, day, OUTFILE)

def classify_text(dir, STAT_DISTANCE_CUTOFF_PIX, OUTFILE):
    """
    If images have been classified and the text files are available, use this.
    Clusters and collates from yolov5 text files.

    Args:
        dir: The directory containing the text files
        STAT_DISTANCE_CUTOFF_PIX: The cutoff for static boats (pixels)
        OUTFILE: The output file name

    Returns:
        None
    """
    classifications, _ = read_classifications("prerun", class_folder=dir)
    # cluster
    clusters = cluster(classifications, STAT_DISTANCE_CUTOFF_PIX)
    # process
    boats = process_clusters(clusters)
    # write to csv
    write_to_csv(boats, "unknown", OUTFILE)

def prepare_temp_dirs():
    remove(TEMP)
    remove(TEMP_PNG)
    os.mkdir(TEMP) 
    os.mkdir(TEMP_PNG)

def detect_from_tif(file, tif_dir, yolo_dir, python, weights, confidence_threshold)-> tuple[np.ndarray, np.ndarray]:
    """
    Detect from a tif file

    Args:
        file: The tif file to detect from
        tif_dir: The directory containing the tif file
        yolo_dir: The directory containing yolo
        python: The python executable to use
        weights: The weights to use for the NN
        confidence_threshold: The confidence threshold to use where if confidence < threshold, it is considered low confidence

    Returns:
        A tuple of the classifications and low confidence classifications
        With boats as a list of: [x, y, confidence, class, width, height]
    """
    prepare_temp_dirs()
    file_name = path.basename(file)
    ics.create_padded_png(tif_dir, TEMP_PNG, file_name, tile_size=TILE_SIZE, stride=STRIDE)
    png_path = path.join(os.getcwd(), TEMP_PNG, f"{file_name[0:-4]}.png")
    ics.segment_image_for_classification(png_path, TEMP, tile_size=TILE_SIZE, stride=STRIDE)
    detect_path = path.join(yolo_dir, "detect.py")
    os.system(f"{python} {detect_path} --imgsz {TILE_SIZE} --save-txt --save-conf --weights {weights} --source {TEMP}")
    return read_classifications(yolo_dir=yolo_dir, confidence_threshold=confidence_threshold, delete_folder=True)

def detect_from_dir(dir, yolo_dir, python, weights, confidence_threshold) -> tuple[np.ndarray, np.ndarray]:
    """
    Detect from a directory containing images

    Args:
        dir: The directory containing the images
        yolo_dir: The directory containing yolo
        python: The python executable to use
        weights: The weights to use for the NN
        confidence_threshold: The confidence threshold to use where if confidence < threshold, it is considered low confidence

    Returns:
        A tuple of the classifications and low confidence classifications
        With boats as a list of: [x, y, confidence, class, width, height]
    """
    detect_path = path.join(yolo_dir, "detect.py")
    os.system(f"{python} {detect_path} --imgsz {TILE_SIZE} --save-txt --save-conf --weights {weights} --source {dir}")
    return read_classifications(yolo_dir=yolo_dir, confidence_threshold=confidence_threshold)

def classification_file_info(file: str) -> tuple[int, int, list[str]]:
    """
    Get information and data from a small png file
    The file-name is in the format: <.*>_<row>_<col>.txt

    Args:
        file: The file path to get information from

    Returns:
        The across, down, and data from the file
    """
    fname = os.path.basename(file)
    fname= fname.split(".txt")[0].split("_")
    row = int(fname[-2])
    col = int(fname[-1])
    across = col * STRIDE
    down = row * STRIDE
    with open(file) as f:
        lines = [line.rstrip() for line in f]
    return across, down, lines

def parse_classifications(file: str) -> np.ndarray:
    """
    parse a single text file of classifications into the desired format 

    Args:
        file: path to text file
    
    Returns:
        array of classifications from the file in the form:
        x, y, confidence, class, width, height
    """
    across, down, lines = classification_file_info(file)
    if len(lines) == 0:
        return np.array([])

    # split lines into classifications
    classifications = np.array([line.split(" ") for line in lines])
    # if no confidence, add column of 1s (for manual label files)
    if classifications.shape[1] == 5:
        classifications = np.c_[classifications, np.ones(classifications.shape[0])]
    # move columns around
    # from: class, x, y, w, h, conf
    # to:   x, y, conf, class, w, h
    classifications = np.c_[classifications[:, 1], # xMid
                            classifications[:, 2], # yMid
                            classifications[:, 5], # Confidence
                            classifications[:, 0], # Class
                            classifications[:, 3], # xWid
                            classifications[:, 4]] # yWid
    # convert to float
    classifications = classifications.astype(np.float64)
    # adjust x and y for the full image
    classifications[:, 0] = classifications[:, 0] * TILE_SIZE + across
    classifications[:, 1] = classifications[:, 1] * TILE_SIZE + down
    # adjust width and height for the full image
    classifications[:, 4] = classifications[:, 4] * TILE_SIZE
    classifications[:, 5] = classifications[:, 5] * TILE_SIZE
    return classifications

def remove_low_confidence(classifications:np.ndarray, confidence_threshold:float) -> tuple[np.ndarray, np.ndarray]:
    """
    Remove all classifications with confidence < confidence_threshold

    Args:
        classifications: The classifications to remove low confidence from. Confidence is the third column.
        confidence_threshold: The threshold to remove below

    Returns:
        The same classifications as a tuple, with the first element being the high confidence classifications
    """
    low_confidence  = classifications[classifications[:, 2] < confidence_threshold]
    classifications = classifications[classifications[:, 2] >= confidence_threshold]
    return classifications, low_confidence

def read_classifications(yolo_dir=None, class_folder=None, confidence_threshold:float=0.5, delete_folder=False) -> tuple[np.ndarray, np.ndarray]:
    """
    Read classifications from either the given directory, or the latest detection from yolo.
    Classifications are per-image, this function reads all files and returns a single list.

    Args:
        yolo_dir: The directory where yolo is installed, used to find the latest detection.
        class_folder: The folder to read classifications from. If None, reads from the latest detection in yolo.
        confidence_threshold = 0.5: The confidence threshold to use when separating low confidence classifications.
        delete_folder: Whether to delete the classification folder after reading.
    
    Returns:
        tuple[classifications, low_conf]: where each is in the form (x, y, conf, class, w, h)
    """
    latest_exp = None
    if class_folder is None:
        assert yolo_dir is not None, "Must provide yolo_dir if class_folder is not provided"
        # Classifications are stored in the CLASS_PATH directory in the latest exp folder
        exps = [int(f.split("exp")[1]) if f != "exp" else 0 for f in os.listdir(os.path.join(yolo_dir, "runs", "detect" )) if "exp" in f]
        latest_exp = max(exps) if max(exps) != 0 else ""
        classification_path = os.path.join(os.path.join(yolo_dir, "runs", "detect"), f"exp{latest_exp}", "labels")
    else:
        classification_path = os.path.join(class_folder)
    all_cs = [parse_classifications(os.path.join(classification_path, file)) for file in os.listdir(classification_path) if not "DS" in file]
    # remove empty arrays
    all_cs = [cs for cs in all_cs if cs.shape[0] != 0]
    if len(all_cs) == 0:
        return np.array([]), np.array([])
    # flatten list of lists
    all_cs = np.concatenate(all_cs)
    # remove low confidence
    classifications, low_confidence = remove_low_confidence(all_cs, confidence_threshold)
    # remove the classification path
    if delete_folder and latest_exp is not None and yolo_dir is not None:
        folder = os.path.join(yolo_dir, "runs", "detect", f"exp{latest_exp}")
        remove(folder)
    return classifications, low_confidence

def cluster(classifications:np.ndarray, cutoff:float) -> np.ndarray:
    """
    Cluster the given classifications using the given cutoff.

    Args:
        classifications: The classifications to cluster, in the form x, y, ...
        cutoff: The cutoff to use for clustering

    Returns:
        The classifications with an additional column for the cluster number

    """
    if classifications.shape[0] < 2:
        # add cluster = 1 to point
        if classifications.shape[0] == 1:
            classifications = np.array([np.append(classifications[0], 1)])
        return classifications
    points              = classifications[:, [0, 1]].astype(np.float64)
    distances           = scipy.spatial.distance.pdist(points, metric='euclidean')
    clustering          = scipy.cluster.hierarchy.linkage(distances, 'average')
    clusters            = scipy.cluster.hierarchy.fcluster(clustering, cutoff, criterion='distance')
    points_with_cluster = np.c_[classifications, clusters]
    return points_with_cluster

def process_clusters(classifications_with_clusters:np.ndarray) -> np.ndarray:
    """
    Process the given classifications with clusters. Condenses each cluster into a single point.

    Args:
        classifications_with_clusters: The classifications as x, y, confidence, class, width, height, filename, cluster
    
    Return:
        An array of the condensed classifications in the form: x, y, confidence, class, width, height, filenames
    """
    boats = np.array([], dtype=np.float64).reshape(0, 6)
    if len(classifications_with_clusters) == 0:
        return boats
    # as a comprehension:
    boats = [condense(classifications_with_clusters[classifications_with_clusters[:, -1] == i])
             for i in np.unique(classifications_with_clusters[:, -1])]
    return np.asarray(boats)


def condense(cluster:np.ndarray) -> np.ndarray:
    """
    Given a cluster, condense it into a single point.
    Uses the mean of x, y, w, and h - the most common class, and the maximum confidence.

    Args:
        cluster: The cluster to condense

    Returns:
        The condensed cluster in the form x, y, confidence, class, width, height, filenames
    """
    # remove cluster number
    thisBoat = np.asarray(cluster)[:, [0, 1, 2, 3, 4, 5]].astype(np.float64)
    thisBoatMean = np.mean(thisBoat, axis=0)
    # using maximum confidence as the cluster confidence
    maxVals = np.max(thisBoat, axis=0)
    thisBoatMean[2] = maxVals[2]
    # use the most common class
    thisBoatMean[3] = scipy.stats.mode(thisBoat[:, 3])[0]
    if cluster.shape[1] == 8:
        files = np.unique(np.asarray(cluster)[:, 6])
        return np.append(thisBoatMean.astype(str), " ".join(files))
    return thisBoatMean

def write_to_csv(classifications, day, file) -> None:
    """
    Write the given classifications to a csv file.

    Args:
        classifications: The classifications to write
        day: The day the classifications are from
        file: The file to write to

    Returns:
        None
    """
    # Write to output csv
    # Create output csv if it doesn't exist
    file = os.path.join(cfg["output_dir"], file)
    if not os.path.isfile(f"{file}.csv"):
        with open(f"{file}.csv", "a+") as outFile:
            outFile.writelines("date,class,images,latitude,longitude,confidence,w,h\n")

    # Write the data for that day to a csv
    lines = [f"{day},{int(float(boat[3]))},{boat[6]},{boat[1]},{boat[0]},{boat[2]},{boat[4]},{boat[5]}\n" for boat in classifications]
    with open(f"{file}.csv", "a+") as outFile:
        outFile.writelines(lines)

def remove(path: str, del_folder=True) -> None:
    """
    Removes all files in a folder and the folder itself.

    Args:
        path: The path to remove
        del_folder: Whether to remove the folder itself

    Returns: 
        None
    """
    if not os.path.exists(path):
        return
    for file in os.listdir(path):
        file_path = os.path.join(path, file)
        if os.path.isfile(file_path):
            os.remove(file_path)
        elif os.path.isdir(file_path):
            remove(file_path)
    if del_folder:
        os.rmdir(path)

def pixel2latlong(classifications, tif) -> np.ndarray:
    """
    Convert the given classifications from pixel coordinates to lat/long.

    Args: 
        classifications: The classifications to convert, must have x, y as first two columns.
        tif: The tif file these classifications came from.
    
    Returns:
        The same classifications with x, y converted to lat/long
    """
    leftPad, _, topPad, _ = ics.get_required_padding(tif, TILE_SIZE, STRIDE)
    crs = ics.get_crs(tif)
    # get the crs from the tif, e.g EPSG:4326
    for c in classifications:
        x = float(c[0]) - leftPad
        y = float(c[1]) - topPad
        xp, yp = ics.pixel2coord(x, y, tif)
        c[0], c[1] = ics.coord2latlong(xp, yp, crs)
    return classifications

if __name__ == "__main__":
    main()

