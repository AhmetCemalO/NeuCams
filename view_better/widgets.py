import time
from concurrent.futures import Future, ThreadPoolExecutor
from os.path import dirname, join, realpath
from pathlib import PurePath

import cv2
import numpy as np
from application.image_processing import (BASE_PROCESSING_STAGES, EmptyStage,
                                          HistogramStretcher, ImageFlipper,
                                          ImageProcessingPipeline,
                                          ImageRotator, get_image_depth)
from application.interface_factory import InterfaceFactory
from application.interface_manager import InterfaceManager
from application.mptracker import MPTrackerWidget
from application.udp_socket import UDPConnectionReset, UDPSocket, UDPTimeOut
from application.utils import display, single_emit
from application.view.widget_utils import (get_widget_data_type,
                                           get_widget_setter, get_widget_value)
from colorama import Fore, Style
from PyQt5 import uic
from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QImage, QPixmap
from PyQt5.QtWidgets import (QAction, QApplication, QMainWindow, QMdiSubWindow,
                             QMessageBox, QWidget)

AVAILABLE_PROCESSING_STAGES = {
    **BASE_PROCESSING_STAGES, 'MPTracker': MPTrackerWidget}

dirpath = dirname(realpath(__file__))
repo_path = dirname(dirname(dirname(dirpath)))


