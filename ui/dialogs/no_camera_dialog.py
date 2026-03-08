"""
NoCameraDialog — informacja o braku aparatu Canon.
Jeden przycisk Cancel. Dialog sam co 2s nasłuchuje podłączenia aparatu.
"""
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from ui.dialogs.usb_disconnect_dialog import _lsusb_has_canon

_IMG = os.path.join("assets", "pictures", "korpus-canon-eos-rp-not-presented-full.jpg")


class NoCameraDialog(QDialog):
    """
    Wyświetlany gdy aparat nie został wykryty przez USB.
    accept() = Canon wykryty automatycznie (caller zleca re-probe),
    reject() = Cancel (oba panele zostają nieaktywne).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Camera not detected"))
        self.setMinimumWidth(480)
        self.setModal(True)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._check_camera)
        self._timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(12, 8, 12, 8)

        img_label = QLabel()
        if os.path.exists(_IMG):
            pix = QPixmap(_IMG).scaled(
                460, 300,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            img_label.setPixmap(pix)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        msg = QLabel(
            self.tr("Camera not detected.\n"
                    "Connect camera via USB.\n"
                    "Make sure the camera is turned on.")
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("font-size: 15px;")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setFixedSize(90, 34)
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        QTimer.singleShot(0, btn_cancel.setFocus)

    def _check_camera(self):
        """Sprawdza lsusb — jeśli Canon wykryty, zamknij dialog automatycznie."""
        if _lsusb_has_canon():
            self._timer.stop()
            self.accept()
