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
    DIALOG_SPACING, DIALOG_MARGINS, DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT,
    DIALOG_IMG_SIZE, DIALOG_BTN_H, DIALOG_BTN_W, DIALOG_TEXT_STYLE,
    center_on_parent,
)


# ── Spacingi dialogu Prepare Camera — dostosuj tutaj ─────────────────────────
_STRETCH_TOP    = 3   # stretch nad obrazkiem
_STRETCH_MIDDLE = 3   # stretch między obrazkiem a krokami
_STRETCH_BOTTOM = 2   # stretch między krokami a przyciskami
_STEPS_SPACING  = 6   # odstęp między wierszami kroków (px)
# ─────────────────────────────────────────────────────────────────────────────


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
        self.setMinimumHeight(DIALOG_MIN_HEIGHT)
        self.setModal(True)
        self._state = self._WAIT_DISCONNECT
        self._reconnect_after = 0.0
        self._btn_cancel_ref = None
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    def showEvent(self, event):
        super().showEvent(event)
        center_on_parent(self)
        if self._btn_cancel_ref:
            self._btn_cancel_ref.setFocus()
        self._timer.start(1200)
        self._poll()

    def _build_ui(self):
        from PyQt6.QtWidgets import QWidget

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(*DIALOG_MARGINS)

        layout.addStretch(_STRETCH_TOP)

        img_label = QLabel()
        img_path = os.path.join("assets", "pictures", "turn_switch-on-and-off.jpg")
        if os.path.exists(img_path):
            raw = QPixmap(img_path)
            scaled = raw.scaled(DIALOG_IMG_SIZE, DIALOG_IMG_SIZE,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            img_label.setPixmap(scaled)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        layout.addStretch(_STRETCH_MIDDLE)

        # Kroki OFF / ON — wycentrowana grupa, tekst wyrównany pionowo
        steps = QWidget()
        steps_layout = QVBoxLayout(steps)
        steps_layout.setSpacing(_STEPS_SPACING)
        steps_layout.setContentsMargins(0, 0, 0, 0)

        self._step1 = QLabel(f"{self._DOT_PENDING}  " + self.tr("Turn camera off"))
        self._step1.setStyleSheet(DIALOG_TEXT_STYLE + " color: #888;")
        steps_layout.addWidget(self._step1)

        self._step2 = QLabel(f"{self._DOT_PENDING}  " + self.tr("Turn camera back on"))
        self._step2.setStyleSheet(DIALOG_TEXT_STYLE + " color: #888;")
        steps_layout.addWidget(self._step2)

        layout.addWidget(steps, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(_STRETCH_BOTTOM)

        # Przyciski wycentrowane, przyklejone do dołu
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setFixedHeight(DIALOG_BTN_H)
        btn_cancel.setMinimumWidth(DIALOG_BTN_W)
        btn_cancel.setDefault(True)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        self._btn_cancel_ref = btn_cancel

        btn_row.addSpacing(8)

        self._btn_start = QPushButton(self.tr("Start Session"))
        self._btn_start.setFixedHeight(DIALOG_BTN_H)
        self._btn_start.setMinimumWidth(DIALOG_BTN_W)
        self._btn_start.setEnabled(False)
        self._btn_start.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_start)

        btn_row.addStretch(1)
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
