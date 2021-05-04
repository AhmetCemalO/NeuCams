import sys
from os import path, makedirs
from datetime import datetime
import json
import time

def display(msg):
    sys.stdout.write('['+datetime.today().strftime('%y-%m-%d %H:%M:%S')+'] - ' + msg + '\n')
    sys.stdout.flush()

DEFAULT_SERVER_PARAMS = {
                         'server': 'udp',
                         'server_refresh_time':30, #ms
                         'server_port':9999
                         }
                      
DEFAULT_RECORDER_PARAMS = {
                            'recorder' : 'opencv',
                            'data_folder': 'C:\\Users\\User\\data',
                            'experiment_folder': 'EXP_TEST',
                            'frames_per_file': 256,
                            'compress': 0
                          }

DEFAULT_CAM_INFOS = [
                     {'description':'facecam',
                      'name':'Mako G-030B',
                      'driver':'avt',
                      'params': {'gain':10,
                                 'frameRate':31.,
                                 'TriggerSource':'Line1',
                                 'TriggerMode':'LevelHigh',
                                 'NBackgroundFrames':1.}},
                     {'description':'1photon',
                      'name':'qcam',
                      'id':0,
                      'driver':'QImaging',
                      'params': {'gain':1500,
                                 'triggerType':1,
                                 'binning':2,
                                 'exposure':100000,
                                 'frameRate':0.1}},
                     {'description':'webcam',
                      'name':'webcam',
                      'id':0,
                      'driver':'OpenCV'
                      },
                     {'description':'1photon-2',
                      'name':'pco.edge',
                      'id':0,
                      'driver':'pco',
                      'params': {'triggerType':0,
                                 'exposure':33},
                      'recorder_params': {'recorder' : 'binary'}}
                      ]

def get_default_folder():
    return path.join(path.expanduser('~'), 'labcams')

def get_default_preferences():
    return {'cams': DEFAULT_CAM_INFOS, 'recorder_params': DEFAULT_RECORDER_PARAMS, 'server_params' : DEFAULT_SERVER_PARAMS}
    
def write_template_to_file(filepath):
    display('Creating editable template.')
    dir_path = path.dirname(filepath)
    if not path.isdir(dir_path):
        makedirs(dir_path)
    with open(filepath, 'w') as outfile:
        json.dump(get_default_preferences(), outfile, sort_keys = True, indent = 4)
    display('Saved editable template to: ' + filepath)

def get_preferences(filepath = None, create_template = True):
    """
    
    """
    filepath = path.join(get_default_folder(),'default.json') if filepath is None else filepath
    pref = {}
    if path.isfile(filepath):
        with open(filepath, 'r') as infile:
            pref = json.load(infile)
        pref['user_config_path'] = filepath
        check_preferences(pref)
        return True, pref
    else:
        if create_template:
            write_template_to_file(filepath)
            print('\n\tPlease close the GUI, edit the template, then relaunch.\n', flush=True)
        return False, pref

def check_preferences(pref): #TODO check for required fields
    cams = pref.get("cams", [])
    descriptions = []
    for cam in cams:
        if "description" in cam:
            description =  cam["description"]
            if description in descriptions:
                print(f"ERROR: descriptions have to be unique in your labcams config file at {pref['user_config_path']}. Those are used to determine the recorder subfolders.", flush = True)
                sys.exit(0)
            descriptions.append(description)