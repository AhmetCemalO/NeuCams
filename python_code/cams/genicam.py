from os import path
import time
import numpy as np
from harvesters.core import Harvester
from .generic_cam import GenericCam
from utils import display

def get_gentl_producer_path():
    gen_tl_producer_path = ''
    dir_path = path.dirname(path.abspath(__file__))
    fname = path.join(dir_path, 'genicam_gen_tl.cfg')
    if path.isfile(fname):
        with open(fname,'r') as f:
            lines = f.readlines()
            for line in lines:
                key, val = line.split('=')
                if key == 'GENTL_PATH':
                    gen_tl_producer_path = val
    return gen_tl_producer_path

def GenI_get_cam_ids(harvester = None):
    manage_harvester = harvester is None
    if manage_harvester:
        harvester = Harvester()
        harvester.add_file(get_gentl_producer_path())
        harvester.update()
    cam_ids = [i for i in range(len(harvester.device_info_list))]
    cam_infos = harvester.device_info_list
    if manage_harvester:
        harvester.reset()
    return cam_ids, cam_infos
        
class GenICam(GenericCam):
    """GeniCam class for GeniCam compliant vision cameras.
    Used for Teledyne Dalsa Genie Nano.
    """
    timeout = 2000
    def __init__(self, cam_id = None, params = None, format = None):
        
        self.h = Harvester()
        
        self.h.add_file(get_gentl_producer_path())
        
        self.h.update()

        if cam_id is None:
            if len(self.h.device_info_list) > 0:
                cam_id = 0

        super().__init__(name = 'GenICam', cam_id = cam_id, params = params, format = format)
        
        default_params = {'exposure':29000, 'frame_rate':30,'gain':8, 'gain_auto': False,
                          'acquisition_mode': 'Continuous', 'n_frames': 1,
                          'triggered': False, # hardware trigger
                          }
                          
        self.exposed_params = ['frame_rate', 'gain', 'exposure', 'gain_auto', 'triggered', 'acquisition_mode', 'n_frames']
        
        self.params = {**default_params, **self.params}

        default_format = {'dtype': np.uint8}
        self.format = {**default_format, **self.format}
    
    def is_connected(self):
        """To be checked before trying to open"""
        ids, devices = GenI_get_cam_ids(self.h)
        if len(devices) == 0:
            display('No GenICam cams detected, check connections.', level='error')
            return False
        display(f'GenICam cams detected: {devices}', level='info')
        if self.cam_id in ids:
            display(f'Requested GenICam cam detected {self.cam_id}.', level='info')
            return True
        display(f'Requested GenICam cam not detected {self.cam_id}, check connections.', level='error')
        return False
        
    def __enter__(self):
        self.cam_handle = self.h.create(self.cam_id)
        self.cam_handle.__enter__()
        self.cam_handle.num_buffers = 2
        self.features = self.cam_handle.remote_device.node_map
        self.apply_params()
        self._record()
        self._init_format()
        return self
        
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.cam_handle.__exit__(exc_type, exc_value, exc_traceback)
        self.close()
    
    def close(self):
        self.h.reset()
        
    def apply_params(self):
        
        resume_recording = self.is_recording
        if self.is_recording:
            self.stop()
        
        params = {'EventNotification' : 'On',
                  'PixelFormat': 'Mono8',
                  'AcquisitionFrameRate': self.params['frame_rate'],
                  'Gain': self.params['gain'],
                  'GainAuto': 'Once' if self.params['gain_auto'] else 'Off',
                  'ExposureTime': self.params['exposure'],
                  'ExposureMode': 'Timed'}
                  
        for key in params:
            try:
                if hasattr(self.features, key):
                    getattr(self.features, key).value = params[key]
            except Exception as e:
                print(f"Could not set param [{key}] to value [{params[key]}], {repr(e)}", flush=True)
        
        if resume_recording:
            self._record()

    def get_features(self):
        features_str = ""
        for feature_name in dir(self.cam_handle.remote_device.node_map):
            try:
                features_str += feature_name + ': ' + getattr(self.cam_handle.remote_device.node_map, feature_name).to_string() + '\n'
            except Exception: #node.AccessException and AttributeError for methods
                pass
        return features_str

    def get_frame_generator(self, n_frames = None, timeout_ms = 0):
        idx = 0
        while (n_frames is None) or idx < n_frames:
            try:
                with self.cam_handle.fetch(timeout = timeout_ms) as buffer:
                    payload = buffer.payload
                    timestamp = buffer.timestamp
                    component = payload.components[0]
                    to_print = component.data.shape
                    _2d = component.data.reshape(component.height, component.width)
                    frame = np.copy(_2d)
            except Exception: # buffer exceptions should not kill the generator
                frame = np.array([])
            yield frame, idx, time.time() - self.t_start
            idx += 1
            
    def _record(self):
        self.cam_handle.start() # it was self.cam_handle.start(run_in_background = True)
        limit = self.params['n_frames'] if self.params['acquisition_mode'] == "MultiFrame" else None
        self.t_start = time.time()
        self.frame_generator = self.get_frame_generator(n_frames = limit, timeout_ms = self.timeout/1000)
        self.is_recording = True
        
    def stop(self):
        self.cam_handle.stop()
        self.is_recording = False
        
    def image(self):
        if self.is_recording:
            try:
                frame, frame_id, time_stamp = next(self.frame_generator)
            except StopIteration:
                return None, "stop"
            except Exception:
                return None, 'error'
            if frame.shape[0] == 0:
                return None, "timeout"
            return frame, (frame_id, time_stamp)
        return None, 'not recording'
      