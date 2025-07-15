from importlib import import_module
from dataclasses import dataclass
from application.abstract_interface import Interface
from typing import List


@dataclass
class ClassLoader:
    module_name: str
    class_name: str

    def load_class(self, module_folder=""):
        module = import_module(module_folder + self.module_name)
        return getattr(module, self.class_name)


class InterfaceFactory:
    """Exposes the available interfaces and allows to load them on a per-need basis"""

    interfaces = {'opencv': ClassLoader('opencv_cam', 'OpenCVCamInterface'),
                  'genicam': ClassLoader('genicam_cam', 'GenICamInterface'),
                  'pco': ClassLoader('pco_cam', 'PCOInterface'),
                  'avt': ClassLoader('avt_cam', 'AVTInterface'),
                  'pvcam': ClassLoader('pv_cam', 'PVCamInterface'),
                  'hamamatsu': ClassLoader('hamamatsu_cam', "HamamatsuInterface")
                  }

    def get_interface(self, interface_name: str) -> Interface:
        return self.interfaces[interface_name].load_class('application.cams.')

    def list_available_interfaces(self) -> List[str]:
        return [interface_name for interface_name in self.interfaces]