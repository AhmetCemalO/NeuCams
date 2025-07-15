import sys
from os import getcwd, path
import os
from os.path import join, dirname
import numpy as np
import cv2
import time
from functools import lru_cache
from collections import deque
from PyQt5 import uic
from PyQt5.QtGui import QImage, QPixmap, QIcon
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QMessageBox,
                             QMdiSubWindow, QAction, QComboBox, QSpinBox,
                             QCheckBox, QFileDialog)
from PyQt5.QtCore import Qt, QTimer

from udp_socket import UDPSocket
from utils import display
from camera_handler import CameraHandler
from cams.avt_cam import AVTCam
from view_ng.components import DisplaySettingsWidget, ImageProcessingWidget
from view_ng.base_widgets import BaseCameraWidget, nparray_to_qimg


dirpath = dirname(path.realpath(__file__))

class PyCamsWindow(QMainWindow):
    _udp_server_created = False

    def __init__(self, preferences = None):
        self.preferences = preferences if preferences is not None else {}
        
        super().__init__()
        
        uic.loadUi(join(dirpath, 'UI_pycams.ui'), self)
        
        self.setWindowIcon(QIcon(dirpath + '/icon/pycams.png'))
        
        self.cam_widgets = []
        for cam in self.preferences.get('cams', []):
            if cam['driver'] in ['avt', 'pco', 'genicam']:
                self.setup_camera(cam)
        
        # Only create the UDP server once, not per camera
        server_params = self.preferences.get('server_params', None)
        if server_params is not None and not hasattr(PyCamsWindow, '_udp_server_created'):
            server = server_params.get('server', None)
            if server == "udp":
                self.server = UDPSocket((server_params.get('server_ip', '0.0.0.0'), server_params.get('server_port', 9999)))
                self._timer = QTimer(self)
                self._timer.timeout.connect(self.process_server_messages)
                self._timer.start(server_params.get('server_refresh_time', 100))
                PyCamsWindow._udp_server_created = True  # Mark as created
        
        self.mdiArea.setActivationOrder(1)
        
        self.menuView.triggered[QAction].connect(self.viewMenuActions)
        
        self.show()
    
    def set_save_path(self, save_path):
        if os.path.sep == '/': # Makes sure that the experiment name has the right slashes.
            save_path = save_path.replace('\\',os.path.sep)
        save_path = save_path.strip(' ')
        for cam_widget in self.cam_widgets:
            cam_widget.cam_handler.set_folder_path(save_path)
        
    def process_server_messages(self):
        ret, msg, address = self.server.receive()
        if ret:
            action, *value = [i.lower() for i in msg.split('=')]
            
            if action == 'ping':
                display(f'Server got pinged [{address}]')
                self.server.send('pong',address)
                
            elif action == 'folder':
                self.set_save_path(value)
                display(f'Folder changed to {value} [{address}]')
                self.server.send('ok=folder',address)
                
            elif action == 'start':
                display(f'Starting triggered cameras [{address}]')
                for cam_widget in self.cam_widgets:
                    if cam_widget.is_triggered:
                        cam_widget.start_cam()
                self.server.send('ok=start',address)
                
            elif action == 'stop':
                display(f'Stopping triggered cameras [{address}]')
                for cam_widget in self.cam_widgets:
                    if cam_widget.is_triggered:
                        cam_widget.stop_cam()
                self.server.send('ok=stop',address)
                
            elif action == 'done?':
                cam_descr = value[0]
                for cam_widget in self.cam_widgets:
                    if cam_widget.cam_handler.cam_dict['description'] == cam_descr:
                        display(f'Received status request from [{address}] \nCam {cam_descr} {action} status: {cam_widget.cam_handler.is_acquisition_done.is_set()}')
                        self.server.send(f'done?={cam_widget.cam_handler.is_acquisition_done.is_set()}',address)
                        return
                self.server.send('done?=camera not found',address)
            
            elif action == 'quit':
                display(f'Exiting [{address}]')
                self.server.send('ok=bye',address)
                self.close()
        
    def setup_camera(self, cam_dict):
        if 'settings_file' in cam_dict.get('params', {}):
            cam_dict['params']['settings_file'] = join(dirname(getcwd()), 'configs', cam_dict['params']['settings_file'])
        writer_dict = {**self.preferences.get('recorder_params', {}), **cam_dict.get('recorder_params', {})}
        cam_handler = CameraHandler(cam_dict, writer_dict)
        if cam_handler.camera_connected:
            cam_handler.start()
            widget = CamWidget(cam_handler)
            self.cam_widgets.append(widget)
            self.setup_widget(cam_dict['description'], widget)
        
    def setup_widget(self, name, widget):
        """
        Adds the supplied widget with the supplied name in the main window
        Checks if widget is already existing but hidden

        :param name: Widget name in main window
        :type name: string
        :param widget: Widget
        :type widget: QWidget
        """
        active_subwindows = [e.objectName() for e in self.mdiArea.subWindowList()]
        if name not in active_subwindows:
            subwindow = QMdiSubWindow(self.mdiArea)
            subwindow.setWindowTitle(name)
            subwindow.setObjectName(name)
            subwindow.setWidget(widget)
            subwindow.resize(widget.minimumSize().width() + 40,widget.minimumSize().height() + 40)
            subwindow.show()
            subwindow.setProperty("center", True)
        else:
            widget.show()
    
    def viewMenuActions(self,q):
        """
        Handles the click event from the View menu.

        :param q:
        :type q: QAction
        """
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
    
    def closeEvent(self, event):
        """
        Handles the click event from the top right X to close.
        Asks for confirmation before it does.
        """
        reply = QMessageBox.question(self, 'Window Close', 'Are you sure you want to close the window?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            event.accept()
            self.close()
        else:
            event.ignore()

    def close(self):
        """
        Clean up non GUI objects
        """
        for cam_widget in self.cam_widgets:
            cam_widget.cam_handler.close()
        time.sleep(0.5)
        display("PyCams out, bye!")
        QApplication.quit()
        sys.exit()


class CamWidget(BaseCameraWidget):
    def __init__(self, cam_handler=None):
        super().__init__(cam_handler)
        uic.loadUi(join(dirpath, 'UI_cam.ui'), self)

        # --- FPS computation ---
        self._fps_deque = deque(maxlen=10) # Store last 10 FPS values

        # --- Connections ---
        self.start_stop_pushButton.clicked.connect(self._start_stop_toggled)
        self.record_checkBox.stateChanged.connect(self._record)

        self.camera_settings_pushButton.clicked.connect(self._toggle_cam_settings)
        self.display_settings_pushButton.clicked.connect(self._toggle_display_settings)
        self.image_processing_pushButton.clicked.connect(self._toggle_img_processing_settings)

        # --- Child widgets ---
        self.cam_settings = CamSettingsWidget(self, self.cam_handler)
        self.display_settings = DisplaySettingsWidget(self)
        self.img_processing_settings = ImageProcessingWidget(self)

        # --- Image processing pipeline ---
        # The new stages from the ImageProcessingWidget should be inserted
        # at the beginning of the pipeline, before the contrast stretcher.
        if hasattr(self.display_settings, 'pipeline'):
            pipeline = self.display_settings.pipeline
            # This is a bit of a hack; a better design would be a dedicated
            # pipeline manager class. For now, we manually insert at the start.
            pipeline.stages.insert(0, self.img_processing_settings.subtract_stage)
            pipeline.stages.insert(0, self.img_processing_settings.blur_stage)

    def _update(self):
        if self.cam_handler is None:
            return

        # Update file path display
        dest = self.cam_handler.get_filepath()
        self.save_location_label.setText('Filepath: ' + dest)

        # Process new image if available
        if self.frame_nr != self.cam_handler.total_frames.value:
            img = self.cam_handler.get_image()
            if isinstance(img, tuple) and len(img) == 3 and isinstance(img[0], str):
                shm_name, shape, dtype = img
                img, shm = AVTCam.frame_from_shm(shm_name, shape, dtype)
                img = np.array(img, copy=True)
                shm.close()
                shm.unlink()
            self.original_img = np.copy(img)
            self.is_img_processed = False
            self.frame_nr = self.cam_handler.total_frames.value

        # Update FPS and frame count labels
        self._update_stats()

        # Update camera state (e.g., start/stop button text)
        if self.cam_handler.start_trigger.is_set() and not self.cam_handler.stop_trigger.is_set():
            self._set_stop_text()
        else:
            self._set_start_text()

        # Update image display
        if self.display_settings.isVisible():
            self.is_img_processed = False
        self._update_img()
        super().update()

    def _update_stats(self):
        current_time = time.time()
        current_frame = self.cam_handler.total_frames.value
        dt = current_time - self._prev_time
        df = current_frame - self._prev_frame_nr

        if dt >= 0.5 and df > 0: # Update more frequently
            fps = df / dt
            self._fps_deque.append(fps)
            avg_fps = np.mean(self._fps_deque)
            self.fps_label.setText(f"{avg_fps:.1f} fps")
            self._prev_time = current_time
            self._prev_frame_nr = current_frame
        self.frame_nr_label.setText(f"frame: {current_frame}")

    def _update_img(self):
        if self.original_img is not None:
            if not self.is_img_processed:
                self.processed_img = self.display_settings.process_img(self.original_img)
                self.is_img_processed = True
            
            pixmap = QPixmap(nparray_to_qimg(self.processed_img))
            pixmap = pixmap.scaled(self.img_label.width(), self.img_label.height(),
                                   self.AR_policy, Qt.FastTransformation)
            self.img_label.setPixmap(pixmap)

    def _start_stop_toggled(self, checked):
        if checked:
            self.start_cam()
        else:
            self.stop_cam()

    def _set_start_text(self):
        self.start_stop_pushButton.setText("Start")
        self.start_stop_pushButton.setChecked(False)
        self.record_checkBox.setEnabled(True)

    def _set_stop_text(self):
        self.start_stop_pushButton.setText("Stop")
        self.start_stop_pushButton.setChecked(True)
        self.record_checkBox.setEnabled(False)

    def _record(self, state):
        if state:
            self.cam_handler.start_saving()
        else:
            self.cam_handler.stop_saving()

    def _toggle_img_processing_settings(self):
        self.img_processing_settings.setVisible(not self.img_processing_settings.isVisible())
        
class CamSettingsWidget(QWidget):
    def __init__(self, parent, cam_handler=None):
        super().__init__(parent)

        self.setWindowFlag(Qt.Window)
        uic.loadUi(join(dirpath, 'UI_cam_settings.ui'), self)

        self.cam_handler = cam_handler

        # --- Connections ---
        self.apply_pushButton.clicked.connect(self._apply_settings)
        self.load_settings_pushButton.clicked.connect(self._load_settings)
        self.save_settings_pushButton.clicked.connect(self._save_settings)

        self.autogain_checkBox.stateChanged.connect(self._toggle_gain_spinBox)
        self.mode_comboBox.currentTextChanged.connect(self._toggle_nframes_spinBox)

        # --- Widgets dictionary ---
        self.settings = {
            'frame_rate': self.framerate_spinBox,
            'exposure': self.exposure_spinBox,
            'gain': self.gain_spinBox,
            'gain_auto': self.autogain_checkBox,
            'binning': self.binning_comboBox,
            'acquisition_mode': self.mode_comboBox,
            'n_frames': self.nframes_spinBox
        }

    def _toggle_gain_spinBox(self, state):
        self.gain_spinBox.setEnabled(not state)

    def _toggle_nframes_spinBox(self, text):
        self.nframes_spinBox.setEnabled(text != "Continuous")

    def _apply_settings(self):
        for setting, widget in self.settings.items():
            if not widget.isEnabled():
                continue

            if isinstance(widget, QSpinBox):
                val = widget.value()
            elif isinstance(widget, QComboBox):
                val = widget.currentText()
            elif isinstance(widget, QCheckBox):
                val = widget.isChecked()
            else:
                continue
            self.cam_handler.set_cam_param(setting, val)

    def init_fields(self):
        self.cam_handler.query_cam_params()
        while not self.cam_handler.cam_param_get_flag.is_set():
            time.sleep(0.01)
        params = self.cam_handler.get_cam_params()
        if params is None:
            return

        for setting, widget in self.settings.items():
            is_setting_available = setting in params
            widget.setEnabled(is_setting_available)
            if not is_setting_available:
                continue

            value = params[setting]
            if isinstance(widget, QSpinBox):
                widget.setValue(value)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            elif isinstance(widget, QCheckBox):
                widget.setChecked(value)

        self._toggle_gain_spinBox(self.autogain_checkBox.isChecked())
        self._toggle_nframes_spinBox(self.mode_comboBox.currentText())

    def _load_settings(self):
        # Note: XML support can be added here if needed
        fileName, _ = QFileDialog.getOpenFileName(
            self, "Load Settings", "", "JSON Files (*.json)")
        if fileName:
            self.cam_handler.load_cam_settings(fileName)
            self.init_fields()  # Refresh display

    def _save_settings(self):
        fileName, _ = QFileDialog.getSaveFileName(
            self, "Save Settings", "", "JSON Files (*.json)")
        if fileName:
            self.cam_handler.save_cam_settings(fileName)
        