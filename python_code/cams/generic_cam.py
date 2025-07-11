"""cams.py
Camera classes for behavioral monitoring and single photon imaging.
Creates separate processes for acquisition and queues frames"""
import time
import ctypes

import numpy as np
from utils import display


class GenericCam:
    """Abstract class for interfacing with the cameras
    Has last frame on multiprocessing array
    """
    def __init__(self, name = '', cam_id = None, params = None, format = None):
        
        self.name = name
        self.cam_id = cam_id
        self.cam_handle = None
        
        self.params = params if params is not None else {}
        self.format = format if format is not None else {}
        
        self.is_recording = False
        
        self.exposed_params = []
    
    def _init_format(self):
        frame, _ = self.image()
        # Handle shared memory tuple from AVT
        if isinstance(frame, tuple) and len(frame) == 3 and isinstance(frame[0], str):
            from cams.avt_cam import AVTCam  # <-- move import here
            shm_name, shape, dtype = frame
            frame, shm = AVTCam.frame_from_shm(shm_name, shape, dtype)
            frame = np.array(frame, copy=True)
            shm.close()
            shm.unlink()
        self.format['height'] = frame.shape[0]
        self.format['width'] = frame.shape[1]
        self.format['n_chan'] = frame.shape[2] if frame.ndim == 3 else 1
        display(f"{self.name} - size: {self.format['height']} x {self.format['width']}")
    
    def is_connected(self):
        pass
        
    def __enter__(self):
        return self
        
    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        '''close cam - release driver'''
        pass
        
    def apply_params(self):
        pass
    
    def set_param(self, param : str, val):
        param = param.lower()
        if param in self.exposed_params:
            self.params[param] = val
            print(f"Set param {param} : {val}", flush=True)
        
    def get_param(self, param : str):
        pass
    
    def get_features(self):
        """returns features as formatted string"""
        pass
        
    def _record(self):
        '''start camera acq'''
        pass

    def stop(self):
        '''stop camera acq'''
        pass
    
    def get_health_status(self):
        pass
    
    def image(self):
        pass