class PyCamsWindow(QMainWindow):
    display('PQTSignal emitter here')
    single_emitter = pyqtSignal(object)
    

    def __init__(self, preferences=None):
        display('init maybe?')
        self.preferences = preferences if preferences is not None else {}

        super().__init__()
        display('super init')
        uic.loadUi(join(dirpath, 'UI_pycams.ui'), self)
        display('load ui')
        self.setWindowIcon(QIcon(str(PurePath(dirpath + '/icon/pycams.png'))))

        self.cam_widgets = []
        self.interfaces = {}

        interface_factory = InterfaceFactory()

        for cam_dict in self.preferences.get('cams', []):
            cam_type = cam_dict['type']
            display('Selected cam type: {}'.format(cam_type))
            display('Cam type is in available interfaces: {}'.format(cam_type in interface_factory.list_available_interfaces()))
            if cam_type in interface_factory.list_available_interfaces():
                display('Cam type in self interfaces: {}'.format(cam_type in self.interfaces))
                if cam_type not in self.interfaces:
                    self.interfaces[cam_type] = InterfaceManager(
                        interface_factory.get_interface(cam_type)())
                self.handle_camera(cam_dict)

        server_params = self.preferences.get('server_params', None)
        if server_params is not None:
            server = server_params.get('server', None)
            if server == "udp":
                self.server = UDPSocket(("",
                                         server_params.get('server_port', 9999)))
                self._timer = QTimer(self)
                self.server_thread = ThreadPoolExecutor()
                self._timer.timeout.connect(self.listen_server_message)
                self._timer.start(server_params.get(
                    'server_refresh_time', 100))

        self.mdiArea.setActivationOrder(1)

        self.menuView.triggered[QAction].connect(self.viewMenuActions)

        self.show()

    def listen_server_message(self):
        server_response_future = self.server_thread.submit(self.server.receive)
        server_response_future.add_done_callback(self.process_server_message)

    def process_server_message(self, server_response_future):

        def server_display(msg):
            display(Fore.CYAN + msg + Style.RESET_ALL)

        try:
            msg, address = server_response_future.result()
        except (UDPTimeOut, UDPConnectionReset):
            return
        else:
            server_display(f"Received '{msg}' from {address}")
            if '=' in msg:
                request, value = msg.split('=')
            else:
                request = msg

            if request == 'ping':
                server_display(f'Server got pinged [{address}]')
                self.server.send('pong', address)

            elif request == 'folder':
                for cam_widget in self.cam_widgets:
                    if cam_widget.remote_control_enabled:
                        exp_folder = str(PurePath(value))
                        cam_widget.acq_handler.set_folder_path(exp=exp_folder)
                        server_display(
                            f'Experiment folder changed to {exp_folder} [{address}]')
                self.server.send(f'ok={request}', address)

            elif request == 'save':
                server_display(f'Received save={value} command [{address}]')
                for cam_widget in self.cam_widgets:
                    if cam_widget.remote_control_enabled:
                        state = value.lower() == 'true'
                        cam_widget.record(state)
                        single_emit(self.single_emitter,
                                    cam_widget.record_checkBox.setChecked, state)
                self.server.send(f'ok={request}', address)

            elif request == 'start':
                server_display(f'Received start command [{address}]')
                for cam_widget in self.cam_widgets:
                    if cam_widget.remote_control_enabled:
                        cam_widget.set_acquisition(mode=True)
                        server_display(f'Camera started [{address}]')
                self.server.send(f'ok={request}', address)

            elif request == 'stop':
                server_display(f'Received stop command [{address}]')
                for cam_widget in self.cam_widgets:
                    if cam_widget.remote_control_enabled:
                        cam_widget.set_acquisition(mode=False)
                        server_display(f'Camera stopped [{address}]')
                self.server.send(f'ok={request}', address)

            # TODO acq_handler now needs to use a callback
            # elif request == 'done?':
            #     cam_descr = value[0]
            #     for cam_widget in self.cam_widgets:
            #         if cam_widget.acq_handler.get_cam_dict()['description'] == cam_descr:
            #             display(f'Received status request from [{address}] \n',
            #                     f"Cam {cam_descr} {request} status: {cam_widget.acq_handler.is_trigger_set('is_acquisition_done')}")
            #             self.server.send(f"done?={cam_widget.acq_handler.is_trigger_set('is_acquisition_done')}", address)
            #             return
            #     self.server.send('done?=camera not found', address)

            elif request == 'quit':
                server_display(f'Exiting [{address}]')
                self.server.send(f'ok={request}', address)
                self.close()

    def handle_camera(self, cam_dict):
        display('Handling camera')
        writer_dict = self.create_writer_dict(cam_dict)
        acq_handler = self.setup_acquisition_handler(cam_dict, writer_dict)
        cam_widget = self.setup_camera_widget(
            cam_dict['description'], acq_handler)
        single_emit(self.single_emitter, cam_widget.remote_control_checkBox.setChecked,
                    cam_dict.get('remote_control', True))

    def create_writer_dict(self, cam_dict):
        writer_dict = {
            **self.preferences.get('recorder_params', {}), **cam_dict.get('recorder_params', {})}
        # , writer_dict['experiment_folder'])
        writer_dict['_root_folder_path'] = join(
            writer_dict['data_folder'], cam_dict['description'])
        return writer_dict

    def setup_acquisition_handler(self, cam_dict, writer_dict):
        # acq_handler is a proxy, can only access values through methods
        display('Setting up acquisition handler')
        acq_handler = self.interfaces[cam_dict['type']].get_proxy_acquisition_handler(
            cam_dict.get('id', None), writer_dict)
        display('AQ handler done')
        acq_handler.set_folder_path(root=str(PurePath(
            writer_dict['_root_folder_path'])), exp=writer_dict['experiment_folder'])
        cam_params = cam_dict.get('params', {})
        if 'settings_file' in cam_params:
            settings_path = join(repo_path, 'configs',
                                 cam_params.pop('settings_file'))
            acq_handler.cam_load_settings(settings_path)
        acq_handler.set_cam_params(cam_params)
        display('Acquisition handler set up')
        return acq_handler

    def setup_camera_widget(self, widget_name, acq_handler):
        widget = CamWidget(acq_handler)
        self.cam_widgets.append(widget)
        self.setup_widget(widget_name, widget)
        return widget

    def setup_widget(self, name, widget):
        active_subwindows = [e.objectName()
                             for e in self.mdiArea.subWindowList()]
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

    def viewMenuActions(self, q):
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
        reply = QMessageBox.question(self,
                                     'Window Close',
                                     'Are you sure you want to close the window?',
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)

        if reply == QMessageBox.Yes:
            event.accept()
            self.close()
        else:
            event.ignore()

    def close(self):
        for cam_widget in self.cam_widgets:
            cam_widget.close()
        for interface in self.interfaces.values():
            interface.close()
        display("PyCams out, bye!")
        QApplication.quit()


