# Counting Boats

## What

This project counts small marine vessels from satellite imagery of the Moreton Bay
region. The counts are recorded and can be analysed or presented later. Tools for
visualising training and inference data are also available.

## How

This project utilises satellite images, and harnesses machine learning
object detection to count small marine vessels (boats) in the Moreton Bay area.
Extendable to any images from any area, the recommended pipeline runs as follows:

1. Using Planet, satellite images of the area of interest are automatically ordered for recent dates
2. Once the orders are available, imagery is automatically downloaded from planet.
3. A pre-processing pipeline prepares imagery for detection
4. Our YOLOv5 model detects and labels both stationary and moving boats in the images
5. We collate and analyse the boat counts as time-series data, outputting a CSV of detected boats and their coordinates

## Usage

### Installation

#### Yolov5

Clone [YoloV5](https://github.com/ultralytics/yolov5). This is used for the Neural Network detections.

#### Python Dependencies

It's recommended to install a conda-based package manager such as [Miniconda](https://docs.conda.io/projects/miniconda/en/latest/).
Running the following will then install all required dependencies:

```
conda env create --file env.yaml
```

Activate the environment (if not already) with `conda activate Boats`, and you should be good to go.

### Setup

#### Configuration

Set the variables in `config.yaml` to align with your environment and preferences.
Similarly for 'config_train.yaml' or 'config_test.yaml' for training and testing respectively.

### Running

From the root directory, run the following commands:

#### Training

```
python -m counting_boats.train {prepare|segment|train} --config config_train.yaml
```

#### Testing

```
python -m counting_boats.testing --config config_test.yaml
```

By altering `config_test.yaml`, you can change the test data and test tasks that are run.

#### Deployment

```
python counting_boats.classify {auto} --config config_classify.yaml
```

## Acknowledgements
