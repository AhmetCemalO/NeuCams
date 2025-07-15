from multiprocessing import Process,Queue,Event,Array,Value
import queue
import numpy as np
import ctypes
import time
import datetime
from os.path import dirname, join
from file_writer import BinaryWriter, TiffWriter, FFMPEGWriter, OpenCVWriter
from utils import display, resolve_cam_id_by_serial
from importlib import import_module
from cams.avt_cam import AVTCam
# from cams.pco_cam import PCOCam
# from cams.genicam import GenICam

def clear_queue(my_queue):
    while True:
        try:
            my_queue.get_nowait()
        except queue.Empty:
            break

class CameraFactory:
    cameras = {
        'avt': ('cams.avt_cam', 'AVTCam'),
        'pco': ('cams.pco_cam', 'PCOCam'),
        'genicam': ('cams.genicam', 'GenICam'),
        # Add more drivers here as needed
    }

    @staticmethod
    def get_camera(driver, cam_id=None, params=None):
        if driver not in CameraFactory.cameras:
            raise ValueError(f"Unknown camera driver: {driver}")
        module_name, class_name = CameraFactory.cameras[driver]
        module = import_module(module_name, package='python_code')
        cam_class = getattr(module, class_name)
        return cam_class(cam_id=cam_id, params=params)

