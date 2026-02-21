from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QSizePolicy
from ui.widgets.labeled_combo_box import LabeledComboBox


class AutofocusControls(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Focus Settings")
        group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        inner = QVBoxLayout(group)
        inner.setSpacing(0)

        self.focus_mode_label = QLabel("<b>Focusmode set to:</b> AI Servo")
        self.focus_mode_label.setStyleSheet("color: #666; margin-bottom: 5px;")
        inner.addWidget(self.focus_mode_label)

        self.af_method = LabeledComboBox("AF Method", [
            'LiveFace', 'LiveSpotAF', 'Live', 'LiveSingleExpandCross',
            'LiveSingleExpandSurround', 'LiveZone'
        ])
        self.cont_af = LabeledComboBox("Continuous AF", ['Off', 'On'])

        inner.addStretch(1)
        inner.addWidget(self.af_method)
        inner.addStretch(1)
        inner.addWidget(self.cont_af)
        layout.addWidget(group, 1)

    def get_settings(self):
        return {
            "afmethod": self.af_method.currentText(),
            "continuousaf": self.cont_af.currentText()
        }
