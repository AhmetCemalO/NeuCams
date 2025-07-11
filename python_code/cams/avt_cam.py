# avt_cam.py  –  Vimba X / vmbpy-compatible
import numpy as np
from multiprocessing import shared_memory
from vmbpy import (
    VmbSystem,
    Frame, Camera, PixelFormat,
    VmbFeatureError, VmbTimeout,
)
from .generic_cam import GenericCam
from utils import display


# ----------------------------------------------------------------------
# helper: attribute-style feature setter
def _set(cam: Camera, feat_name: str, value):
    """Set any feature by name."""
    try:
        getattr(cam, feat_name).set(value)
    except AttributeError as e:
        raise VmbFeatureError(f"Feature '{feat_name}' not found") from e
# ----------------------------------------------------------------------


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
    """Return ([ids], [pretty strings]) for all connected Allied Vision cams."""
    with VmbSystem.get_instance() as vmb:
        ids, infos = [], []
        for c in vmb.get_all_cameras():
            ids.append(c.get_id())
            infos.append(f"{c.get_model()} {c.get_serial()} {c.get_id()}")
    return ids, infos


class AVTCam(GenericCam):
    """Allied Vision camera wrapper updated for vmbpy."""

    timeout = 2_000  # ms

    # ------------------------------------------------------------------
    def __init__(self, cam_id=None, params=None, format=None):
        ids, _ = AVT_get_ids()
        if cam_id is None and ids:
            cam_id = ids[0]

        super().__init__(
            name="AVT",
            cam_id=cam_id,
            params=params or {},
            format=format or {},
        )

        default_params = {
            "exposure": 29_000,              # µs
            "frame_rate": 30,
            "gain": 10,
            "gain_auto": False,
            "acquisition_mode": "Continuous",
            "n_frames": 1,
            "triggered": False,
            "triggerSource": "Line1",
            "triggerMode": "LevelHigh",
            "triggerSelector": "FrameStart",
        }
        self.exposed_params = [
            "frame_rate", "gain", "exposure", "gain_auto",
            "triggered", "acquisition_mode", "n_frames",
        ]
        self.params = {**default_params, **self.params}

        default_format = {"dtype": np.uint8}
        self.format = {**default_format, **self.format}

        # internal state
        self.cam_handle = None
        self.vimba = None
        self.frame_generator = None
        self.is_recording = False

    # ------------------------------------------------------------------
    # connection helpers
    # ------------------------------------------------------------------
    def is_connected(self):
        ids, _ = AVT_get_ids()
        if self.cam_id in ids:
            display(f"Requested AVT cam detected: {self.cam_id}")
            return True
        display(f"Requested AVT cam **not** detected: {self.cam_id}", level="error")
        return False

    # ------------------------------------------------------------------
    # context management
    # ------------------------------------------------------------------
    def __enter__(self):
        if not self.is_connected():
            return self

        self.vimba = VmbSystem.get_instance()
        self.vimba.__enter__()

        for cam in self.vimba.get_all_cameras():
            if cam.get_id() == self.cam_id:
                self.cam_handle = cam
                break
        if self.cam_handle is None:
            display(f"Camera {self.cam_id} vanished.", level="error")
            return self

        self.cam_handle.__enter__()
        self.apply_params()
        self._record()
        self._init_format()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.is_recording:
                self.stop()
            if self.cam_handle:
                self.cam_handle.__exit__(exc_type, exc_val, exc_tb)
        finally:
            if self.vimba:
                self.vimba.__exit__(exc_type, exc_val, exc_tb)
        return True

    # ------------------------------------------------------------------
    # parameter handling
    # ------------------------------------------------------------------
    def apply_params(self):
        if not self.cam_handle:
            display("apply_params() called before camera opened", level="warning")
            return

        p = self.params
        try:
            _set(self.cam_handle, "EventNotification", "On")
            self.cam_handle.set_pixel_format(PixelFormat.Mono8)

            _set(self.cam_handle, "SyncOutSelector", "SyncOut1")
            _set(self.cam_handle, "SyncOutSource", "FrameReadout")

            # ⬇⬇ updated names ⬇⬇
            _set(self.cam_handle, "AcquisitionFrameRateAbs", p["frame_rate"])
            _set(self.cam_handle, "ExposureTimeAbs",       p["exposure"])
            # ⬆⬆ updated names ⬆⬆

            _set(self.cam_handle, "Gain",      p["gain"])
            _set(self.cam_handle, "GainAuto", "Once" if p["gain_auto"] else "Off")
            _set(self.cam_handle, "ExposureMode", "Timed")

        except VmbFeatureError as err:
            display(f"Error applying parameters: {err}", level="warning")

    # ------------------------------------------------------------------
    # acquisition
    # ------------------------------------------------------------------
    def _record(self):
        """Create a blocking generator that yields (shm.name, shape, dtype, meta)."""
        self.is_recording = True

        def _gen():
            while self.is_recording:
                try:
                    if self.cam_handle is not None:
                        frame = self.cam_handle.get_frame(timeout_ms=self.timeout)
                    else:
                        display("Camera handle is None in _record().", level="error")
                        break
                except VmbTimeout:
                    continue
                if frame is not None:
                    arr = frame.as_numpy_ndarray()
                    # Allocate shared memory for the frame
                    shm = shared_memory.SharedMemory(create=True, size=arr.nbytes)
                    shm_arr = np.ndarray(arr.shape, dtype=arr.dtype, buffer=shm.buf)
                    shm_arr[:] = arr  # Copy frame data into shared memory
                    meta = (frame.get_id(), frame.get_timestamp())
                    # Yield the shared memory name, shape, dtype, and meta
                    yield (shm.name, arr.shape, str(arr.dtype), meta)
                else:
                    yield None, "no frame"
        self.frame_generator = _gen()

    # Helper for consumer to reconstruct frame from shared memory
    @staticmethod
    def frame_from_shm(shm_name, shape, dtype):
        shm = shared_memory.SharedMemory(name=shm_name)
        arr = np.ndarray(shape, dtype=np.dtype(dtype), buffer=shm.buf)
        return arr, shm

    def stop(self):
        self.is_recording = False
        display("AVT cam stopped.")

    # ------------------------------------------------------------------
    # data access
    # ------------------------------------------------------------------
    def image(self):
        if not self.is_recording:
            display("image() called while not recording.", level="warning")
            return None, "not recording"
        # Ensure frame_generator is initialized and is a generator
        if self.frame_generator is None:
            self._record()
        if not hasattr(self.frame_generator, '__next__'):
            display("frame_generator is not a generator object.", level="error")
            return None, "generator error"
        try:
            result = next(self.frame_generator)
            # Handle shared memory tuple
            if isinstance(result, tuple) and len(result) == 4 and isinstance(result[0], str):
                shm_name, shape, dtype, meta = result
                img, shm = self.frame_from_shm(shm_name, shape, dtype)
                # Optionally, copy to detach from shared memory and clean up
                img_copy = np.array(img, copy=True)
                shm.close()
                shm.unlink()
                return img_copy, meta
            else:
                img, meta = result
                return img, meta
        except StopIteration:
            return None, "stop"
        except Exception as err:
            display(f"Error fetching image: {err}", level="error")
            return None, "error"

    # alias for GenericCam compatibility
    close = stop
