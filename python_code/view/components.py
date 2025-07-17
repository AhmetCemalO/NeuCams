from functools import lru_cache
from os.path import dirname, join
import numpy as np
from PyQt5 import uic
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt

from .image_processing import (HistogramStretcher, ImageFlipper,
                               ImageProcessingPipeline, ImageRotator,
                               GaussianBlur, BackgroundSubtractor)

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

class DisplaySettingsWidget(QWidget):
    """Upgraded widget to handle advanced display settings including rotation,
    flipping, and histogram stretching via a processing pipeline.
    """
    def __init__(self, parent):
        super().__init__(parent)

        self.setWindowFlag(Qt.Window)
        uic.loadUi(join(dirname(__file__), 'UI_display_settings.ui'), self)

        # Image processing pipeline setup
        self.pipeline = ImageProcessingPipeline()
        self.stretcher = HistogramStretcher()
        self.flipper = ImageFlipper()
        self.rotator = ImageRotator()
        self.pipeline.add_stage(self.stretcher)
        self.pipeline.add_stage(self.flipper)
        self.pipeline.add_stage(self.rotator)
        
        self.last_img = None

        # Connect UI controls to methods
        self.graphWidget.showAxis('left', False)
        self.min_horizontalSlider.valueChanged.connect(self.set_minimum)
        self.max_horizontalSlider.valueChanged.connect(self.set_maximum)
        self.reset_pushButton.clicked.connect(self.reset)
        self.auto_stretch_pushButton.clicked.connect(self.auto_stretch)
        self.flip_h_pushButton.toggled.connect(self.toggle_flip_h)
        self.flip_v_pushButton.toggled.connect(self.toggle_flip_v)
        self.rotate_cw_pushButton.clicked.connect(self.rotate_cw)
        self.rotate_ccw_pushButton.clicked.connect(self.rotate_ccw)

        # Keep a reference to the parent's aspect ratio policy
        if hasattr(parent, 'keep_AR_checkBox'):
            self.keep_AR_checkBox.stateChanged.connect(parent._pixmap_aspect_ratio)


    def set_minimum(self, val):
        self.stretcher.set_range(val, self.stretcher.max_percent)

    def set_maximum(self, val):
        self.stretcher.set_range(self.stretcher.min_percent, val)

    def toggle_flip_h(self, checked):
        self.flipper.flip_h = checked

    def toggle_flip_v(self, checked):
        self.flipper.flip_v = checked

    def rotate_cw(self):
        self.rotator.set_angle(self.rotator.angle + 90)

    def rotate_ccw(self):
        self.rotator.set_angle(self.rotator.angle - 90)

    def reset(self):
        """Resets all display settings to their default values."""
        self.min_horizontalSlider.setValue(0)
        self.max_horizontalSlider.setValue(100)
        self.stretcher.set_range(0, 100)

        self.flip_h_pushButton.setChecked(False)
        self.flip_v_pushButton.setChecked(False)
        self.flipper.flip_h = False
        self.flipper.flip_v = False

        self.rotator.set_angle(0)

    def auto_stretch(self):
        """Automatically sets the contrast to the min/max of the image."""
        if self.last_img is None:
            return

        min_val = np.min(self.last_img)
        max_val = np.max(self.last_img)
        img_depth = get_image_depth(self.last_img.dtype)

        # Convert to percentage for the sliders
        min_percent = int((min_val / img_depth) * 100)
        max_percent = int((max_val / img_depth) * 100)

        self.min_horizontalSlider.setValue(min_percent)
        self.max_horizontalSlider.setValue(max_percent)
        self.stretcher.set_range(min_percent, max_percent)

    def process_img(self, img):
        if self.isVisible():
            self.last_img = img  # Keep a reference for auto-stretch
            self.process_histogram(img)
            self.stretcher.set_depth(get_image_depth(img.dtype))

        return self.pipeline.apply(img)

    def process_histogram(self, img):
        self.graphWidget.clear()
        img_depth = get_image_depth(img.dtype)
        y, x = np.histogram(img, bins=100, range=(0, img_depth))
        self.graphWidget.plot(y)


class ImageProcessingWidget(QWidget):
    """A widget to control various image processing stages."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.Window)
        uic.loadUi(join(dirname(__file__), 'UI_image_processing.ui'), self)

        # --- Stages ---
        self.blur_stage = GaussianBlur()
        self.bg_subtract_stage = BackgroundSubtractor()

        # --- Connections ---
        self.groupBox.toggled.connect(self.toggle_blur)
        self.blur_kernel_size_spinBox.valueChanged.connect(self.set_blur_kernel)

        self.groupBox_2.toggled.connect(self.toggle_bg_subtract)
        self.n_frames_spinBox.valueChanged.connect(self.set_n_frames)

    def toggle_blur(self, enabled):
        self.blur_stage.enabled = enabled

    def set_blur_kernel(self, value):
        # Ensure kernel size is at least 1 and odd
        if value < 1:
            value = 1

        self.blur_stage.set_kernel_size(value)
        self.blur_kernel_size_spinBox.setValue(value)

    def toggle_bg_subtract(self, enabled):
        self.bg_subtract_stage.enabled = enabled
        if not enabled:
            self.bg_subtract_stage.reset()

    def set_n_frames(self, value):
        self.bg_subtract_stage.set_n_frames(value)

    def add_to_pipeline(self, pipeline: ImageProcessingPipeline):
        """Adds the processing stages from this widget to a pipeline."""
        pipeline.add_stage(self.blur_stage)
        pipeline.add_stage(self.bg_subtract_stage)