class CameraHandler(Process):
    
    def __init__(self, cam_dict, writer_dict):
        super().__init__()
        
        self.cam_dict = cam_dict
        self.writer_dict = writer_dict
        
        self.close_event = Event()
        self.start_trigger = Event()
        self.is_running = Event()
        self.stop_trigger = Event()
        self.camera_ready = Event()
        self.saving = Event()
        
        self.is_acquisition_done = Event()

        self.cam_param_InQ = Queue()
        self.cam_param_OutQ = Queue()
        self.cam_param_get_flag = Event()
        
        self.handler_closed = Event()
        
        self.img = None
        self.folder_path_array = Array('u',' ' * 1024) #can set folder
        self.filepath_array = Array('u',' ' * 1024) #filepath is readonly
        
        self.run_nr = 0
        self.frame_nr = 0
        
        self.total_frames = Value('i', 0)
        
        self.lastframeid = -1
        self.last_timestamp = 0
        
        cam = self._open_cam()
        self.camera_connected = cam.is_connected()
        if not self.camera_connected:
            display(f"Camera '{self.cam_dict.get('description', 'unknown')}' (name: '{self.cam_dict.get('name', 'unknown')}') not found or not connected. Please check the connection and close other processes which use the camera.", level='error')
        cam.close()
        
        if self.camera_connected:
            self._init_framebuffer()
        
    def _init_framebuffer(self):
        with self._open_cam() as cam:
            dtype  = cam.format.get('dtype', None)
            height = cam.format.get('height', None)
            width  = cam.format.get('width', None)
            n_chan = cam.format.get('n_chan', 1)
            
            if dtype == np.uint8:
                cdtype = ctypes.c_ubyte
            elif dtype == np.uint16:
                cdtype = ctypes.c_ushort
            else:
                display(f"WARNING: dtype {dtype} not available, defaulting to np.uint16")
                cdtype = ctypes.c_ushort
            
            if (dtype is None) or (height is None) or (width is None):
                display(f"ERROR: format (height, width, dtype[,n_chan]) needs to be set to init the framebuffer")
                return

            self.frame = Array(cdtype,np.zeros([height, width, n_chan],
                                               dtype = dtype).flatten())
            self.format = {'dtype':dtype, 'height':height,'width':width,'n_chan':n_chan,'cdtype':cdtype}
            
            self._init_buffer()
            
    def _init_buffer(self):
        self.img = np.frombuffer(self.frame.get_obj(), dtype = self.format['cdtype'])\
                        .reshape([self.format['height'], self.format['width'], self.format['n_chan']])
                        
    def run(self):
        self._init_buffer()
        with self._open_cam() as cam:
            self.cam = cam
            with self._open_writer() as writer:
                self.writer = writer
                while not self.close_event.is_set():
                    self._process_queues()
                    self.init_run()
                    
                    display(f'[{cam.name} {cam.cam_id}] waiting for trigger.')
                    self.wait_for_trigger()
                    if self.start_trigger.is_set():
                        display(f'[{cam.name} {cam.cam_id}] start trigger set.')
                        if self.saving.is_set():
                            display(f'[{cam.name} {cam.cam_id}] filepath: {self.get_filepath()}')
                    while not self.stop_trigger.is_set():
                        self._process_queues()
                        frame, metadata = cam.image()
                        # Handle shared memory tuple from AVT
                        if isinstance(frame, tuple) and len(frame) == 3 and isinstance(frame[0], str):
                            shm_name, shape, dtype = frame
                            frame, shm = AVTCam.frame_from_shm(shm_name, shape, dtype)
                            frame = np.array(frame, copy=True)
                            shm.close()
                            shm.unlink()
                        # Remove type/shape debug prints
                        if frame is not None:
                            if self.saving.is_set():
                                writer.save(frame, metadata)
                            self._update(frame,metadata)
                        elif metadata == "stop":
                            self.stop_trigger.set()
                    display(f'[{cam.name} {cam.cam_id}] stop trigger set.')
                    self.close_run()
        self.handler_closed.set()
    
    def _open_writer(self):
        writer_type = self.writer_dict.get('recorder', 'opencv')
        writers = {'opencv': OpenCVWriter, 'binary': BinaryWriter, 'tiff': TiffWriter, 'ffmpeg': FFMPEGWriter} 
        writer = writers[writer_type]
        std_keys = ['frames_per_file'] #might be more later again
        dict = {key: self.writer_dict[key] for key in self.writer_dict if key in std_keys}
        folder = join(self.writer_dict['data_folder'], self.cam_dict['description'], self.writer_dict['experiment_folder'])
        self.set_folder_path(folder)
        dict['filepath'] = self.get_new_filepath()
        dict['frame_rate'] = self.cam.params.get('frame_rate', None)
        return writer(**dict)
    
    def get_filepath(self):
        return str(self.filepath_array[:]).strip(' ')
    
    def _update_filepath_array(self, filepath):
        for i in range(len(self.filepath_array)):
            self.filepath_array[i] = ' '
        for i in range(len(filepath)):
            self.filepath_array[i] = filepath[i]
            
    def get_folder_path(self):
        return str(self.folder_path_array[:]).strip(' ')
        
    def set_folder_path(self, folder_path):
        for i in range(len(self.folder_path_array)):
            self.folder_path_array[i] = ' '
        for i in range(len(folder_path)):
            self.folder_path_array[i] = folder_path[i]
    
    def get_new_filename(self):
        return datetime.date.today().strftime('%y%m%d') + '_' + f"{self.run_nr}"
    
    def get_new_filepath(self):
        filepath = join(self.get_folder_path(), self.get_new_filename())
        self._update_filepath_array(filepath)
        return filepath
        
    def _open_cam(self):
        cam_dict_copy = self.cam_dict.copy()
        cam_type = cam_dict_copy.pop('driver', 'avt').lower()
        serial_number = cam_dict_copy.get('serial_number', None)
        # Prefer serial_number, fallback to id
        if serial_number is not None:
            cam_id = resolve_cam_id_by_serial(cam_type, serial_number)
        else:
            cam_id = cam_dict_copy.get('id', None)
        return CameraFactory.get_camera(
            cam_type,
            cam_id=cam_id,
            params=cam_dict_copy.get('params', None)
        )
    
    def get_image(self):
        return self.img
    
    def init_run(self):
        self.frame_nr = 0
        self.lastframeid = -1
        self.writer.set_filepath(self.get_new_filepath())
        self.camera_ready.set()
    
    def close_run(self):
        self.start_trigger.clear()
        self.is_acquisition_done.set()
        if self.saving.is_set():
            self.run_nr += 1
        if not self.close_event.is_set():
            self.stop_trigger.clear()
        self.is_running.clear()

    def _update(self, frame, metadata):
        self._update_buffer(frame)
        self.frame_nr += 1
        self.total_frames.value += 1
        frameID,timestamp = metadata[:2]
        self.lastframeid = frameID
        self.last_timestamp = timestamp
    
    def _update_buffer(self,frame):
        self.img[:] = np.reshape(frame,self.img.shape)[:]
        
    def wait_for_trigger(self):
        while not self.start_trigger.is_set() and not self.stop_trigger.is_set():
            self._process_queues()
            time.sleep(0.001) # limits resolution to 1 ms
        self.cam.apply_params()
        self.is_running.set()
        self.camera_ready.clear()
    
    def _process_queues(self):
        self._process_params()
    
    def _process_params(self):
        """ self.cam_param_InQ is setget
            ('set', param, val)
            ('get') -> returns all params # TODO should we get the actual values of the acquisition rather than the last inputs?
            self.cam_param_OutQ is queried params
            (param, val) [only queried params]
        """
        params_to_set = False
        while True:
            try:
               param = self.cam_param_InQ.get_nowait()
            except queue.Empty:
                break
            else:
                if param[0] == 'get':
                    try:
                        clear_queue(self.cam_param_OutQ)
                        self.cam_param_OutQ.put_nowait({k:self.cam.params[k] for k in self.cam.params if k in self.cam.exposed_params})
                    except queue.Full:
                        pass
                    self.cam_param_get_flag.set()
                elif param[0] == 'set':
                    self.cam.set_param(param[1], param[2])
                    params_to_set = True
        if params_to_set:
            self.cam.apply_params()

    def set_cam_param(self, param : str, val):
        try:
            self.cam_param_InQ.put_nowait(['set', param, val])
        except queue.Full:
            # print(f"Warning: could not set cam params, order queue is full", flush=True)
            pass
    
    def query_cam_params(self):
        try:
            self.cam_param_InQ.put_nowait(['get'])
        except queue.Full:
            # print(f"Warning: could not query cam params, order queue is full", flush=True)
            pass
                
    def get_cam_params(self):
        if not self.cam_param_get_flag.is_set():
            print(f"Warning: check cam_param_get_flag before calling this function, returning.", flush=True)
            return
        n_loop = 0
        ret = None
        while True:
            try:
                ret = self.cam_param_OutQ.get_nowait()
                self.cam_param_get_flag.clear()
            except queue.Empty:
                break
            n_loop += 1
        if n_loop > 1:
            print(f"Warning: you queried the cam params {n_loop} times and only got them once", flush=True)
        
        return ret
        
    def start_saving(self):
        self.saving.set()
        
    def stop_saving(self):
        self.saving.clear()
    
    def start_acquisition(self):
        if self.camera_ready.is_set():
            self.is_acquisition_done.clear()
            self.start_trigger.set()
            return True
        print(f"Could not start acquisition, camera {self.cam_dict['description']} not ready", flush=True)
        return False
        
    def stop_acquisition(self):
        self.stop_trigger.set()

    def close(self):
        self.close_event.set()
        self.stop_acquisition()
        self.handler_closed.wait()