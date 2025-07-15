import numpy as np
import datetime
from os.path import join
from application.abstract_cam import (
    Camera,
    CameraModes,
    CameraGeneratorStopped
    )
from application.frame import (
    Frame,
    FrameStatus
    )
from application.utils import (
    display,
    for_all_methods,
    print_unhandled_exception,
    RepeatTimer
    )
from application.file_writer import FileWriter


@for_all_methods(print_unhandled_exception)
class AcquisitionHandler:
    """"""
    def __init__(self, cam: Camera, writer: FileWriter):
        self.cam = cam
        self.writer = writer

        self.close_event = False
        self.start_trigger = False
        self.stop_trigger = False
        self.camera_ready = False
        self.saving = False

        self.is_acquisition_done = False

        self.img = None

        self.cam_folder_path = ""
        self.exp_folder_path = ""  # can set folder
        self._folder_path = ""

        self.run_nr = 0
        self.frame_nr = 0

        self.mode = None

        self.effective_framerate = 0
        self.last_timestamp = 0

        self.cam.open()

        self.processor = self._process()

    def _process(self):
        """this is a generator (which yields nothing useful), this way we can use context managers
        and have a (relatively) clean flow logic.
        The alternative solution is to separate this function into init-loop-shutdown,
        which would be much longer and messier to handle.""" 
        while not self.close_event:
            self.init_run()
            display(f'[{str(self.cam)}] waiting for trigger.')
            while not self.start_trigger and not self.stop_trigger:
                yield 0   
            self.start_run()
            while not self.stop_trigger:
                if self.mode == CameraModes.SYNC:
                    self.get_and_process_frame()
                yield 0
            
            self.close_run()

    def start_run(self):
        self.frame_nr = 0
        self.effective_framerate = 0
        self.camera_ready = False
        
        if self.start_trigger:
            display(f'[{str(self.cam)}] start trigger set.')
            self.enter_camera_mode()

    def get_and_process_frame(self):
        try:
            frame = self.cam.get_frame()
            if frame.status == FrameStatus.SUCCESS:
                self._process_frame(frame)
        except CameraGeneratorStopped:
            if self.cam.params['acquisition_mode'] == self.cam._AcquisitionMode.CONTINUOUS:
                print('ERROR: camera generator ended, probable causes:\n',
                        '\t- camera has lost power or faulty connection\n',
                        '\t- exception was thrown in generator, killing it, causing StopIteration in next',
                        flush=True)
            self.stop_trigger = True

    def _process_frame(self, frame: Frame):
        self._update(frame)
        if self.saving:
            self.writer.save(frame)

    def _update(self, frame: Frame):
        self._update_buffer(frame.buffer)
        self.frame_nr += 1
        timestamp = frame.timestamp
        self.effective_framerate = round(1/(timestamp - self.last_timestamp),1)
        self.last_timestamp = timestamp

        # https://docs.python.org/3/library/multiprocessing.shared_memory.html
        
        # self.frame = Array(cdtype,np.zeros([self.h,self.w,self.nchan],
        #                                    dtype = dtype).flatten())
        # self.img = np.frombuffer(
        #     self.frame.get_obj(),
        #     dtype = cdtype).reshape([self.h, self.w, self.nchan])

    def _update_buffer(self, buffer: np.ndarray):
        # NB: we don't know the x-y format, as there might be binning
        buffer_copy = np.copy(buffer)
        n_chan = buffer.shape[2] if buffer.ndim == 3 else 1
        self.img = np.reshape(buffer_copy, (buffer_copy.shape[0], buffer_copy.shape[1], n_chan))

    def is_trigger_set(self, *trigger_names):
        triggers = []
        for trigger_name in trigger_names:
            if not hasattr(self, trigger_name):
                raise AttributeError(f'No trigger {trigger_name} in camera handler')
            triggers.append(getattr(self, trigger_name))
        if len(trigger_names) == 1:
            return triggers[0]
        return triggers

    def get_frame_nr(self):
        return self.frame_nr
    
    def get_framerate(self):
        return self.effective_framerate
    
    def get_image(self):
        return self.img

    def get_filepath(self):
        writer_path = self.writer.get_current_filepath()
        return writer_path if writer_path != "" else self._folder_path

    def set_folder_path(self, root=None, exp=None):
        self.root_folder_path = self.root_folder_path if root is None else root
        self.exp_folder_path = self.exp_folder_path if exp is None else exp
        self._folder_path = join(self.root_folder_path, self.exp_folder_path)
        display(f'[{str(self.cam)}] stopping acquisition to set folder path to\n{self._folder_path}')
        self.stop_acquisition()

    def get_filename_suffix(self):
        return datetime.date.today().strftime('%y%m%d') + '_' + f"{self.run_nr}"

    def get_new_filepath(self):
        return join(self._folder_path, self.get_filename_suffix())

    def init_run(self):
        self.writer.update_base_filepath(self.get_new_filepath())
        if hasattr(self.writer, 'frame_rate'):
            self.writer.update_attributes(frame_rate=self.cam.params.get('frame_rate', None))
        self.camera_ready = True

    def close_run(self):
        if self.start_trigger:
            self.exit_camera_mode()
        display(f'[{str(self.cam)}] stop trigger set.')
        self.start_trigger = False
        self.is_acquisition_done = True
        if self.saving:
            display(f'[{str(self.cam)}] filepath: {self.get_filepath()}')
            self.run_nr += 1
        if not self.close_event:
            self.stop_trigger = False
        
    def set_cam_mode(self, mode):
        self.cam.set_mode(mode)

    def set_cam_param(self, param: str, val):
        self.cam.add_param_to_set(param, val)
        self.cam.apply_params()
    
    def set_cam_params(self, params_dict):
        for key, val in params_dict.items():
            self.cam.add_param_to_set(key, val)
        self.cam.apply_params()
    
    def cam_load_settings(self, settings_path):
        """If manufacturer API has load_settings/save_settings methods"""
        self.cam.load_settings(settings_path)

    def get_cam_params(self):
        return {k:self.cam.params[k] for k in self.cam.params if k in self.cam.exposed_params}

    def get_cam_modes(self):
        return self.cam.available_modes

    def enable_saving(self, state=True):
        self.saving = state

    def disable_saving(self):
        self.enable_saving(state=False)

    def start_acquisition(self):
        if self.camera_ready:
            self.is_acquisition_done = False
            self.start_trigger = True
            return True
        print(f"Could not start acquisition, camera {str(self.cam)} not ready", flush=True)
        return False

    def enter_camera_mode(self):
        self.mode = self.cam.current_mode
        if self.mode in [CameraModes.ASYNC_SW, CameraModes.ASYNC_HW]:
            self.cam.set_asynchronous_callback(self._process_frame)
            if self.mode == CameraModes.ASYNC_SW:
                time_interval_s = 1.0/self.cam.params['frame_rate']
                self.emitter_thread = RepeatTimer(time_interval_s,
                                                self.cam.emit_software_trigger)
                self.emitter_thread.start()
        self.cam.record()

    def exit_camera_mode(self):
        if self.mode == CameraModes.ASYNC_SW:
            self.emitter_thread.stop()
        self.cam.stop()

    def stop_acquisition(self):
        self.stop_trigger = True

    def close(self):
        self.close_event = True
        self.stop_acquisition()
        while True:
            try:
                next(self.processor)
            except StopIteration:
                break
        self.cam.close()
        self.writer.close()
