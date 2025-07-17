import cv2
import numpy as np


class ImageProcessingPipeline:
    """A simple pipeline to apply a series of processing stages to an image."""
    def __init__(self):
        self.stages = []

    def add_stage(self, stage):
        """Adds a processing stage to the pipeline."""
        self.stages.append(stage)

    def apply(self, img: np.ndarray) -> np.ndarray:
        """Applies all stages in the pipeline to the image."""
        for stage in self.stages:
            img = stage.apply(img)
        return img

    def replace_stage(self, index, new_stage):
        """Replaces a stage at a given index."""
        if 0 <= index < len(self.stages):
            self.stages[index] = new_stage


class ProcessingStage:
    """Base class for a processing stage."""
    def apply(self, img: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class EmptyStage(ProcessingStage):
    """A stage that does nothing."""
    def apply(self, img: np.ndarray) -> np.ndarray:
        return img


class HistogramStretcher(ProcessingStage):
    """Stretches the histogram of an image to enhance contrast."""
    def __init__(self):
        self.min_percent = 0
        self.max_percent = 100
        self.img_depth = 255  # Default for 8-bit

    def set_range(self, min_val: int, max_val: int):
        self.min_percent = min_val
        self.max_percent = max_val

    def set_depth(self, depth: int):
        self.img_depth = depth

    def apply(self, img: np.ndarray) -> np.ndarray:
        if self.min_percent == 0 and self.max_percent == 100:
            return img
        
        min_val = self.min_percent / 100 * self.img_depth
        max_val = self.max_percent / 100 * self.img_depth

        # Avoid division by zero if min and max are the same
        if max_val == min_val:
            return img
        
        # Simple contrast stretching
        stretched = (img - min_val) * (self.img_depth / (max_val - min_val))
        stretched = np.clip(stretched, 0, self.img_depth)
        return stretched.astype(img.dtype)


class BackgroundSubtractor(ProcessingStage):
    """Subtracts the average of the last N frames (background) from the current image."""
    def __init__(self, n_frames=10):
        self.n_frames = n_frames
        self.enabled = False
        self.buffer = []
        self.background = None

    def set_n_frames(self, n):
        self.n_frames = max(1, int(n))
        self.buffer = []  # Reset buffer when N changes
        self.background = None

    def reset(self):
        self.buffer = []
        self.background = None

    def apply(self, img: np.ndarray) -> np.ndarray:
        if not self.enabled:
            return img
        # Add current frame to buffer
        self.buffer.append(img.astype(np.float32))
        if len(self.buffer) > self.n_frames:
            self.buffer.pop(0)
        # Compute background if enough frames
        if len(self.buffer) == self.n_frames:
            self.background = np.mean(self.buffer, axis=0)
            result = cv2.subtract(img.astype(np.float32), self.background)
            result = np.clip(result, 0, np.iinfo(img.dtype).max)
            return result.astype(img.dtype)
        else:
            return img


class GaussianBlur(ProcessingStage):
    """Applies a Gaussian blur to an image."""
    def __init__(self, kernel_size=1):
        self.kernel_size = kernel_size
        self.enabled = False

    def set_kernel_size(self, size):
        # Kernel size must be an odd number
        self.kernel_size = size if size % 2 != 0 else size + 1

    def apply(self, img: np.ndarray) -> np.ndarray:
        if not self.enabled or self.kernel_size <= 1:
            return img
        return cv2.GaussianBlur(img, (self.kernel_size, self.kernel_size), 0)


class ImageFlipper(ProcessingStage):
    """Flips an image horizontally or vertically."""
    def __init__(self):
        self.flip_h = False
        self.flip_v = False

    def apply(self, img: np.ndarray) -> np.ndarray:
        if self.flip_h:
            img = cv2.flip(img, 1)
        if self.flip_v:
            img = cv2.flip(img, 0)
        return img


class ImageRotator(ProcessingStage):
    """Rotates an image by a multiple of 90 degrees."""
    def __init__(self):
        self.angle = 0  # Can be 0, 90, 180, 270

    def set_angle(self, angle: int):
        self.angle = angle % 360

    def apply(self, img: np.ndarray) -> np.ndarray:
        if self.angle == 90:
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif self.angle == 180:
            return cv2.rotate(img, cv2.ROTATE_180)
        elif self.angle == 270:
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return img 