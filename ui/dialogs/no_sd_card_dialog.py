"""
NoSdCardDialog — informacja o braku karty SD w aparacie.
Przyciski: Cancel (reject → prawy panel zostaje nieaktywny) / OK (accept → caller re-probe).
"""
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from ui.styles import (
    DIALOG_SPACING, DIALOG_MARGINS, DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT,
    DIALOG_IMG_SIZE, DIALOG_BTN_H, DIALOG_TEXT_STYLE,
    center_on_parent,
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
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setMinimumHeight(DIALOG_MIN_HEIGHT)
        self.setModal(True)
        self._focus_btn = None
        self._build_ui()

    def showEvent(self, event):
        super().showEvent(event)
        center_on_parent(self)
        if self._focus_btn:
            self._focus_btn.setFocus()


    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(DIALOG_SPACING)
        layout.setContentsMargins(*DIALOG_MARGINS)

        img_label = QLabel()
        if os.path.exists(_IMG):
            raw = QPixmap(_IMG)
            scaled = raw.scaled(DIALOG_IMG_SIZE, DIALOG_IMG_SIZE,
                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width()  - DIALOG_IMG_SIZE) // 2
            y = (scaled.height() - DIALOG_IMG_SIZE) // 2
            img_label.setPixmap(scaled.copy(x, y, DIALOG_IMG_SIZE, DIALOG_IMG_SIZE))
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        msg = QLabel(self.tr("Insert SD card into camera."))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(DIALOG_TEXT_STYLE)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setFixedHeight(DIALOG_BTN_H)
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addSpacing(8)

        btn_ok = QPushButton(self.tr("OK"))
        btn_ok.setFixedHeight(DIALOG_BTN_H)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)

        layout.addLayout(btn_row)
        self._focus_btn = btn_ok
