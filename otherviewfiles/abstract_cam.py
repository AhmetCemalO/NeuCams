"""cams.py
Camera classes for behavioral monitoring and single photon imaging.
Creates separate processes for acquisition and queues frames"""
from abc import ABC, abstractmethod
import time
from collections import namedtuple
from enum import Enum, auto
from dataclasses import dataclass
from typing import Callable, List, Union
from colorama import Fore, Style
import numpy as np
from application.frame import (
    Frame,
    FrameStatus
    )

CameraInfos = namedtuple('CameraInfos', 'model serial id')


class CameraNotFoundError(Exception):
    """Custom exception for absent cameras"""


class CameraTimeout(Exception):
    """Custom exception for timeouts"""


class CameraError(Exception):
    """Custom exception for generic camera errors"""


class CameraGeneratorStopped(Exception):
    """Custom exception raised when trying to access camera image but generator is stopped"""


@dataclass
class CameraFeature:
    name: str
    value: object


class CameraModes(Enum):
    SYNCHRONOUS = SYNC = 'Synchronous'
    ASYNCHRONOUS_SOFTWARE_TRIGGER = ASYNC_SW = 'Asynchronous - Software'
    ASYNCHRONOUS_HARDWARE_TRIGGER = ASYNC_HW = 'Asynchronous - Hardware'


