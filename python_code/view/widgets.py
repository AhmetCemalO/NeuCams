import sys
from os import getcwd
from os import path
from os.path import join, dirname
import numpy as np
import cv2
import time
from functools import lru_cache
from PyQt5 import uic
from PyQt5.QtGui import QImage, QPixmap, QIcon
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QMessageBox, QMdiSubWindow, QAction, QComboBox, QSpinBox, QCheckBox
from PyQt5.QtCore import Qt, QTimer

from udp_socket import UDPSocket
from utils import display
from camera_handler import CameraHandler
from cams.avt_cam import AVTCam

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


def nparray_to_qimg(img):
    height, width, n_chan = img.shape
    dtype = img.dtype
    if dtype == np.uint16:
        img = cv2.convertScaleAbs(img) #starting from pyqt 5.13 (not available yet) we could use Format_Grayscale16 to not have to do this conversion
    format = QImage.Format_Grayscale8 if n_chan == 1 else QImage.Format_RGB888
    bytesPerLine = n_chan * width
    return QImage(img.data, width, height, bytesPerLine, format)
        
class CamWidget(QWidget):
    def __init__(self, cam_handler = None):
        super().__init__()
        uic.loadUi(join(dirpath, 'UI_cam.ui'), self)
        
        self.cam_handler = cam_handler
        
        self._init_trigger_checkbox()
        self.is_triggered = self.trigger_checkBox.isChecked()
        
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(100)
        
        self.AR_policy = Qt.KeepAspectRatio
        
        self.original_img = None
        self.processed_img = None
        self.is_img_processed = False
        
        self.frame_nr = None
        
        self.start_stop_pushButton.clicked.connect(self._start_stop)
        self.record_checkBox.stateChanged.connect(self._record)
        self.trigger_checkBox.stateChanged.connect(self._trigger)
        self.keep_AR_checkBox.stateChanged.connect(self._pixmap_aspect_ratio)
        
        self.cam_settings = CamSettingsWidget(self, self.cam_handler)
        self.camera_settings_pushButton.clicked.connect(self._toggle_cam_settings)
        
        self.display_settings = DisplaySettingsWidget(self)
        self.display_settings_pushButton.clicked.connect(self._toggle_display_settings)
    
    def _update(self):
        if self.cam_handler is not None:
            dest = self.cam_handler.get_filepath()
            self.save_location_label.setText('Filepath: ' + dest)
            if self.frame_nr != self.cam_handler.total_frames.value:
                img = self.cam_handler.get_image()
                # Handle shared memory tuple from AVT
                if isinstance(img, tuple) and len(img) == 3 and isinstance(img[0], str):
                    shm_name, shape, dtype = img
                    img, shm = AVTCam.frame_from_shm(shm_name, shape, dtype)
                    img = np.array(img, copy=True)
                    shm.close()
                    shm.unlink()
                self.original_img = np.copy(img)
                self.is_img_processed = False
                self.frame_nr = self.cam_handler.total_frames.value
            if self.cam_handler.start_trigger.is_set() and not self.cam_handler.stop_trigger.is_set():
                self._set_stop_text()
            else:
                self._set_start_text()
        if self.display_settings.isVisible():
            self.is_img_processed = False
        self._update_img()
        super().update()
        
    def _update_img(self):
        if self.original_img is not None:
            self.processed_img = self.display_settings.process_img(self.original_img) if not self.is_img_processed else self.processed_img
            self.is_img_processed = True
            pixmap = QPixmap(nparray_to_qimg(self.processed_img))
            pixmap = pixmap.scaled(self.img_label.width(), self.img_label.height(), self.AR_policy, Qt.FastTransformation)
            self.img_label.setPixmap(pixmap)
    
    def _pixmap_aspect_ratio(self, state):
        self.AR_policy = Qt.KeepAspectRatio if state else Qt.IgnoreAspectRatio

    def resizeEvent(self, event):
        pixmap = self.img_label.pixmap()
        if pixmap is not None:
            self.img_label.setMinimumSize(1,1)
            pixmap = pixmap.scaled(self.img_label.width(), self.img_label.height(), self.AR_policy, Qt.FastTransformation)
            self.img_label.setPixmap(pixmap)

    def _start_stop(self):
        if self.start_stop_pushButton.text() == "Start":
            self.start_cam()
        else:
            self.stop_cam()
    
    def start_cam(self):
        if self.cam_handler is not None:
            ret = self.cam_handler.start_acquisition()
            if ret:
                self._set_stop_text()
        else:
            print("Could not start cam, camera already running", flush=True)
            
    def stop_cam(self):
        self.cam_handler.stop_acquisition()
        self._set_start_text()
    
    def _set_start_text(self):
        self.start_stop_pushButton.setText("Start")
        self.record_checkBox.setEnabled(True)
        self.trigger_checkBox.setEnabled(True)
        
    def _set_stop_text(self):
        self.start_stop_pushButton.setText("Stop")
        self.record_checkBox.setEnabled(False)
        self.trigger_checkBox.setEnabled(False)
        
    def _record(self, state):
        if state:
            self.cam_handler.start_saving()
        else:
            self.cam_handler.stop_saving()

    def _init_trigger_checkbox(self):
        self.cam_handler.query_cam_params()
        while not self.cam_handler.cam_param_get_flag.is_set():
            time.sleep(0.01)
        params = self.cam_handler.get_cam_params()
        if params is not None:
            is_setting_available = 'triggered' in params
            if is_setting_available:
                self.trigger_checkBox.setChecked(params['triggered'])
            else:
                self.trigger_checkBox.setEnabled(False)
                
    def _trigger(self, state):
        self.is_triggered = state
        self.cam_handler.set_cam_param('triggered', state)
        
    def _toggle_cam_settings(self):
        is_visible = self.cam_settings.isVisible()
        self.cam_settings.setVisible(not is_visible)
        if not is_visible:
            self.cam_settings.init_fields()
            
    def _toggle_display_settings(self):
        is_visible = self.display_settings.isVisible()
        self.display_settings.setVisible(not is_visible)

