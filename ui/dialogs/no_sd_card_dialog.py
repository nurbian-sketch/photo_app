"""
NoSdCardDialog — informacja o braku karty SD w aparacie.
Przyciski: Cancel (reject → prawy panel zostaje nieaktywny) / OK (accept → caller re-probe).
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

_IMG = os.path.join("assets", "pictures", "sdcard-not-presented.jpg")


class NoSdCardDialog(QDialog):
    """
    Wyświetlany gdy aparat wykryty, ale brak karty SD.
    accept() = OK (caller może zlecić re-probe),
    reject() = Cancel (prawy panel pozostaje nieaktywny).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("SD card not found"))
        self.setMinimumWidth(380)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 14, 20, 14)

        img_label = QLabel()
        if os.path.exists(_IMG):
            pix = QPixmap(_IMG).scaled(
                360, 200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            img_label.setPixmap(pix)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        layout.addSpacing(4)

        msg = QLabel(self.tr("Insert SD card into camera."))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("font-size: 13px;")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        layout.addSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setFixedSize(90, 34)
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addSpacing(8)

        btn_ok = QPushButton(self.tr("OK"))
        btn_ok.setFixedSize(90, 34)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)
