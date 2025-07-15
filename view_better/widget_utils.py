
from PyQt5 import uic
from PyQt5.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
                             QComboBox, QSpinBox,
                             QCheckBox)
from PyQt5.QtCore import Qt
from os.path import realpath, join, dirname

dirpath = dirname(realpath(__file__))


def get_widget_data_type(widget):
    if isinstance(widget, QSpinBox):
        return int
    elif isinstance(widget, QDoubleSpinBox):
        return float
    elif isinstance(widget, (QComboBox, QLineEdit)):
        return str
    elif isinstance(widget, QCheckBox):
        return bool
    raise TypeError


def get_widget_setter(widget):
    if isinstance(widget,(QSpinBox, QDoubleSpinBox)):
        return widget.setValue
    elif isinstance(widget, QComboBox):
        return widget.setCurrentText
    elif isinstance(widget, QLineEdit):
        return widget.setText
    elif isinstance(widget, QCheckBox):
        return widget.setChecked
    raise TypeError


def get_widget_value(widget):
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        return widget.value()
    elif isinstance(widget, QComboBox):
        return widget.currentText()
    elif isinstance(widget, QLineEdit):
        return widget.text()
    elif isinstance(widget, QCheckBox):
        return widget.isChecked()
    raise TypeError


class AutoFieldWidget(QWidget):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlag(Qt.Window)
        uic.loadUi(join(dirpath, 'UI_autofield_template.ui'), self)
        self.apply_params_pushButton.clicked.connect(self._apply_parameters)
        self.settings = {}
        

    def init_widgets(self):
        vbox = self.verticalLayout
        def init_setting(setting_name, val):
            if isinstance(val, bool):
                checkbox = QCheckBox(setting_name)
                checkbox.setChecked(val)
                return checkbox
            elif isinstance(val, (int, float)):
                spinbox = QSpinBox() if isinstance(val, int) else QDoubleSpinBox()
                spinbox.setValue(val)
                return spinbox
            elif isinstance(val, str):
                line_edit = QLineEdit()
                line_edit.setText(val)
                return line_edit
            else:
                print(f'{self.__class__.__name__}: No GUI element found for setting {setting_name}', flush=True)
                return None

        widgets = {}
        for idx, [setting, val] in enumerate(self.settings.items()):
            widget = init_setting(setting, val)
            if isinstance(val, bool):
                vbox.insertWidget(idx, widget)
            else:
                hbox = QHBoxLayout()
                hbox.addWidget(QLabel(setting))
                hbox.addWidget(widget)
                vbox.insertLayout(idx, hbox)
            widgets[setting] = widget
        self.widgets = widgets
        self.adjustSize()
        self.show()
    
    def _apply_parameters(self):
        for setting in self.widgets:
            widget = self.widgets[setting]
            if widget.isEnabled():
                self.settings[setting] = get_widget_value(widget)
