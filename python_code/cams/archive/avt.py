"""avt.pymb
Allied Vision Technologies cameras
"""
import time
from multiprocessing import Event
import numpy as np
from pymba import *
from .generic_cam import GenericCam
from ..utils import display

def debug_pickle(obj, prefix=''):
    import pickle, collections.abc
    try:
        pickle.dumps(obj)
        print(prefix, '✅ picklable', type(obj))
    except Exception as e:
        print(prefix, '❌ NOT picklable', type(obj), '→', e)
        if isinstance(obj, (list, tuple, set)):
            for i, item in enumerate(obj):
                debug_pickle(item, prefix + f'  [{i}] ')
        elif isinstance(obj, dict):
            for k, v in obj.items():
                debug_pickle(k, prefix + '  {key} ')
                debug_pickle(obj[k], prefix + f'  {k}: ')

def AVT_get_ids():
    with Vimba() as vimba:
        cam_ids = vimba.camera_ids()
        cams = [vimba.get_camera(id) for id in cam_ids]
        cam_infos = []
        for cam_id, cam in zip(cam_ids,cams):
            try:
                cam.open()
            except:
                cam_infos.append('')
                continue
            cam.close()
            print(cam.infos(), flush=True)
            cam_infos.append('{0} {1} {2}'.format(cam.DeviceModelName,
                                                  cam.DevicePartNumber,
                                                  cam.DeviceID))
    return cam_ids, cam_infos

