import os
import yaml

config_path = os.path.join(os.getcwd(), 'config.yml')

with open(config_path, 'r') as ymlfile:
    cfg = yaml.load(ymlfile, Loader=yaml.FullLoader)
    cfg['tif_dir'] = os.path.join(cfg['proj_root'], 'images', 'RawImages') # This is generated so not included in the config file

