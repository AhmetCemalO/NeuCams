from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import QTimer, Qt
import time
import numpy as np

from .components import DisplaySettingsWidget
from cams.avt_cam import AVTCam

def nparray_to_qimg(img):
    if len(img.shape) == 2:
        height, width = img.shape
        n_chan = 1
    else:
        height, width, n_chan = img.shape
    
    dtype = img.dtype
    if dtype == np.uint16:
        import cv2
        img = cv2.convertScaleAbs(img)
        
    from PyQt5.QtGui import QImage
    format = QImage.Format_Grayscale8 if n_chan == 1 else QImage.Format_RGB888
    bytesPerLine = n_chan * width
    return QImage(img.data, width, height, bytesPerLine, format)

class BaseCameraWidget(QWidget):
    """
    A base class that contains the common, non-UI-specific logic for
    managing a camera feed and its associated settings.
    """
    def __init__(self, cam_handler=None):
        super().__init__()
        self.cam_handler = cam_handler

        # --- Timer for UI updates ---
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update)
        self._timer.start(100)

        # --- FPS computation ---
        self._prev_time = time.time()
        self._prev_frame_nr = 0

        # --- Image aspect ratio policy ---
        self.AR_policy = Qt.KeepAspectRatio

        # --- Image buffers ---
        self.original_img = None
        self.processed_img = None
        self.is_img_processed = False
        self.frame_nr = None

    def _update(self):
        raise NotImplementedError("Subclasses must implement the update method.")

    def _pixmap_aspect_ratio(self, state):
        self.AR_policy = Qt.KeepAspectRatio if state else Qt.IgnoreAspectRatio

    def resizeEvent(self, event):
        pixmap = self.img_label.pixmap()
        if pixmap and not pixmap.isNull():
            self.img_label.setMinimumSize(1,1)
            pixmap = pixmap.scaled(self.img_label.width(), self.img_label.height(),
                                   self.AR_policy, Qt.FastTransformation)
            self.img_label.setPixmap(pixmap)

    def start_cam(self):
        if self.cam_handler:
            if self.cam_handler.start_acquisition():
                self._set_stop_text()

    def stop_cam(self):
        if self.cam_handler:
            self.cam_handler.stop_acquisition()
            self._set_start_text()

    def _set_start_text(self):
        raise NotImplementedError

    def _set_stop_text(self):
        raise NotImplementedError

    def _toggle_cam_settings(self):
        if not self.cam_settings.isVisible():
            self.cam_settings.init_fields()
        self.cam_settings.setVisible(not self.cam_settings.isVisible())

    def _toggle_display_settings(self):
        self.display_settings.setVisible(not self.display_settings.isVisible()) 