class AVTCam(GenericCam):    
    def __init__(self, cam_id = None, outQ = None,
                 exposure = 29000,
                 frameRate = 30., gain = 10,frameTimeout = 100,
                 nFrameBuffers = 10,
                 triggered = Event(),
                 triggerSource = 'Line1',
                 triggerMode = 'LevelHigh',
                 triggerSelector = 'FrameStart',
                 acquisitionMode = 'Continuous',
                 nTriggeredFrames = 1000,
                 frame_timeout = 100,
                 recorderpar = None):
        
        super().__init__(name = 'AVT', cam_id = cam_id, outQ=outQ, recorderpar=recorderpar)
        
        self.exposure = ((1000000/int(frameRate)) - 150)/1000.
        self.frame_rate = frameRate
        self.gain = gain
        self.frameTimeout = frameTimeout
        self.triggerSource = triggerSource
        self.triggerSelector = triggerSelector
        self.acquisitionMode = acquisitionMode
        self.nTriggeredFrames = nTriggeredFrames 
        self.nbuffers = nFrameBuffers
        self.frame_timeout = frame_timeout
        self.triggerMode = triggerMode
        self.tickfreq = float(1.0)
        with Vimba() as vimba:
            self.cam = vimba.getCamera(cam_id)
            self.cam.openCamera()
            names = self.cam.getFeatureNames()
            # get a frame
            self.cam.acquisitionMode = 'SingleFrame'
            self.set_exposure(self.exposure)
            self.set_framerate(self.frame_rate)
            self.set_gain(self.gain)
            self.tickfreq = float(self.cam.GevTimestampTickFrequency)
            self.cam.TriggerSource = 'FixedRate'
            self.cam.TriggerMode = 'Off'
            self.cam.TriggerSelector = 'FrameStart'
            frame = self.cam.getFrame()
            frame.announceFrame()
            self.cam.startCapture()
            frame.queueFrameCapture()
            self.cam.runFeatureCommand('AcquisitionStart')
            frame.waitFrameCapture()
            self.cam.runFeatureCommand('AcquisitionStop')
            self.h = frame.height
            self.w = frame.width
            self.dtype = np.uint8
            self._init_variables(dtype = self.dtype)
            # ─── NEW ───  (detach via bytes → NumPy)
            buf       = bytes(frame.getBufferByteData())           # 1st copy
            frame_np  = np.frombuffer(buf, dtype=self.dtype)     # NumPy sees plain bytes
            frame_np  = frame_np.reshape(frame.height, frame.width)  # keep same shape
            frame_np  = frame_np.copy()

            self.img[:] = frame_np[:]
            display("AVT [{1}] = Got info from camera (name: {0})".format(
                self.cam.DeviceModelName,self.cam_id))
            self.cam.endCapture()
            self.cam.revokeAllFrames()
            self.cam = None
        self.triggered = triggered
        if self.triggered.is_set():
            display('AVT [{0}] - Triggered mode ON.'.format(self.cam_id))
            self.triggerSource = triggerSource

    def _init_controls(self):
        self.ctrevents = dict(exposure = dict(function = 'set_exposure',
                                            widget = 'float',
                                            variable = 'exposure',
                                            units = 'ms',
                                            type = 'float',
                                            min = 0.001,
                                            max = 100000,
                                            step = 10),
                                gain = dict(function = 'set_gain',
                                            widget = 'float',
                                            variable = 'gain',
                                            units = 'ms',
                                            type = 'int',
                                            min = 0,
                                            max = 30,
                                            step = 1),
                           framerate = dict(function = 'set_framerate',
                                            widget = 'float',
                                            type = 'float',
                                            variable = 'frame_rate',
                                            units = 'fps',
                                            min = 0.001,
                                            max = 1000,
                                            step = 1))
        
    def set_exposure(self,exposure = 30):
        '''Set the exposure time is in ms'''
        self.exposure = exposure
        if not self.cam is None:
            self.cam.ExposureTimeAbs =  int(self.exposure*1000)
            display('[AVT {0}] Setting exposure to {1} ms.'.format(self.cam_id, self.exposure))

    def set_framerate(self,frame_rate = 30):
        '''set the frame rate of the AVT camera.''' 
        self.frame_rate = frame_rate
        if not self.cam is None:
            self.cam.AcquisitionFrameRateAbs = self.frame_rate
            if self.cam_is_running:
                self.start_trigger.set()
                self.stop_trigger.set()
            display('[AVT {0}] Setting frame rate to {1} .'.format(self.cam_id, self.frame_rate))
                
    def set_gain(self,gain = 0):
        ''' Set the gain of the AVT camera'''
        self.gain = int(gain)
        if not self.cam is None:
            self.cam.GainRaw = self.gain
            display('[AVT {0}] Setting camera gain to {1} .'.format(self.cam_id, self.gain))
    
    def _cam_init(self):
        self.nframes.value = 0
        self.recorded_frames = []
        self.vimba = Vimba()
        self.vimba.startup()
        system = self.vimba.getSystem()
        if system.GeVTLIsPresent:
            system.runFeatureCommand("GeVDiscoveryAllOnce")
            time.sleep(0.1)
        # prepare camera
        self.cam = self.vimba.getCamera(self.cam_id)
        self.cam.openCamera()
        # cam.EventSelector = 'FrameTrigger'
        self.cam.EventNotification = 'On'
        self.cam.PixelFormat = 'Mono8'
        self.cameraFeatureNames = self.cam.getFeatureNames()
        #display('\n'.join(cameraFeatureNames))
        self.set_framerate(self.frame_rate)
        self.set_gain(self.gain)
        self.set_exposure(self.exposure)
        
        self.cam.SyncOutSelector = 'SyncOut1'
        self.cam.SyncOutSource = 'FrameReadout'#'Exposing'
        if self.triggered.is_set():
            self.cam.TriggerSource = self.triggerSource#'Line1'#self.triggerSource
            self.cam.TriggerMode = 'On'
            #cam.TriggerOverlap = 'Off'
            self.cam.TriggerActivation = self.triggerMode #'LevelHigh'##'RisingEdge'
            self.cam.AcquisitionMode = self.acquisitionMode
            self.cam.TriggerSelector = self.triggerSelector
            if self.acquisitionMode == 'MultiFrame':
                self.cam.AcquisitionFrameCount = self.nTriggeredFrames
                self.cam.TriggerActivation = self.triggerMode #'LevelHigh'##'RisingEdge'
        else:
            display('[Cam - {0}] Using no trigger.'.format(self.cam_id))
            self.cam.AcquisitionMode = 'Continuous'
            self.cam.TriggerSource = 'FixedRate'
            self.cam.TriggerMode = 'Off'
            self.cam.TriggerSelector = 'FrameStart'
        # create new frames for the camera
        self.frames = []
        for i in range(self.nbuffers):
            self.frames.append(self.cam.getFrame())    # creates a frame
            self.frames[i].announceFrame()
        self.cam.startCapture()
        for f,ff in enumerate(self.frames):
            try:
                ff.queueFrameCapture()
            except:
                display('Queue frame error while getting cam ready: '+ str(f))
                continue                    
        self.camera_ready.set()
        self.lastframeid = [-1 for i in self.frames]
        # Ready to wait for trigger
            
    def _cam_startacquisition(self):
        self.cam.runFeatureCommand("GevTimestampControlReset")
        self.cam.runFeatureCommand('AcquisitionStart')
        if self.triggered.is_set():
            self.cam.TriggerSelector = self.triggerSelector
            self.cam.TriggerMode = 'On'

    def _cam_loop(self):
        # run and acquire frames
        #sortedfids = np.argsort([f._frame.frameID for f in frames])
        for ibuf in range(self.nbuffers):
            f = self.frames[ibuf]
            avterr = f.waitFrameCapture(timeout = self.frameTimeout)
            if avterr == 0:
                timestamp = float(f._frame.timestamp)/self.tickfreq
                frameID = int(f._frame.frameID)
                #print('Frame id:{0}'.format(frameID))
                if not frameID in self.recorded_frames:
                    self.recorded_frames.append(frameID)
                    buf = f.getBufferByteData()
                    frame = np.frombuffer(bytes(buf), dtype=self.dtype).reshape((f.height, f.width))
                    #display("Time {0} - {1}:".format(str(1./(time.time()-tstart)),self.nframes.value))
                    #tstart = time.time()
                    try:
                        f.queueFrameCapture()
                    except:
                        display('Queue frame failed: '+ str(f))
                        return False, None,(None,None)
                    self.lastframeid[ibuf] = frameID
                    return True, frame,(frameID,timestamp)
            elif avterr == -12:
                #display('VimbaException: ' +  str(avterr))        
                return False, None,(None,None)

    def _cam_close(self):
        # Stop acquisition on the camera
        self.cam.runFeatureCommand('AcquisitionStop')
        display('[AVT]  Stopped acquisition.')

        # Drain any frames still in the buffers
        for ibuf in range(self.nbuffers):
            frm = self.frames[ibuf]
            try:
                frm.waitFrameCapture(timeout=self.frame_timeout)

                # Native Python types for metadata
                timestamp = float(frm._frame.timestamp) / self.tickfreq
                frameID   = int(frm._frame.frameID)

                # --- detach buffer via bytes() then NumPy ---
                buf       = bytes(frm.getBufferByteData())          # copy #1
                frame_np  = np.frombuffer(buf, dtype=self.dtype)    # plain buffer
                frame_np  = frame_np.reshape(frm.height, frm.width) # same shape
                # ------------------------------------------------

                if self.saving.is_set():
                    self.was_saving = True
                    if frameID not in self.lastframeid:
                        self.queue.put((frame_np.copy(), (frameID, timestamp)))
                elif self.was_saving:
                    self.was_saving = False
                    self.queue.put(['STOP'])

                self.lastframeid[ibuf] = frameID
                self.nframes.value     = frameID
                self.frame             = frame_np

            except VimbaException:
                # ignore timeouts or revoke errors on shutdown
                pass

        display(
            f'{self.cam.DeviceModelName} delivered:{self.cam.StatFrameDelivered}, '
            f'dropped:{self.cam.StatFrameDropped}, queued:{self.nframes.value}, '
            f'time:{self.cam.StatTimeElapsed}'
        )

        # Clean up SDK resources
        self.cam.runFeatureCommand('AcquisitionStop')
        self.cam.endCapture()
        try:
            self.cam.revokeAllFrames()
        except Exception:
            display('Failed to revoke frames.')

        self.cam.closeCamera()
        display(f'AVT [{self.cam_id}]  Close event: {self.close_event.is_set()}')
        self.vimba.shutdown()

