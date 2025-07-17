import sys
import os
import time
from os import getcwd, path
from os.path import dirname, join
from functools import lru_cache
import logging

import numpy as np
from PyQt5 import uic
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QAction, QApplication, QMainWindow, QMessageBox,
                             QMdiSubWindow, QWidget)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from .image_processing import (HistogramStretcher, ImageFlipper,
                               ImageProcessingPipeline, ImageRotator)
from udp_socket import UDPSocket
from utils import display
from camera_handler import CameraHandler

# Re-use the existing CamWidget implementation (and its helpers) from the legacy GUI.
from view.widgets import CamWidget

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

dirpath = dirname(path.realpath(__file__))
legacy_icon_path = join(dirname(dirpath), 'view', 'icon', 'pycams.png')

# -----------------------------------------------------------------------------
# Logging Handler for GUI
# -----------------------------------------------------------------------------
class QtLogHandler(logging.Handler):
    """A custom logging handler that emits a signal for each log record."""
    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    def emit(self, record):
        msg = self.format(record)
        self.parent.log_message.emit(msg)

class PyCamsWindow(QMainWindow):
    """Next-gen wrapper that loads the *new* main-window .ui while keeping the
    proven backend logic from the legacy GUI.
    """
    log_message = pyqtSignal(str)
    _udp_server_created = False  # Re-use the one-per-process server guard

    def __init__(self, preferences=None):
        # Keep the same public API expected by the rest of the app
        self.preferences = preferences if preferences is not None else {}

        super().__init__()

        # Load the *new* Qt Designer layout
        uic.loadUi(join(dirpath, 'UI_pycams.ui'), self)

        # --- Logging Setup ---
        # self.log_message.connect(self.log_textEdit.append)
        handler = QtLogHandler(self)
        # Optional: Add formatting to the handler
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
                                      datefmt='%H:%M:%S')
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        display("NeuCams started.")

        # Reuse the existing icon so we do not need to copy the whole folder
        # self.setWindowIcon(QIcon(legacy_icon_path))

        # ------------------------------------------------------------------
        # Camera widgets setup (logic copied from legacy implementation)
        # ------------------------------------------------------------------
        self.cam_widgets = []
        for cam in self.preferences.get('cams', []):
            if cam.get('driver') in ['avt', 'pco', 'genicam']:
                self._setup_camera(cam)

        # Arrange the camera windows in a grid
        self.mdiArea.tileSubWindows()

        # ------------------------------------------------------------------
        # Optional UDP server (one per process)
        # ------------------------------------------------------------------
        server_params = self.preferences.get('server_params', None)
        if (server_params is not None and
                not hasattr(PyCamsWindow, '_udp_server_created')):
            server_type = server_params.get('server', None)
            if server_type == 'udp':
                self.server = UDPSocket((server_params.get('server_ip', '0.0.0.0'),
                                         server_params.get('server_port', 9999)))
                self._timer = QTimer(self)
                self._timer.timeout.connect(self._process_server_messages)
                self._timer.start(server_params.get('server_refresh_time', 100))
                PyCamsWindow._udp_server_created = True

        # Misc UI initialisation
        self.mdiArea.setActivationOrder(1)
        self.menuView.triggered[QAction].connect(self._view_menu_actions)

        self.show()

    # ------------------------------------------------------------------
    # Legacy helpers copied / simplified from the original widgets.py
    # ------------------------------------------------------------------

    def _setup_camera(self, cam_dict):
        if 'settings_file' in cam_dict.get('params', {}):
            cam_dict['params']['settings_file'] = join(dirname(getcwd()),
                                                       'configs',
                                                       cam_dict['params']['settings_file'])
        writer_dict = {**self.preferences.get('recorder_params', {}),
                       **cam_dict.get('recorder_params', {})}
        cam_handler = CameraHandler(cam_dict, writer_dict)
        if cam_handler.camera_connected:
            cam_handler.start()
            widget = CamWidget(cam_handler)
            self.cam_widgets.append(widget)
            self._add_widget(cam_dict['description'], widget)

    def _add_widget(self, name, widget):
        active_subwindows = [e.objectName() for e in self.mdiArea.subWindowList()]
        if name not in active_subwindows:
            subwindow = QMdiSubWindow(self.mdiArea)
            subwindow.setWindowTitle(name)
            subwindow.setObjectName(name)
            subwindow.setWidget(widget)
            subwindow.resize(widget.minimumSize().width() + 40,
                             widget.minimumSize().height() + 40)
            subwindow.show()
            subwindow.setProperty("center", True)
        else:
            widget.show()

    # ------------------------------------------------------------------
    # UDP helper
    # ------------------------------------------------------------------

    def _process_server_messages(self):
        ret, msg, address = self.server.receive()
        if not ret:
            return

        action, *value = [i.lower() for i in msg.split('=')]

        if action == 'ping':
            display(f'Server got pinged [{address}]')
            self.server.send('pong', address)

        elif action == 'folder':
            self._set_save_path(value)
            display(f'Folder changed to {value} [{address}]')
            self.server.send('ok=folder', address)

        elif action == 'start':
            display(f'Starting triggered cameras [{address}]')
            for cam_widget in self.cam_widgets:
                if getattr(cam_widget, 'is_triggered', False):
                    cam_widget.start_cam()
            self.server.send('ok=start', address)

        elif action == 'stop':
            display(f'Stopping triggered cameras [{address}]')
            for cam_widget in self.cam_widgets:
                if getattr(cam_widget, 'is_triggered', False):
                    cam_widget.stop_cam()
            self.server.send('ok=stop', address)

        elif action == 'done?':
            cam_descr = value[0] if value else ''
            for cam_widget in self.cam_widgets:
                if cam_widget.cam_handler.cam_dict.get('description') == cam_descr:
                    status = cam_widget.cam_handler.is_acquisition_done.is_set()
                    self.server.send(f'done?={status}', address)
                    return
            self.server.send('done?=camera not found', address)

        elif action == 'quit':
            display(f'Exiting [{address}]')
            self.server.send('ok=bye', address)
            self.close()

    # ------------------------------------------------------------------
    # Utility helpers (unchanged)
    # ------------------------------------------------------------------

    def _set_save_path(self, save_path):
        if os.path.sep == '/':
            save_path = save_path.replace('\\', os.path.sep)
        save_path = save_path.strip(' ')
        for cam_widget in self.cam_widgets:
            cam_widget.cam_handler.set_folder_path(save_path)

    def _view_menu_actions(self, q):
        if q.text() == 'Subwindow View':
            self.mdiArea.setViewMode(0)
        if q.text() == 'Tabbed View':
            self.mdiArea.setViewMode(1)
        elif q.text() == 'Cascade View':
            self.mdiArea.setViewMode(0)
            self.mdiArea.cascadeSubWindows()
        elif q.text() == 'Tile View':
            self.mdiArea.setViewMode(0)
            self.mdiArea.tileSubWindows()

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Window Close',
                                     'Are you sure you want to close the window?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            event.accept()
            self.close()
        else:
            event.ignore()

    def close(self):
        for cam_widget in self.cam_widgets:
            cam_widget.cam_handler.close()
        time.sleep(0.5)
        display("PyCams out, bye!")
        QApplication.quit()
        sys.exit() 