import os
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, QMessageBox, QProgressBar
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from view.widgets import PyCamsWindow
from utils import get_preferences, display
from camera_handler import CameraHandler

LAST_CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.neucams_last_config.txt')
LABCAMSAC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# Helpers for saving/loading last config

def save_last_config(path):
    try:
        with open(LAST_CONFIG_PATH, 'w') as f:
            f.write(path)
    except Exception as e:
        display(f'Could not save last config: {e}', level='warning')

def load_last_config():
    try:
        if os.path.isfile(LAST_CONFIG_PATH):
            with open(LAST_CONFIG_PATH, 'r') as f:
                return f.read().strip()
    except Exception as e:
        display(f'Could not load last config: {e}', level='warning')
    return None

# QThread for background loading (heavy camera setup)
class CameraSetupWorker(QThread):
    finished = pyqtSignal(object, object, object)  # (ret, prefs, cam_handlers)
    def __init__(self, config_path):
        super().__init__()
        self.config_path = config_path
    def run(self):
        ret, prefs = get_preferences(self.config_path)
        cam_handlers = []
        if ret:
            for cam in prefs.get('cams', []):
                if cam.get('driver') in ['avt', 'pco', 'genicam']:
                    writer_dict = {**prefs.get('recorder_params', {}), **cam.get('recorder_params', {})}
                    cam_handler = CameraHandler(cam, writer_dict)
                    if cam_handler.camera_connected:
                        cam_handlers.append((cam, cam_handler))
        self.finished.emit(ret, prefs, cam_handlers)

# Splash/launcher window
class SplashWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('NeuCams Launcher')
        self.setFixedSize(400, 300)
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        title = QLabel('NeuCams')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('font-size: 32px; font-weight: bold; margin-bottom: 30px;')
        layout.addWidget(title)
        self.choose_btn = QPushButton('Choose a JSON configuration file')
        self.choose_btn.setStyleSheet('font-size: 18px; padding: 16px;')
        self.choose_btn.clicked.connect(self.choose_config)
        layout.addWidget(self.choose_btn)
        self.last_btn = QPushButton('Open with last used config')
        self.last_btn.setStyleSheet('font-size: 18px; padding: 16px;')
        self.last_btn.clicked.connect(self.open_last_config)
        layout.addWidget(self.last_btn)
        self.loading_label = QLabel('Loading, please wait...')
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet('font-size: 16px; margin-top: 30px;')
        self.loading_label.hide()
        layout.addWidget(self.loading_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.setLayout(layout)
        self.worker_thread = None
        self.main_window = None

    def choose_config(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Select configuration file', LABCAMSAC_DIR, 'JSON Files (*.json)')
        if fname:
            save_last_config(fname)
            self.start_loading()
            self.worker_thread = CameraSetupWorker(fname)
            self.worker_thread.finished.connect(self.on_loaded)
            self.worker_thread.start()

    def open_last_config(self):
        last = load_last_config()
        if last and os.path.isfile(last):
            self.start_loading()
            self.worker_thread = CameraSetupWorker(last)
            self.worker_thread.finished.connect(self.on_loaded)
            self.worker_thread.start()
        else:
            QMessageBox.warning(self, 'No config found', 'No previous configuration file found.')

    def start_loading(self):
        self.choose_btn.setEnabled(False)
        self.last_btn.setEnabled(False)
        self.loading_label.show()
        self.progress_bar.show()

    def stop_loading(self):
        self.choose_btn.setEnabled(True)
        self.last_btn.setEnabled(True)
        self.loading_label.hide()
        self.progress_bar.hide()

    def on_loaded(self, ret, prefs, cam_handlers):
        if not ret:
            QMessageBox.warning(self, 'Config Error', 'Could not load preferences from the selected file.')
            self.loading_label.setText('')
            self.choose_btn.setEnabled(True)
            self.last_btn.setEnabled(True)
            self.stop_loading()
            return
        # Pass cam_handlers to PyCamsWindow (modify PyCamsWindow to accept them)
        self.main_window = PyCamsWindow(preferences=prefs, preinit_cam_handlers=cam_handlers)
        self.main_window.show()
        self.hide()
        self.stop_loading() 