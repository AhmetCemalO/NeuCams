"""qimaging.py
QImaging cameras
"""

from multiprocessing import Event
from .generic_cam import GenericCam
try:
    from .qimaging_dll import *
except ImportError:
    pass
from ..utils import display

class QImagingCam(GenericCam):
    def __init__(self, cam_id = None,
                 outQ = None,
                 exposure = 100000,
                 gain = 3500,frameTimeout = 100,
                 nFrameBuffers = 1,
                 binning = 2,
                 triggerType = 0,
                 triggered = Event(),
                 recorderpar = None):
        '''
        Qimaging camera (tested with the Emc2 only!)
            triggerType (0=freerun,1=hardware,5=software)
        '''
        
        frame_rate = 1./(self.exposure/1000.)
        super().__init__(name = 'Qcam', cam_id = cam_id, outQ = outQ,
                         params = {'binning': binning, 'exposure': exposure,
                                   'gain': gain, 'frame_rate': frame_rate,
                                   'frameTimeout': frameTimeout, 'triggerType': triggerType,
                                   'estimated_readout_lag': 1257})
        self.triggered = triggered
        self._init_framebuffer()
        self.cam_queue = None
        
    def _init_framebuffer(self):
        ReleaseDriver()
        LoadDriver()
        self.cam = OpenCamera(ListCameras()[cam_id])
        self.set_cam_settings()
        self.cam.StartStreaming()
        frame = self.cam.GrabFrame()
        self.format['dtype'] = np.uint16
        buf = np.frombuffer(frame.stringBuffer,
                            dtype = self.format['dtype']).reshape(
                                (frame.width,frame.height))
        self.format['height'] = buf.shape[1]
        self.format['width'] = buf.shape[0]
        self.cam.StopStreaming()
        self.cam.CloseCamera()
        self.cam = None
        ReleaseDriver()
        super()._init_framebuffer()
        display("Got info from camera (name: {0})".format(self.cam_id))
    
    def _cam_init(self):
        ReleaseDriver()
        LoadDriver()
        self.nframes.value = 0
        if not self.camera_ready.is_set():
            # prepare camera
            self.cam = OpenCamera(ListCameras()[self.cam_id])
            if self.cam.settings.coolerActive:
                display('QImaging - cooler active.')
            triggerType = self.triggerType if self.triggered.is_set() else 0
            self.set_cam_settings(triggerType = self.params['triggerType'])
            
            display('QImaging - Camera ready!')
            self.camera_ready.set()
            
                
    def set_cam_settings(self, triggerType = 0):
        self.cam.settings.readoutSpeed=0 # 0=20MHz, 1=10MHz, 7=40MHz
        self.cam.settings.imageFormat = 'mono16'
        self.cam.settings.binning = self.binning
        self.cam.settings.emGain = self.gain
        self.cam.settings.triggerType = triggerType
        self.cam.settings.exposure = self.exposure - self.estimated_readout_lag
        self.cam.settings.blackoutMode=True
        self.cam.settings.Flush()
    
    def wait_for_start_trigger(self):
        while not self.start_trigger.is_set():
            # limits resolution to 1 ms 
            time.sleep(0.001)
            if self.close_event.is_set():
                return
    
    def _cam_close(self):
        self.cam_queue.stop()
        self.cam.settings.blackoutMode=False
        self.cam.settings.Flush()
        self.cam.Abort()
        self.cam.CloseCamera()
        self.cam = None
        self.saving.clear()
        self.start_trigger.clear()
        self.stop_trigger.clear()
        ReleaseDriver()
        
    def run(self):
        
        self.close_event.clear()
        while not self.close_event.is_set():
            
            self._cam_init()
            self.wait_for_start_trigger()
            self.cam_queue = CameraQueue(self.cam)
            self.cam_queue.start()
            display('QImaging - Started acquisition.')
            self.camera_ready.clear()
            while not self.stop_trigger.is_set():
                # run and acquire frames
                try:
                    f = self.cam_queue.get(True, 1)
                except self.cam_queue.Empty:
                    continue
                self.nframes.value += 1
                frame = np.ndarray(buffer = f.stringBuffer,
                                   dtype = self.dtype,
                                   shape = (self.w,
                                            self.h)).copy()
                timestamp = f.timeStamp
                frameID = f.frameNumber
                if self.saving.is_set():
                    self.was_saving = True
                    self.queue.put((frame.reshape([self.h,self.w]),
                                    (frameID,timestamp)))
                elif self.was_saving:
                    self.was_saving = False
                    self.queue.put(['STOP'])
                self.img[:] = np.reshape(frame,self.img.shape)[:]

                self.cam_queue.put(f)
            
            time.sleep(0.01)
            display('QImaging - Stopped acquisition.')
    
    