class CamSettingsWidget(QWidget):
    def __init__(self, parent, cam_handler = None):
        super().__init__(parent)
        
        self.setWindowFlag(Qt.Window)
        
        uic.loadUi(join(dirpath, 'UI_cam_settings.ui'), self)
        
        self.cam_handler = cam_handler
        
        self.apply_pushButton.clicked.connect(self._apply_settings)
        self.autogain_checkBox.stateChanged.connect(self._toggle_gain_spinBox)
        self.mode_comboBox.currentTextChanged.connect(self._toggle_nframes_spinBox)
        
        self.settings = {'frame_rate': self.framerate_spinBox,
                         'exposure': self.exposure_spinBox,
                         'gain': self.gain_spinBox,
                         'gain_auto' : self.autogain_checkBox,
                         'binning': self.binning_comboBox,
                         'acquisition_mode': self.mode_comboBox,
                         'n_frames': self.nframes_spinBox}
    
    def _toggle_gain_spinBox(self, state):
        self.gain_spinBox.setEnabled(not state)
    
    def _toggle_nframes_spinBox(self, text):
        self.nframes_spinBox.setEnabled(text != "Continuous")
            
    def _apply_settings(self):
        for setting in self.settings:
            widget = self.settings[setting]
            if widget.isEnabled():
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
        if params is not None:
            for setting in self.settings:
                is_setting_available = setting in params
                widget = self.settings[setting]
                widget.setEnabled(is_setting_available)
                if isinstance(widget, QSpinBox):
                    widget.setValue(params[setting] if is_setting_available else 0)
                elif isinstance(widget, QComboBox):
                    widget.setCurrentText(params[setting] if is_setting_available else "")
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(params[setting] if is_setting_available else False)
        self._toggle_gain_spinBox(self.autogain_checkBox.isChecked())
        self._toggle_nframes_spinBox(self.mode_comboBox.currentText())

@lru_cache(maxsize=1)
def get_image_depth(dtype):
    img_depth = 0
    if dtype == np.uint8:
        img_depth = 255
    elif dtype == np.uint16:
        img_depth = 65_535
    else:
        print(f"Warning: no assigned image depth for your dtype {dtype}... using 65_535", flush=True)
        img_depth = 65_535 # yes, that's a bit random
    return img_depth

def stretch_histogram(img, lower_thresh, upper_thresh):
    img_depth = get_image_depth(img.dtype)
    r = img_depth/(upper_thresh-lower_thresh+2) # unit of stretching
    out = np.round(r*(img-lower_thresh+1)).astype(img.dtype) # stretched values
    out[img < lower_thresh] = 0
    out[img > upper_thresh] = img_depth
    return out
        
class DisplaySettingsWidget(QWidget):
    #https://www.mfitzp.com/tutorials/embed-pyqtgraph-custom-widgets-qt-app/
    def __init__(self, parent):
        super().__init__(parent)
        
        self.setWindowFlag(Qt.Window)
        
        uic.loadUi(join(dirpath, 'UI_display_settings.ui'), self)
        
        self.graphWidget.showAxis('left', False)

        self.minimum_percent = 0
        self.maximum_percent = 100
        
        self.min_horizontalSlider.valueChanged.connect(self.set_minimum)
        self.max_horizontalSlider.valueChanged.connect(self.set_maximum)
        
        self.reset_pushButton.clicked.connect(self.reset)

    def set_minimum(self, val):
        self.minimum_percent = val

    def set_maximum(self, val):
        self.maximum_percent = val
    
    def reset(self):
        self.minimum_percent = 0
        self.maximum_percent = 100
        self.min_horizontalSlider.setValue(self.minimum_percent)
        self.max_horizontalSlider.setValue(self.maximum_percent)
    
    def process_img(self, img):
        if self.isVisible():
            self.process_histogram(img)
        if self.minimum_percent == 0 and self.maximum_percent == 100:
            return img
        img_depth = get_image_depth(img.dtype)
        minimum = self.minimum_percent/100 * img_depth
        maximum = self.maximum_percent/100 * img_depth
        img = stretch_histogram(img, minimum, maximum)
        return img
        
    def process_histogram(self, img):
        self.graphWidget.clear()
        img_depth = get_image_depth(img.dtype)
        y,x = np.histogram(img, bins=100, range=(0, img_depth))
        self.graphWidget.plot(y)
        