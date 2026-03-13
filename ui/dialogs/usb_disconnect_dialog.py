"""
UsbDisconnectDialog — dialog przygotowania sesji.
Prowadzi przez cykl OFF → ON aparatu (aktywacja modułu BT).
"""
import os
import subprocess

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

from ui.styles import (
    DIALOG_SPACING, DIALOG_MARGINS, DIALOG_MIN_WIDTH,
    DIALOG_IMG_SIZE, DIALOG_BTN_W, DIALOG_BTN_H, DIALOG_TEXT_STYLE,
)


def _lsusb_has_canon() -> bool:
    """Sprawdza przez lsusb czy aparat Canon jest widoczny — bez gphoto2, bez sesji PTP."""
    try:
        r = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=2)
        return "Canon" in r.stdout
    except Exception:
        return False


class UsbDisconnectDialog(QDialog):
    """
    Dialog przygotowania sesji: prowadzi przez dwa kroki (OFF → ON).
    Emituje status_changed(str) do paska stanu głównego okna.

    Stany:
        WAIT_DISCONNECT — oczekuje na odłączenie aparatu (krok 1)
        WAIT_RECONNECT  — aparat zniknął, oczekuje na ponowne wykrycie (krok 2)
        READY           — aparat wykryty po cyklu — Start aktywny
    """

    status_changed = pyqtSignal(str)

    _WAIT_DISCONNECT = 0
    _WAIT_RECONNECT  = 1
    _READY           = 2

    _DOT_PENDING = "○"
    _DOT_DONE    = "●"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Prepare camera"))
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setModal(True)
        self._state = self._WAIT_DISCONNECT
        self._reconnect_after = 0.0  # timestamp — krok 2 aktywny dopiero po tym czasie
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(1200)
        self._poll()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(DIALOG_SPACING)
        layout.setContentsMargins(*DIALOG_MARGINS)

        img_label = QLabel()
        img_path = os.path.join("assets", "pictures", "turn_switch-on-and-off.jpg")
        if os.path.exists(img_path):
            raw = QPixmap(img_path)
            scaled = raw.scaled(DIALOG_IMG_SIZE, DIALOG_IMG_SIZE,
                                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width()  - DIALOG_IMG_SIZE) // 2
            y = (scaled.height() - DIALOG_IMG_SIZE) // 2
            img_label.setPixmap(scaled.copy(x, y, DIALOG_IMG_SIZE, DIALOG_IMG_SIZE))
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        self._step1 = QLabel(f"{self._DOT_PENDING}  " + self.tr("Turn camera off"))
        self._step1.setStyleSheet(DIALOG_TEXT_STYLE + " color: #888;")
        self._step1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._step1)

        self._step2 = QLabel(f"{self._DOT_PENDING}  " + self.tr("Turn camera back on"))
        self._step2.setStyleSheet(DIALOG_TEXT_STYLE + " color: #888;")
        self._step2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._step2)

        layout.addSpacing(4)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setFixedSize(DIALOG_BTN_W, DIALOG_BTN_H)
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addSpacing(8)

        self._btn_start = QPushButton(self.tr("Start Session"))
        self._btn_start.setFixedSize(130, DIALOG_BTN_H)
        self._btn_start.setEnabled(False)
        self._btn_start.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_start)

        layout.addLayout(btn_row)
        QTimer.singleShot(0, btn_cancel.setFocus)

    def _poll(self):
        """Polling USB co ~1.2s — lsusb, bez gphoto2."""
        present = _lsusb_has_canon()

        import time
        if self._state == self._WAIT_DISCONNECT:
            if not present:
                self._state = self._WAIT_RECONNECT
                self._reconnect_after = time.monotonic() + 1.0  # min. 1s ochrony przed artefaktem
                self._step1.setText(f"{self._DOT_DONE}  " + self.tr("Turn camera off"))
                self._step1.setStyleSheet(DIALOG_TEXT_STYLE + " color: #27ae60;")
                self._step2.setStyleSheet(DIALOG_TEXT_STYLE)
                self.status_changed.emit(self.tr("Camera not connected"))

        elif self._state == self._WAIT_RECONNECT:
            if present and time.monotonic() >= self._reconnect_after:
                self._state = self._READY
                self._step2.setText(f"{self._DOT_DONE}  " + self.tr("Turn camera back on"))
                self._step2.setStyleSheet(DIALOG_TEXT_STYLE + " color: #27ae60;")
                self._btn_start.setEnabled(True)
                self._btn_start.setDefault(True)
                self._btn_start.setFocus()
                self._timer.stop()
                self.status_changed.emit(self.tr("Camera ready — wireless mode active"))

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
