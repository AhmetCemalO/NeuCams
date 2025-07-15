from os import path
import time
import numpy as np
try:
    from harvesters.core import Harvester
except ImportError:
    Harvester = None
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
    if Harvester is None:
        display('Harvester library not available.', level='error')
        return [], []
    manage_harvester = harvester is None
    if manage_harvester:
        harvester = Harvester()
        harvester.add_file(get_gentl_producer_path())
        harvester.update()
    # Use serial_number as unique ID
    cam_ids = [getattr(dev, 'serial_number', None) for dev in harvester.device_info_list]
    cam_infos = harvester.device_info_list
    if manage_harvester:
        harvester.reset()
    return cam_ids, cam_infos
        
class GenICam(GenericCam):
    timeout = 2000
    def __init__(self, cam_id = None, params = None, format = None):
        if Harvester is None:
            display('Harvester library not available. Cannot open GenICam camera.', level='error')
        self.h = Harvester() if Harvester is not None else None
        if self.h is not None:
            self.h.add_file(get_gentl_producer_path())
            self.h.update()
        if cam_id is None and self.h is not None:
            if len(self.h.device_info_list) > 0:
                # Default to first serial number
                cam_id = getattr(self.h.device_info_list[0], 'serial_number', None)
        super().__init__(name = 'GenICam', cam_id = cam_id, params = params, format = format)
        default_params = {'exposure':29000, 'frame_rate':30,'gain':8, 'gain_auto': False, 'acquisition_mode': 'Continuous', 'n_frames': 1, 'triggered': False}
        self.exposed_params = ['frame_rate', 'gain', 'exposure', 'gain_auto', 'triggered', 'acquisition_mode', 'n_frames']
        self.params = {**default_params, **self.params}
        default_format = {'dtype': np.uint8}
        self.format = {**default_format, **self.format}

    def is_connected(self):
        cam_name = getattr(self, 'name', self.params.get('name', 'unknown')) if hasattr(self, 'params') else getattr(self, 'name', 'unknown')
        if self.h is None:
            display(f"Harvester library not available for camera '{cam_name}'.", level='error')
            return False
        ids, devices = GenI_get_cam_ids(self.h)
        if len(devices) == 0:
            display(f"No GenICam cams detected for '{cam_name}', check connections.", level='error')
            return False
        display(f"GenICam cams detected: {devices} for '{cam_name}'.", level='info')
        if self.cam_id in ids:
            display(f"Requested GenICam cam detected {self.cam_id} for '{cam_name}'.", level='info')
            return True
        display(f"Requested GenICam cam not detected {self.cam_id} for '{cam_name}', check connections.", level='error')
        return False

    def __enter__(self):
        if self.h is None:
            display('Harvester library not available. Cannot open GenICam camera.', level='error')
            self.cam_handle = None
            return self
        # Find the index of the device with the matching serial_number
        ids, devices = GenI_get_cam_ids(self.h)
        cam_index = None
        for idx, dev in enumerate(devices):
            if getattr(dev, 'serial_number', None) == self.cam_id:
                cam_index = idx
                break
        if cam_index is None:
            display(f"Could not find camera with serial_number {self.cam_id}", level='error')
            self.cam_handle = None
            return self
        self.cam_handle = self.h.create(cam_index)
        self.cam_handle.__enter__()
        self.cam_handle.num_buffers = 2
        self.features = self.cam_handle.remote_device.node_map
        self.apply_params()
        self._record()
        self._init_format()
        return self
        
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if hasattr(self, 'cam_handle') and self.cam_handle is not None:
            self.cam_handle.__exit__(exc_type, exc_value, exc_traceback)
            display('GenICam cam exited.')
        else:
            display('GenICam cam __exit__ called, but camera was never opened.', level='warning')
        self.close()
        return True

    def close(self):
        if hasattr(self, 'h') and self.h is not None:
            self.h.reset()
            display('GenICam cam closed.')
        else:
            display('GenICam cam close() called, but harvester was never opened.', level='warning')

    def apply_params(self):
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('GenICam cam apply_params() called, but camera was never opened.', level='warning')
            return
        # resume_recording = self.is_recording
        # if self.is_recording:
        #     self.stop()
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
                pass
        # if resume_recording:
        #     self._record()

    def get_features(self):
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('GenICam cam get_features() called, but camera was never opened.', level='warning')
            return ''
        features_str = ""
        for feature_name in dir(self.cam_handle.remote_device.node_map):
            try:
                features_str += feature_name + ': ' + getattr(self.cam_handle.remote_device.node_map, feature_name).to_string() + '\n'
            except Exception:
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
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('GenICam cam _record() called, but camera was never opened.', level='warning')
            return
        self.cam_handle.start() # it was self.cam_handle.start(run_in_background = True)
        limit = self.params['n_frames'] if self.params['acquisition_mode'] == "MultiFrame" else None
        self.t_start = time.time()
        self.frame_generator = self.get_frame_generator(n_frames = limit, timeout_ms = self.timeout//1000)
        self.is_recording = True
        
    def stop(self):
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('GenICam cam stop() called, but camera was never opened.', level='warning')
            return
        self.cam_handle.stop()
        self.is_recording = False
        display('GenICam cam stopped.')
        
    def image(self):
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('GenICam cam image() called, but camera was never opened.', level='warning')
            return None, 'not recording'
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
      