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
from ui.styles import (
    DIALOG_SPACING, DIALOG_MARGINS, DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT,
    DIALOG_IMG_SIZE, DIALOG_BTN_H, DIALOG_BTN_W, DIALOG_TEXT_STYLE,
    center_on_parent,
)

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
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setMinimumHeight(DIALOG_MIN_HEIGHT)
        self.setModal(True)
        self._focus_btn = None
        self._build_ui()
        self._timer = QTimer(self)

    def showEvent(self, event):
        super().showEvent(event)
        center_on_parent(self)
        if self._focus_btn:
            self._focus_btn.setFocus()


        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._check_camera)
        self._timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(*DIALOG_MARGINS)

        layout.addStretch(3)

        img_label = QLabel()
        if os.path.exists(_IMG):
            raw = QPixmap(_IMG)
            scaled = raw.scaled(DIALOG_IMG_SIZE, DIALOG_IMG_SIZE,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            img_label.setPixmap(scaled)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        layout.addStretch(3)

        msg = QLabel(
            self.tr("Camera not detected.\n"
                    "Connect camera via USB.\n"
                    "Make sure the camera is turned on.")
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(DIALOG_TEXT_STYLE)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        layout.addStretch(2)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setFixedHeight(DIALOG_BTN_H)
        btn_cancel.setFixedWidth(DIALOG_BTN_W)
        btn_cancel.setDefault(False)
        btn_cancel.setAutoDefault(False)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        self._focus_btn = btn_cancel

    def _check_camera(self):
        """Sprawdza lsusb — jeśli Canon wykryty, zamknij dialog automatycznie."""
        if _lsusb_has_canon():
            self._timer.stop()
            self.accept()