def nparray_to_qimg(img):
    dtype = img.dtype
    if dtype == np.uint16:
        # if upgrade to pyqt 5.13, use Format_Grayscale16 instead
        img = cv2.convertScaleAbs(img, alpha=255.0/65535.0)
    height, width = img.shape[:2]
    n_chan = img.shape[2] if len(img.shape) == 3 else 1
    format = QImage.Format_Grayscale8 if n_chan == 1 else QImage.Format_RGB888
    bytesPerLine = n_chan * width
    return QImage(img.data, width, height, bytesPerLine, format)


class CamWidget(QWidget):

    new_image = pyqtSignal(object)
    new_pixmap = pyqtSignal(object)
    fps_label_updated = pyqtSignal(str)
    filepath_label_updated = pyqtSignal(str)
    frame_nr_label_updated = pyqtSignal(str)
    is_acquiring = pyqtSignal(bool)
    acquisition_label_updated = pyqtSignal(str)

    processing_resolution_updated = pyqtSignal(object)
    processing_budget_ms_updated = pyqtSignal(int)
    processing_time_ms_updated = pyqtSignal(int)

    single_emitter = pyqtSignal(object)

    def __init__(self, acq_handler=None):
        super().__init__()
        uic.loadUi(join(dirpath, 'UI_cam.ui'), self)

        self.acq_handler = acq_handler
        self.schedule_close = False

        self.remote_control_enabled = self.remote_control_checkBox.isChecked()
        self.remote_control_checkBox.stateChanged.connect(
            self._update_remote_control)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self.refresh_rate = 100
        self._timer.start(self.refresh_rate)

        self.start_time_fetch_image = 0

        self.AR_policy = Qt.KeepAspectRatio

        self.original_img = None
        self.processed_img = None

        self.processing_resolution = [0, 0]
        self.processing_scale = 1.0

        self.available_for_processing = True

        self.frame_nr = -1

        self.acquire_pushButton.released.connect(self.set_acquisition)
        self.record_checkBox.stateChanged.connect(self.record)

        self.cam_settings = CamSettingsWidget(self, self.acq_handler)
        self.camera_settings_pushButton.released.connect(
            self._toggle_cam_settings)

        self.is_acquiring.connect(self.cam_settings.mode_comboBox.setDisabled)

        self.display_settings = DisplaySettingsWidget(self)
        self.display_settings_pushButton.released.connect(
            self._toggle_display_settings)
        self.display_settings.keep_AR_checkBox.stateChanged.connect(
            self._pixmap_aspect_ratio)

        self.new_pixmap.connect(self.img_label.setPixmap)
        self.new_image.connect(self.display_settings.update)

        self.is_acquiring.connect(self.record_checkBox.setDisabled)
        self.is_acquiring.connect(self.remote_control_checkBox.setDisabled)
        self.acquisition_label_updated.connect(self.acquire_pushButton.setText)

        self.fps_label_updated.connect(self.fps_label.setText)
        self.filepath_label_updated.connect(self.save_location_label.setText)
        self.frame_nr_label_updated.connect(self.frame_nr_label.setText)

        self.processing_pipeline = ImageProcessingPipeline()
        self.processing_pipeline.add_stage(
            self.display_settings.histogram_stretcher)
        self.processing_pipeline.add_stage(EmptyStage())
        self.processing_pipeline.add_stage(self.display_settings.image_flipper)
        self.processing_pipeline.add_stage(self.display_settings.image_rotator)

        self.image_processing = ImageProcessingWidget(self)
        self.image_processing_pushButton.released.connect(
            self._toggle_image_processing)
        self.lower_processing_resolution_enabled = self.image_processing.lower_resolution_checkBox.isChecked()

        self.current_img_future = None

    def _update(self):
        self._update_labels()
        self._update_img()

    def _update_labels(self):
        if not self.schedule_close and self.acq_handler is not None:
            set_state_future = self.acq_handler.is_trigger_set(
                'start_trigger', 'stop_trigger')
            set_state_future.add_done_callback(self.set_state)

            filepath_future = self.acq_handler.get_filepath()
            filepath_future.add_done_callback(self.set_filepath)

            fps_future = self.acq_handler.get_framerate()
            fps_future.add_done_callback(self.set_fps_label)
            fps_future.add_done_callback(self.update_processing_budget)

            frame_nr_future = self.acq_handler.get_frame_nr()
            frame_nr_future.add_done_callback(self._update_frame_nr)

    def _update_img(self):
        if not self.schedule_close and self.acq_handler is not None:
            if self.current_img_future is None or self.current_img_future.done():
                self.current_img_future = self.acq_handler.get_image()
                self.current_img_future.add_done_callback(self._draw_img)

    def close(self):
        self.schedule_close = True
        time.sleep(0.5)  # wait a bit for the futures to be done
        # TODO cleaner solution e.g. request counter
        # (currently hangs upon close for framerates <= 2)
        super().close()

    def set_filepath(self, filepath):
        self.filepath_label_updated.emit(f'Filepath: {filepath.result()}')

    def update_processing_budget(self, fps):
        try:
            camera_refresh_rate_ms = int(1000/fps.result())
        except ZeroDivisionError:
            pass
        else:
            self.processing_budget_ms_updated.emit(
                max(self._timer.interval(), camera_refresh_rate_ms))

    def set_fps_label(self, fps):
        self.fps_label_updated.emit(f"{fps.result()} fps")

    def _update_frame_nr(self, frame_nr):
        self.frame_nr_label_updated.emit(f"frame: {frame_nr.result()}")

    def _draw_img(self, image_future):
        if self.available_for_processing:
            self.available_for_processing = False
            try:
                image = image_future.result()
                if image is not None:
                    self.original_img = image
                    self.new_image.emit(self.original_img)
                    t_start = time.time()
                    if self.lower_processing_resolution_enabled:
                        miniature_img = cv2.resize(
                            image, None, fx=self.processing_scale, fy=self.processing_scale, interpolation=cv2.INTER_LINEAR)
                        array_to_process = np.reshape(
                            miniature_img, (miniature_img.shape[0], miniature_img.shape[1], self.original_img.shape[2]))
                    else:
                        array_to_process = np.copy(self.original_img)
                    self.processing_resolution_updated.emit(
                        array_to_process.shape[:2][::-1])
                    self.processed_array = self.processing_pipeline.apply(
                        array_to_process)
                    pixmap = QPixmap(nparray_to_qimg(self.processed_array))
                    scaled_pixmap = pixmap.scaled(self.img_label.width(), self.img_label.height(),
                                                  self.AR_policy, Qt.FastTransformation)
                    self.processing_time_ms_updated.emit(
                        int((time.time() - t_start)*1000))
                    self.new_pixmap.emit(scaled_pixmap)
            except Exception as exc:
                print('draw_img', repr(exc), flush=True)
            self.available_for_processing = True

    def _update_processing_pipeline(self, stage_index):
        stage_name = self.image_processing.processing_comboBox.itemText(
            stage_index)
        self.processing_pipeline.replace_stage(
            1, AVAILABLE_PROCESSING_STAGES.get(stage_name)())

    def enable_lower_resolution(self, state):
        self.lower_processing_resolution_enabled = state

    def update_processing_scale(self, scale):
        self.processing_scale = scale

    def _pixmap_aspect_ratio(self, state):
        self.AR_policy = Qt.KeepAspectRatio if state else Qt.IgnoreAspectRatio

    def resizeEvent(self, event):
        pixmap = self.img_label.pixmap()
        if pixmap is not None:
            self.img_label.setMinimumSize(1, 1)
            scaled_pixmap = pixmap.scaled(self.img_label.width(), self.img_label.height(),
                                          self.AR_policy, Qt.FastTransformation)
            self.new_pixmap.emit(scaled_pixmap)

    def set_state(self, triggers):
        start_trigger, stop_trigger = triggers.result()
        is_acquiring = start_trigger and not stop_trigger
        self.is_acquiring.emit(is_acquiring)
        self.acquisition_label_updated.emit(
            "Stop" if is_acquiring else "Start")

    def set_acquisition(self, mode=None):
        if self.acq_handler is not None:
            is_starting = mode if mode is not None else self.acquire_pushButton.text() == "Start"
            if is_starting:
                self.acq_handler.start_acquisition()
            else:
                self.acq_handler.stop_acquisition()

    def record(self, state):
        self.acq_handler.enable_saving(state)

    def _update_remote_control(self, state):
        self.remote_control_enabled = state

    def _toggle_cam_settings(self):
        is_visible = self.cam_settings.isVisible()
        single_emit(self.single_emitter,
                    self.cam_settings.setVisible, not is_visible)
        if not is_visible:
            self.cam_settings.fetch_params_and_update_fields()

    def _toggle_display_settings(self):
        is_visible = self.display_settings.isVisible()
        single_emit(self.single_emitter,
                    self.display_settings.setVisible, not is_visible)

    def _toggle_image_processing(self):
        is_visible = self.image_processing.isVisible()
        single_emit(self.single_emitter,
                    self.image_processing.setVisible, not is_visible)


