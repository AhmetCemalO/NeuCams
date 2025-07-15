from abc import ABC, abstractmethod
from application.utils import for_all_methods, print_unhandled_exception


@for_all_methods(print_unhandled_exception)
class Interface(ABC):
    """Abstract interface class"""

    def list_available_cameras(self):
        """List available cameras"""
        raise NotImplementedError

    def list_available_camera_ids(self):
        """List available camera ids"""
        raise NotImplementedError

    def __enter__(self):
        self.open()

    def __exit__(self, _exc_type, _exc_value, _exc_traceback):
        self.close()

    @abstractmethod
    def open(self):
        """Opens the interface"""

    @abstractmethod
    def close(self):
        """Closes the interface"""

    @abstractmethod
    def get_camera(self, cam_id=None):
        """Initialize a camera"""
