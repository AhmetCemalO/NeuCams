"""pco_cam.py
"""
import time
import numpy as np
try:
    import pco
except ImportError:
    pco = None
from NeuCams.cams.generic_cam import GenericCam
from NeuCams.utils import display

class PCOCam(GenericCam):
    def __init__(self, cam_id = None, params = None, format = None):
        
        cam_id = 0 # the cam_id is discarded for PCOCam, the pco.Camera class does not allow specific opening
        # it is possible to select specific interface/camera id via sdk (or by adjusting init of Camera), 
        # since we don't use multiple PCO's per setup, I will keep it simple
        
        super().__init__(name = 'PCO', cam_id = cam_id, params = params, format = format)
        
        default_params = {'exposure':15000, 
                          'triggered':False,
                          'triggerSource': 'external exposure start & software trigger',
                          'binning': 1
                          #'poll_timeout':1, 
                          }
                          
                            # 'triggerSource' options
                            # * 'auto sequence'
                            # * 'software trigger'
                            # * 'external exposure start & software trigger'
                            # * 'external exposure control'
                            # * 'external synchronized'
                            # * 'fast external exposure control'
                            # * 'external CDS control'
                            # * 'slow external exposure control'
                            # * 'external synchronized HDSDI'
        self.exposed_params = ['exposure', 'triggered', 'binning']
        
        self.params = {**default_params, **self.params}
        
        default_format = {'dtype': np.uint16}
        self.format = {**default_format, **self.format}
    
    def is_connected(self):
        cam_name = getattr(self, 'name', self.params.get('name', 'unknown')) if hasattr(self, 'params') else getattr(self, 'name', 'unknown')
        if pco is None:
            display(f"PCO library not available for camera '{cam_name}'.", level='error')
            return False
        try:
            cam = pco.Camera()
            cam.close()
            display(f"PCO cam detected for '{cam_name}'.")
            return True
        except Exception:
            display(f"PCO cam not detected for '{cam_name}'.", level='error')
            return False
        
    def __enter__(self):
        if pco is None:
            display('PCO library not available. Cannot open camera.', level='error')
            self.cam_handle = None
            return self
        self.cam_handle = pco.Camera()
        self.cam_handle.__enter__()
        self.apply_params()
        self._record()
        self._init_format()
        return self
        
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.stop()
        if hasattr(self, 'cam_handle') and self.cam_handle is not None:
            self.cam_handle.__exit__(exc_type, exc_value, exc_traceback)
            display('PCO cam exited.')
        else:
            display('PCO cam __exit__ called, but camera was never opened.', level='warning')
        return True
        
    def close(self):
        if hasattr(self, 'cam_handle') and self.cam_handle is not None:
            self.cam_handle.close()
            display('PCO cam closed.')
        else:
            display('PCO cam close() called, but camera was never opened.', level='warning')

    def apply_params(self):
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('PCO cam apply_params() called, but camera was never opened.', level='warning')
            return
        resume_recording = self.is_recording
        if self.is_recording:
            self.stop()
        adjusted_params = self.params.copy()
        adjusted_params['exposure time'] = adjusted_params.pop('exposure')/1_000_000
        adjusted_params['trigger'] = adjusted_params['triggerSource'] if self.params['triggered'] else 'auto sequence'
        adjusted_params['binning'] = (adjusted_params['binning'],adjusted_params['binning'])
        self.cam_handle.configuration = adjusted_params
        display(f'PCO - configuration: {self.cam_handle.configuration}')
        if resume_recording:
            self._record()

    def _record(self):
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('PCO cam _record() called, but camera was never opened.', level='warning')
            return
        self.cam_handle.record(number_of_images = 10, mode = 'fifo')
        self.is_recording = True

    def stop(self):
        if hasattr(self, 'cam_handle') and self.cam_handle is not None:
            self.cam_handle.stop()
            self.is_recording = False
            display('PCO cam stopped.')
        else:
            display('PCO cam stop() called, but camera was never opened.', level='warning')

    def get_health_status(self):
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('PCO cam get_health_status() called, but camera was never opened.', level='warning')
            return 0
        ret = self.cam_handle.sdk.get_camera_health_status()
        if 'status' in ret:
            display(f"PCO - Camera health status: {ret['status']}")
        if 'warning' in ret:
            display(f"PCO - Camera health warning: {ret['warning']}")
        if 'error' in ret:
            display(f"PCO - Camera health error: {ret['error']}")
            return -1
        return 0

    def image(self):
        if not hasattr(self, 'cam_handle') or self.cam_handle is None:
            display('PCO cam image() called, but camera was never opened.', level='warning')
            return None, 'not recording'
        self.cam_handle.wait_for_first_image()
        frame, meta = self.cam_handle.image()
        return frame, (meta['camera image number'], time.time())