class Camera(ABC):
    """Abstract class for interfacing with the cameras
    """
    _default_frame_timeout_ms: int = 1000

    class _AcquisitionMode:
        CONTINUOUS = 'Continuous'
        MULTIFRAME = 'MultiFrame'

    class _TriggerSource:
        SOFTWARE = SW = 'Software'
        HARDWARE = HW = 'Hardware'

    class _TriggerMode:
        OFF = 'Off'
        ON = 'On'

    def __init__(self, id, handle, params=None):
        self.id = id
        self._handle = handle
        self.params = params if params is not None else {}
        self._is_recording = False
        self._frame_timeout_ms = self._default_frame_timeout_ms
        self.exposed_params = []  # exposed params have standard names for use in GUI
        self.available_modes = [CameraModes.SYNC]
        self.current_mode = self.available_modes[0]
        self._frame_generator = None
        self._unexposed_params_to_set = {}
        self._asynchronous_callback = None
        self._params_LUT = {}
        self._value_modifier_LUT = {}  # divide when set, multiply when get
        self.record = self._record_synchronous
        self.stop = self._stop_record_synchronous

    def __str__(self):
        """Get instance name in the form ClassName:id"""
        return f"{self.__class__.__name__}:{self.id}"

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        """To override if no context was entered in open"""
        self.close()

    def open(self):
        self._init_handle()
        self._init_settings()
        self.apply_params()
        self.record()

    def _init_handle(self):
        """Init handle context and eventually assign variables"""

    def close(self):
        """close camera"""
        self.stop()

    def add_param_to_set(self, param: str, val):
        """Add a parameter to set later using apply_params.
        It enforces type continuity."""
        if param in self.exposed_params:
            self.params[param] = type(self.params[param])(val)
        else:
            if param in self._unexposed_params_to_set:
                val = type(self._unexposed_params_to_set[param])(val)
            self._unexposed_params_to_set[param] = val

    @abstractmethod
    def _set_params(self):
        """Camera specific method to set camera parameters (framerate, exposure,...)"""
    
    def apply_params(self):
        """Handles stop/resume to apply camera parameters"""
        self._stop_and_resume_recording_if_needed(self._set_params)

    def _update_params(self, params):
        for key, val in params.items():
            try:
                LU_key = self._params_LUT.get(key, key)
                type_val = type(val)
                modifier = None
                if type_val in [int, float]:
                    modifier = self._value_modifier_LUT.get(key, 1)
                    val = type_val(val/modifier)
                self._set_param(LU_key, val)
                if key in self.params:
                    param_type = type(self.params[key])
                    new_val = self._get_param(LU_key)
                    if modifier is not None:
                        new_val *= modifier
                    self.params[key] = param_type(new_val)
            except Exception as exc:
                print(Fore.BLACK + Style.BRIGHT
                    + f"Error with feature {key} : {repr(exc)}"
                    + Style.RESET_ALL,
                    flush=True)

    def _set_param(self, feature_name, value):
        raise NotImplementedError

    def _get_param(self, feature_name):
        raise NotImplementedError

    def _stop_and_resume_recording_if_needed(self, func, *args, **kwargs):
        resume_record = self._is_recording
        if resume_record:
            self.stop()
        res = func(*args, **kwargs)
        if resume_record:
            self.record()
        return res

    def _init_settings(self):
        """One time settings"""

    def load_settings(self, settings_path = None):
        """Load settings using a settings file, handles stop/resume recording"""
        if settings_path is not None:
            self._stop_and_resume_recording_if_needed(self._load_settings, settings_path)

    def _load_settings(self, settings_path):
        """Load settings, manufacturer API needs a dedicated load settings method
        Example: generate settings file in manufacturer program (e.g., Vimba tools or Vimba X SDK Viewer), 
        then load them using load_settings."""
        raise NotImplementedError

    def get_features(self) -> List[CameraFeature]:
        """returns features as formatted string"""
        raise NotImplementedError
                
    def record(self):
        """Start the recording"""

    def stop(self):
        """Stop the recording"""

    def _update_current_mode(self):
        self.current_mode = self._get_current_mode()
        if self.current_mode == CameraModes.SYNC:
            self._set_synchronous_mode()
        else:
            self._set_asynchronous_mode()

    def _get_current_mode(self):
        if self.params['trigger_mode'] == self._TriggerMode.ON:
            if self.params['trigger_source'] == self._TriggerSource.SW:
                return CameraModes.ASYNC_SW
            return CameraModes.ASYNC_HW
        return CameraModes.SYNC

    def set_mode(self, mode: Union[str, CameraModes]):
        if isinstance(mode, str):
            mode = CameraModes(mode)

        if mode is not CameraModes.SYNC :
            self.params['trigger_mode'] = self._TriggerMode.ON
        else:
            self.params['trigger_mode'] = self._TriggerMode.OFF

        if mode is CameraModes.ASYNC_SW:
            self.params['trigger_source'] = self._TriggerSource.SW
        elif mode is CameraModes.ASYNC_HW:
            self.params['trigger_source'] = self._TriggerSource.HW

        self.apply_params()

    # SYNCHRONOUS

    def _get_frame_generator(self, n_frames: int=None, timeout_ms: int=0):
        """Creates a generator that will produce the frames"""
        idx = 0
        t_start = time.time()
        self._setup_frame_generator(n_frames, timeout_ms)
        try:
            while (n_frames is None) or idx < n_frames:
                buffer = np.zeros((1,1,1))
                status = FrameStatus.ERROR
                try:
                    buffer = np.copy(self._fetch_buffer(timeout_ms))
                    idx += 1
                    status = FrameStatus.SUCCESS
                except CameraTimeout:
                    status = FrameStatus.TIMEOUT
                except CameraError:
                    status = FrameStatus.ERROR
                except Exception as exc:
                    print(repr(exc), flush=True)
                finally:
                    t_acquired = time.time() - t_start
                    yield Frame(status, buffer, idx, t_acquired)
        finally:
            self._cleanup_frame_generator()

    def _setup_frame_generator(self, n_frames: int, timeout_ms: int):
        """Eventual setup for the frame generator"""

    def _cleanup_frame_generator(self):
        """Eventual cleanup for the frame generator"""

    @abstractmethod
    def _fetch_buffer(self, timeout_ms):
        """Camera specific method to fetch buffer content"""

    def _start_acquisition(self):
        """Camera specific code to start the acquisition"""

    def _stop_acquisition(self):
        """Camera specific code to stop the acquisition"""

    def _record_synchronous(self):
        if not self._is_recording:
            self._start_acquisition()
            limit = self.params['n_frames'] if self.params['acquisition_mode'] == self._AcquisitionMode.MULTIFRAME \
                                            else None
            self._frame_generator = self._get_frame_generator(n_frames=limit,
                                                            timeout_ms=self._frame_timeout_ms)
            self._is_recording = True

    def _stop_record_synchronous(self):
        if self._is_recording:
            self._frame_generator.close()
            self._stop_acquisition()
            self._is_recording = False

    def get_frame(self):
        """Try to get a frame from the camera
        Only works with synchronous acquisition"""
        try:
            return next(self._frame_generator)
        except StopIteration as exc:
            raise CameraGeneratorStopped from exc

    def _set_synchronous_mode(self):
        self.record = self._record_synchronous
        self.stop = self._stop_record_synchronous
    
    # ASYNCHRONOUS

    def _record_asynchronous(self):
        if not self._is_recording:
            if self._asynchronous_callback is not None:
                self._start_streaming(self._asynchronous_callback)
                self._is_recording = True

    def _stop_record_asynchronous(self):
        if self._is_recording:
            self._stop_streaming()
            self._is_recording = False

    def _set_asynchronous_mode(self):
        self.record = self._record_asynchronous
        self.stop = self._stop_record_asynchronous
    
    def set_asynchronous_callback(self, callback):
        self._asynchronous_callback = callback

    def _start_streaming(self, callback: Callable):
        """Start asynchronous acquisition"""
        raise NotImplementedError
    
    def _stop_streaming(self):
        """Stop asynchronous acquisition"""
        raise NotImplementedError

    def emit_software_trigger(self):
        raise NotImplementedError