class CamSettingsWidget(QWidget):

    enable_nframes_spinBox = pyqtSignal(bool)

    def __init__(self, parent, acq_handler=None):
        super().__init__(parent)

        self.setWindowFlag(Qt.Window)

        uic.loadUi(join(dirpath, 'UI_cam_settings.ui'), self)

        self.acq_handler = acq_handler

        self.apply_pushButton.released.connect(self._apply_settings)

        self.autogain_checkBox.stateChanged.connect(
            self.gain_spinBox.setDisabled)

        self.nframes_comboBox.currentTextChanged.connect(
            self._toggle_nframes_spinBox)
        self.enable_nframes_spinBox.connect(self.nframes_spinBox.setEnabled)

        self.settings = {
            'exposure': self.exposure_spinBox,
            'frame_rate': self.framerate_spinBox,
            'gain': self.gain_spinBox,
            'gain_auto': self.autogain_checkBox,
            'binning': self.binning_spinBox,
            'acquisition_mode': self.nframes_comboBox,
            'n_frames': self.nframes_spinBox,
            'roi_mode': self.roi_checkBox,
            'roi_top': self.roi_top_doubleSpinBox,
            'roi_left': self.roi_left_doubleSpinBox,
            'roi_bottom': self.roi_bottom_doubleSpinBox,
            'roi_right': self.roi_right_doubleSpinBox
        }

        def factory(setter_type):
            return type(
                'SettingSignals',
                (QObject,),
                {
                    'enabler': pyqtSignal(bool),
                    'setter': pyqtSignal(setter_type)
                }
            )

        self.settings_signals = {}
        for setting, widget in self.settings.items():
            self.settings_signals[setting] = factory(
                get_widget_data_type(widget))()
            self.settings_signals[setting].enabler.connect(widget.setEnabled)
            self.settings_signals[setting].setter.connect(
                get_widget_setter(widget))

        modes_future = self.acq_handler.get_cam_modes()
        modes_future.add_done_callback(self._init_mode_comboBox)

        self.roi_save = None
        self.roi_checkBox.stateChanged.connect(self.reset_roi)
        self.roi_checkBox.stateChanged.connect(
            self.roi_verticalWidget.setEnabled)

    def reset_roi(self, roi_enabled):
        roi_edges = ['roi_top', 'roi_left', 'roi_bottom', 'roi_right']
        if roi_enabled:
            if self.roi_save is not None:
                for edge in roi_edges:
                    self.settings_signals[edge].setter.emit(
                        self.roi_save[edge])
        else:
            self.roi_save = {edge: get_widget_value(
                self.settings[edge]) for edge in roi_edges}

    def _init_mode_comboBox(self, modes_future: Future):
        modes = [mode.value for mode in modes_future.result()]
        self.mode_comboBox.addItems(modes)

    def _toggle_nframes_spinBox(self, text):
        self.enable_nframes_spinBox.emit(text != "Continuous")

    def _apply_settings(self):
        params_to_set = {}
        for setting in self.settings:
            widget = self.settings[setting]
            if widget.isEnabled():
                params_to_set[setting] = get_widget_value(widget)
        self.acq_handler.set_cam_mode(self.mode_comboBox.currentText())
        self.acq_handler.set_cam_params(params_to_set)
        # need to wait for cam to set the params before updating
        time.sleep(0.1)
        self.fetch_params_and_update_fields()

    def fetch_params_and_update_fields(self):
        params_future = self.acq_handler.get_cam_params()
        params_future.add_done_callback(self.update_fields)

    def update_fields(self, params_future):
        params = params_future.result()
        if params is not None:
            for setting in self.settings:
                is_setting_available = setting in params
                self.settings_signals[setting].enabler.emit(
                    is_setting_available)
                if is_setting_available:
                    self.settings_signals[setting].setter.emit(params[setting])
        self._toggle_nframes_spinBox(self.nframes_comboBox.currentText())


