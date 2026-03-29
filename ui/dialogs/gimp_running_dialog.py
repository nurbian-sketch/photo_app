"""
GimpRunningDialog — informacja że GIMP jest już uruchomiony.
Wzorzec identyczny z DarktableRunningDialog.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from ui.styles import (
    DIALOG_MARGINS, DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT,
    DIALOG_IMG_SIZE, DIALOG_BTN_H, DIALOG_BTN_W, DIALOG_TEXT_STYLE,
    center_on_parent,
)

_IMG = os.path.join("assets", "pictures", "gimp-is-running.jpg")


class GimpRunningDialog(QDialog):
    """
    Wyświetlany gdy GIMP jest już uruchomiony przez aplikację.
    Tylko OK — użytkownik musi zamknąć bieżącą sesję GIMP.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("GIMP is running"))
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
        layout.setSpacing(0)
        layout.setContentsMargins(*DIALOG_MARGINS)

        layout.addStretch(3)

        img_label = QLabel()
        if os.path.exists(_IMG):
            raw = QPixmap(_IMG)
            scaled = raw.scaled(
                DIALOG_IMG_SIZE, DIALOG_IMG_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            img_label.setPixmap(scaled)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        layout.addStretch(3)

        msg = QLabel(self.tr(
            "GIMP is already running.\n"
            "Close the current GIMP instance before editing a new file."
        ))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(DIALOG_TEXT_STYLE)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        layout.addStretch(2)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        btn_ok = QPushButton(self.tr("OK"))
        btn_ok.setFixedHeight(DIALOG_BTN_H)
        btn_ok.setFixedWidth(DIALOG_BTN_W)
        btn_ok.setDefault(True)
        btn_ok.setAutoDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        self._focus_btn = btn_ok
