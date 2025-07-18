import time
import cv2
import numpy as np
from multiprocessing import Event
from .generic_cam import GenericCam
from ..utils import display

class OpenCVCam(GenericCam):
    """OpenCV camera; some functionality limited (like hardware triggers)
    """
    def __init__(self,
                 cam_id = None,
                 outQ = None,
                 frame_rate = 0.,
                 triggered = Event(),
                 recorderpar = None,
                 **kwargs):

        super().__init__(name = 'OpenCV', cam_id = cam_id, outQ = outQ, 
                         recorderpar = recorderpar, 
                         params = {'frame_rate': float(frame_rate)})
        
        self._init_framebuffer()
        
        self.triggered = triggered
        if self.triggered.is_set():
            display('[OpenCV {0}] Triggered mode ON.'.format(self.cam_id))
            self.triggerSource = triggerSource
    
    def _init_framebuffer(self):
        self.cam = cv2.VideoCapture(self.cam_id)
        self.set_cam_settings()
        ret_val, frame = self.cam.read()
        if ret_val:
            self.format['height'] = frame.shape[0]
            self.format['width'] = frame.shape[1]
            if len(frame.shape) > 2:
                self.format['n_chan'] = frame.shape[2]
            self.format['dtype'] = frame.dtype
            super()._init_framebuffer()
        else:
            display('ERROR: failed to read frame, framebuffer not initialized')
        self.cam.release()
        self.cam = None
    
    def _init_controls(self):
        self.ctrevents = dict(framerate=dict(function = 'set_framerate',
                                             widget = 'float',
                                             variable = 'frame_rate',
                                             units = 'fps',
                                             type = 'float',
                                             min = 0.0,
                                             max = 1000,
                                             step = 0.1))
    
    def set_cam_settings(self):
        self.set_framerate(self.params['frame_rate'])
        
    def set_framerate(self,framerate = 30.):
        '''Set frame rate in seconds'''
        self.frame_rate = float(framerate)
        if not self.cam is None:
            if not float(self.frame_rate) == float(0):
                self.cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                self.cam.set(cv2.CAP_PROP_EXPOSURE,1./self.frame_rate)
                self.cam.set(cv2.CAP_PROP_FPS,self.frame_rate)
            else:
                display('[OpenCV] Setting auto exposure.')
                self.cam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
                self.cam.set(cv2.CAP_PROP_EXPOSURE, 100)

            if self.cam_is_running:
                self.stop_trigger.set()
                self.start_trigger.set()

            display('[OpenCV {0}] Set frame_rate to: {1}.'.format(self.cam_id,
                                                                  self.frame_rate))

    def _cam_init(self):
        self.nframes.value = 0
        self.lastframeid = -1
        self.cam = cv2.VideoCapture(self.cam_id)
        self.set_framerate(self.frame_rate)
        self.camera_ready.set()
        
    def _cam_loop(self):
        frameID = self.nframes.value
        self.nframes.value = frameID + 1
        ret_val, frame = self.cam.read()
        if not ret_val:
            return ret_val, None, (None,None)
        timestamp = time.time()
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return ret_val, frame,(frameID,timestamp)

    def _cam_close(self):
        self.cam.release()
        display('[OpenCV {0}] - Stopped acquisition.'.format(self.cam_id))