class DisplaySettingsWidget(QWidget):
    # https://www.mfitzp.com/tutorials/embed-pyqtgraph-custom-widgets-qt-app/

    min_slider_updated = pyqtSignal(int)
    max_slider_updated = pyqtSignal(int)

    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowFlag(Qt.Window)

        uic.loadUi(join(dirpath, 'UI_display_settings.ui'), self)

        self.graphWidget.showAxis('left', False)  # PlotWidget

        self.histogram_stretcher = HistogramStretcher()

        self.image_rotator = ImageRotator()

        self.image_flipper = ImageFlipper()

        self.set_bit_depth(self.bit_depth_spinBox.value())
        self.bit_depth_spinBox.valueChanged.connect(self.set_bit_depth)

        self.min_horizontalSlider.valueChanged.connect(self.set_minimum)
        self.max_horizontalSlider.valueChanged.connect(self.set_maximum)

        self.min_slider_updated.connect(self.min_horizontalSlider.setValue)
        self.max_slider_updated.connect(self.max_horizontalSlider.setValue)

        self.auto_stretch_next_img = False

        self.auto_stretch_pushButton.released.connect(
            self.schedule_auto_stretch)

        self.reset_pushButton.released.connect(self.reset)

        self.rotate_ccw_pushButton.released.connect(self.increment_image_angle)
        self.rotate_cw_pushButton.released.connect(self.decrement_image_angle)

        self.flip_h_pushButton.released.connect(self.toggle_flip_h)
        self.flip_v_pushButton.released.connect(self.toggle_flip_v)

    def set_bit_depth(self, val: int):
        self.histogram_stretcher.bit_depth = val

    def toggle_flip_h(self):
        self.image_flipper.flip_h = not self.image_flipper.flip_h

    def toggle_flip_v(self):
        self.image_flipper.flip_v = not self.image_flipper.flip_v

    def increment_image_angle(self):
        self.image_rotator.rotation_deg += 90

    def decrement_image_angle(self):
        self.image_rotator.rotation_deg -= 90

    def set_minimum(self, val):
        self.histogram_stretcher.minimum_percent = val

    def set_maximum(self, val):
        self.histogram_stretcher.maximum_percent = val

    def _update_sliders(self):
        self.min_slider_updated.emit(self.histogram_stretcher.minimum_percent)
        self.max_slider_updated.emit(self.histogram_stretcher.maximum_percent)

    def reset(self):
        self.set_minimum(0)
        self.set_maximum(100)
        self._update_sliders()

    def schedule_auto_stretch(self):
        self.auto_stretch_next_img = True

    def update(self, img: np.ndarray):
        if self.auto_stretch_next_img:
            self.histogram_stretcher.find_limits(img)
            self._update_sliders()
            self.auto_stretch_next_img = False

        if self.isVisible():
            self.graphWidget.clear()
            y, x = np.histogram(img, bins=100,
                                range=(0, self.histogram_stretcher.depth))
            self.graphWidget.plot(y)


class ImageProcessingWidget(QWidget):
    """This is not really a separate widget, it just exposes the image processing options
    linked to the parent widget"""
    displayed_resolution_updated = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowFlag(Qt.Window)

        uic.loadUi(join(dirpath, 'UI_image_processing.ui'), self)

        self.processing_comboBox.addItems(AVAILABLE_PROCESSING_STAGES.keys())
        self.processing_comboBox.activated.connect(
            parent._update_processing_pipeline)

        self.lower_resolution_checkBox.stateChanged.connect(
            parent.enable_lower_resolution)
        self.lower_resolution_checkBox.stateChanged.connect(
            self.scale_doubleSpinBox.setEnabled)

        self.scale_doubleSpinBox.valueChanged.connect(
            parent.update_processing_scale)

        parent.processing_budget_ms_updated.connect(
            self.processing_budget_ms_label.setNum)
        parent.processing_time_ms_updated.connect(
            self.processing_time_ms_label.setNum)

        self.displayed_resolution_updated.connect(
            self.resolution_label.setText)

        parent.processing_resolution_updated.connect(
            self.update_displayed_resolution)

    def update_displayed_resolution(self, resolution):
        self.displayed_resolution_updated.emit(
            f'{resolution[0]}, {resolution[1]}')
