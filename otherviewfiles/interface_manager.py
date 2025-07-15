from multiprocessing import Process, Queue, Event
from threading import RLock as ThreadLock
import time
import queue
from concurrent.futures import ThreadPoolExecutor
from application.acquisition_handler import AcquisitionHandler
from application.utils import for_all_methods, print_unhandled_exception
from application.file_writer import FileWriterFactory
from application.abstract_interface import Interface


@for_all_methods(print_unhandled_exception)
class InterfaceManager(Process):
    """Abstract interface class"""

    def __init__(self, interface: Interface) -> None:
        super().__init__()

        self.interface = interface
        self.writer_factory = FileWriterFactory()

        self._start_flag = Event()
        self._close_flag = Event()
        self._shutdown_completed = Event()

        self._cam_requested = Event()
        self._cam_created = Event()

        self._acq_handlers = {}  # TODO decouple handler and cameras,
                                 # should be possible to access camera 'directly'

        self._command_id = 0

        self._command_queues = Queue()
        self._response_queues = Queue()
        self._responses = {}

        self._init_queue = Queue()
        self._id_queue = Queue()

        self.start()

    def start(self) -> None:
        super().start()
        self._start_flag.wait()
    
    def close(self):
        self._close_flag.set()
        self._shutdown_completed.wait()
        super().join()
        super().close()

    def run(self) -> None:
        with self.interface:
            self._start_flag.set()
            while not self._close_flag.is_set():
                self._setup_acquisition_handler_from_queue_if_requested()
                self._process_camera_commands()
                self._process_acquisition_handlers()
            self._close_acquisition_handlers()
        self._shutdown_completed.set()

    def _process_acquisition_handlers(self):
        for acq_handler in self._acq_handlers.values():
            if not hasattr(acq_handler, "processor"): # can remove 65 66
                acq_handler.processor = acq_handler._process()
            next(acq_handler.processor)
        if self._are_all_acquisitions_idle():
            time.sleep(0.001)  # this 1ms sleep avoids using a full core at no load,
                               # actual value slept is 1-2ms

    def _are_all_acquisitions_idle(self):
        for acq_handler in self._acq_handlers.values():
            if acq_handler.start_trigger:
                return False
        return True

    def _setup_acquisition_handler_from_queue_if_requested(self):
        if self._cam_requested.is_set():
            try:
                cam_id, writer_dict = self._init_queue.get_nowait()
            except queue.Empty:
                pass
            else:
                self._setup_acquisition_handler(cam_id, writer_dict)
                self._cam_requested.clear()

    def _setup_acquisition_handler(self, requested_cam_id, writer_dict):
        cam = self.interface.get_camera(requested_cam_id)
        writer = self.writer_factory.get_writer(writer_dict)
        cam_id = cam.id
        self._id_queue.put(cam_id)
        self._acq_handlers[cam_id] = AcquisitionHandler(cam, writer)
        self._cam_created.set()

    def get_proxy_acquisition_handler(self, cam_id, writer_dict):
        print('in get proxy acquisition handler')
        self._cam_created.clear()
        self._init_queue.put_nowait([cam_id, writer_dict])
        self._cam_requested.set()
        self._cam_created.wait()
        cam_id = self._id_queue.get()
        return ProxyAcquisitionHandler(self, cam_id)

    def _process_camera_commands(self):
        while True:
            try:
                command_id, cam_id, command, args, kwargs = self._command_queues.get_nowait()
            except queue.Empty:
                break
            else:
                ret = self._process_command(cam_id, command, args, kwargs)
                self._response_queues.put([command_id, ret])

    def command_acquisition_handler(self, cam_id, command, command_lock, response_lock, *args, **kwargs):
        with command_lock:
            self._command_id += 1
            command_id = self._command_id
        self._command_queues.put([command_id, cam_id, command, args, kwargs])
        while True:
            try:
                response_id, ret = self._response_queues.get_nowait() 
            except queue.Empty:
                pass
            else:
                if response_id == command_id:
                    return ret
                with response_lock:
                    self._responses[response_id] = ret
            with response_lock:
                if command_id in self._responses:
                    return self._responses.pop(command_id)

    def _process_command(self, cam_id, command, args, kwargs):
        if cam_id not in self._acq_handlers:
            print('Error in _process_command, cam_id absent!', flush=True)
            return
        attr = getattr(self._acq_handlers[cam_id], command)
        if callable(attr):
            return attr(*args, **kwargs)
        return attr

    def _close_acquisition_handlers(self):
        """Closes the camera handlers"""
        for acq_handler in self._acq_handlers.values():
            acq_handler.close()


class ProxyAcquisitionHandler:
    """This is a proxy for the acquisition handler class
    The reason it is called a proxy is that we are manipulating an object in a different process.
    This requires communicating using queues and using futures, which have to be associated to callbacks,
    in order to keep the processing responsive.
    
    To be clear, this class allows to use the AcquisitionHandler class with direct methods calls,
    such as 'acq_handler.enable_saving()' (through the 'command_acquisition_handler' interface method).
    NB: this class does NOT allow to access AcquisitionHandler attributes directly."""
    def __init__(self, interface, cam_id) -> None:
        self.interface = interface
        self.cam_id = cam_id
        self._command_lock = ThreadLock()
        self._response_lock = ThreadLock()
        self.executor = ThreadPoolExecutor(thread_name_prefix=f'{self.__class__.__name__}')

    def __getattr__(self, attr):
        def wrapped_method(*args, **kwargs):
            return self.executor.submit(self.interface.command_acquisition_handler,
                                        self.cam_id,
                                        attr,
                                        self._command_lock, self._response_lock,
                                        *args, **kwargs
                                        )
        return wrapped_method
