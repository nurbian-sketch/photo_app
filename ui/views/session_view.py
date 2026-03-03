"""
Widok sesji fotograficznej.
Dwa panele przełączane przez QStackedWidget:
  0 — konfiguracja (formularz przed sesją)
  1 — aktywna sesja (tło, countdown, progress bar, STOP)
  2 — podsumowanie (wyniki po sesji)
"""
from __future__ import annotations

import os
import re
from typing import Optional

from PyQt6.QtCore import Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QFont, QColor, QTransform
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QProgressBar, QGroupBox, QFrame, QDialog, QSplitter,
)

from core.session_context import (
    CameraSettings,
    EndReason,
    SessionContext,
    SessionMode,
    SessionState,
    SessionSummary,
    make_session_context,
)
from core.session_runner import SessionRunner, COUNTDOWN_SEC
from core.session_store import SessionStore
from ui.views.camera_components.exposure_controls import ExposureControls
from ui.views.camera_components.image_controls import ImageControls
from ui.views.camera_components.autofocus_controls import AutofocusControls

# ─────────────────────────── STAŁE

DURATION_VALUES = [1, 3, 5, 10, 15, 30, 45, 60, 90]  # minuty

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

BG_ACTIVE      = os.path.join("assets", "pictures", "session-active.jpg")
BG_FINISHED    = os.path.join("assets", "pictures", "session-finished.jpg")
BG_INTERRUPTED = os.path.join("assets", "pictures", "session-interrupted.jpg")


# ─────────────────────────── DIALOG PRZYGOTOWANIA SESJI

def _lsusb_has_canon() -> bool:
    """Sprawdza przez lsusb czy aparat Canon jest widoczny — bez gphoto2, bez sesji PTP."""
    import subprocess
    try:
        r = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=2)
        return "Canon" in r.stdout
    except Exception:
        return False


class _UsbDisconnectDialog(QDialog):
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

    # Symbole kroków
    _DOT_PENDING = "○"
    _DOT_DONE    = "●"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Prepare camera"))
        self.setMinimumWidth(400)
        self.setModal(True)
        self._state = self._WAIT_DISCONNECT
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(1200)
        self._poll()  # natychmiastowe sprawdzenie

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 14, 20, 14)

        # Obrazek instrukcji
        img_label = QLabel()
        img_path = os.path.join("assets", "pictures", "turn_switch-on-and-off.jpg")
        if os.path.exists(img_path):
            pix = QPixmap(img_path).scaled(
                360, 200,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            img_label.setPixmap(pix)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(img_label)

        layout.addSpacing(4)

        # Krok 1 — wycentrowany
        self._step1 = QLabel(f"{self._DOT_PENDING}  " + self.tr("Turn camera off"))
        self._step1.setStyleSheet("font-size: 13px; color: #888;")
        self._step1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._step1)

        # Krok 2 — wycentrowany
        self._step2 = QLabel(f"{self._DOT_PENDING}  " + self.tr("Turn camera back on"))
        self._step2.setStyleSheet("font-size: 13px; color: #888;")
        self._step2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._step2)

        layout.addSpacing(6)

        # Przyciski
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setFixedSize(90, 34)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        btn_row.addSpacing(8)

        self._btn_start = QPushButton(self.tr("Start Session"))
        self._btn_start.setFixedSize(130, 34)
        self._btn_start.setEnabled(False)
        self._btn_start.setStyleSheet(
            "QPushButton:enabled  { font-weight: bold; "
            "background-color: #1b5e20; color: #e8e8e8; }"
            "QPushButton:disabled { color: #888; }"
        )
        self._btn_start.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_start)

        layout.addLayout(btn_row)

    def _poll(self):
        """Polling USB co ~1.2s — lsusb, bez gphoto2."""
        present = _lsusb_has_canon()

        if self._state == self._WAIT_DISCONNECT:
            if not present:
                # Krok 1 zaliczony
                self._state = self._WAIT_RECONNECT
                self._step1.setText(f"{self._DOT_DONE}  " + self.tr("Turn camera off"))
                self._step1.setStyleSheet("font-size: 13px; color: #27ae60;")
                self._step2.setStyleSheet("font-size: 13px;")  # aktywny
                self.status_changed.emit(self.tr("Camera not connected"))

        elif self._state == self._WAIT_RECONNECT:
            if present:
                # Krok 2 zaliczony — cykl OFF→ON zakończony
                self._state = self._READY
                self._step2.setText(f"{self._DOT_DONE}  " + self.tr("Turn camera back on"))
                self._step2.setStyleSheet("font-size: 13px; color: #27ae60;")
                self._btn_start.setEnabled(True)
                self._timer.stop()
                self.status_changed.emit(self.tr("Camera ready — wireless mode active"))

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)


# ─────────────────────────── WIDGET TŁA

class BackgroundWidget(QWidget):
    """Widget wypełniający tło obrazem (skalowanie z zachowaniem proporcji)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None

    def set_background(self, path: str):
        """Ładuje nowe tło. Brak pliku = czarne tło."""
        if path and os.path.exists(path):
            self._pixmap = QPixmap(path)
        else:
            self._pixmap = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width()  - scaled.width())  // 2
            y = (self.height() - scaled.height()) // 2
            painter.fillRect(self.rect(), QColor("#000000"))
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(self.rect(), QColor("#000000"))


# ─────────────────────────── SUWAK CZASU TRWANIA

class DurationSlider(QWidget):
    """Suwak z wartościami dyskretnymi (minuty) i podpisem bieżącej wartości."""

    value_changed = pyqtSignal(int)  # wartość w minutach

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = DURATION_VALUES
        self._index  = DURATION_VALUES.index(30)  # domyślnie 30 min
        self._build_ui()

    def _build_ui(self):
        from PyQt6.QtWidgets import QSlider
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._label = QLabel(self.tr("Duration: %1 min").replace("%1", "30"))
        self._label.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(self._label)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, len(self._values) - 1)
        self._slider.setValue(self._index)
        self._slider.setTickPosition(
            self._slider.TickPosition.TicksBelow
        )
        self._slider.setTickInterval(1)
        layout.addWidget(self._slider)

        # Skala wartości pod suwakiem
        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        for i, v in enumerate(self._values):
            lbl = QLabel(str(v))
            lbl.setStyleSheet("color: #888; font-size: 10px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scale_row.addWidget(lbl)
            if i < len(self._values) - 1:
                scale_row.addStretch(1)
        layout.addLayout(scale_row)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, idx: int):
        self._index = idx
        val = self._values[idx]
        self._label.setText(self.tr("Duration: %1 min").replace("%1", str(val)))
        self.value_changed.emit(val)

    @property
    def value(self) -> int:
        return self._values[self._index]

    def restore(self, minutes: int):
        if minutes in self._values:
            self._slider.setValue(self._values.index(minutes))


# ─────────────────────────── SKALOWALNY NAPIS

class _ScalableLabel(QLabel):
    """QLabel który skaluje czcionkę do dostępnej szerokości (max 72pt, bold, #e0e0e0)."""

    _MAX_PT = 72
    _MIN_PT = 16

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color: #e0e0e0; background: transparent;")
        self._apply_font(self._MAX_PT)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_font()

    def _fit_font(self):
        avail = self.width()
        if avail <= 0:
            return
        pt = self._MAX_PT
        fm = self.fontMetrics()
        while pt > self._MIN_PT and fm.horizontalAdvance(self.text()) > avail - 8:
            pt -= 1
            self._apply_font(pt)
            fm = self.fontMetrics()

    def _apply_font(self, pt: int):
        f = QFont()
        f.setPointSize(pt)
        f.setBold(True)
        self.setFont(f)


# ─────────────────────────── PANEL KONFIGURACJI

class ConfigPanel(QWidget):
    """Formularz przed startem sesji."""

    start_requested = pyqtSignal(str, int)   # email, duration_min
    private_requested = pyqtSignal(int)      # duration_min

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.addStretch(1)

        # Duży napis — skaluje czcionkę do dostępnej szerokości, max 72pt
        prepare_lbl = _ScalableLabel(self.tr("Prepare session..."))
        outer.addWidget(prepare_lbl)

        outer.addSpacing(24)

        group = QGroupBox(self.tr("New Session"))
        group.setMaximumWidth(520)
        inner = QVBoxLayout(group)
        inner.setSpacing(16)

        # Email
        email_lbl = QLabel(self.tr("Email / Home / Private"))
        email_lbl.setStyleSheet("font-weight: 600;")
        inner.addWidget(email_lbl)

        self.email_field = QLineEdit()
        self.email_field.setPlaceholderText(self.tr("client@example.com  |  home  |  (empty = private)"))
        self.email_field.setFixedHeight(36)
        self.email_field.textChanged.connect(self._on_email_changed)
        inner.addWidget(self.email_field)

        # Info trybu
        self.mode_info = QLabel("")
        self.mode_info.setStyleSheet("color: #aaa; font-style: italic;")
        self.mode_info.setWordWrap(True)
        inner.addWidget(self.mode_info)

        inner.addSpacing(8)

        # Suwak czasu
        self.duration_slider = DurationSlider()
        inner.addWidget(self.duration_slider)

        inner.addSpacing(12)

        # Przyciski
        btn_row = QHBoxLayout()

        self.btn_home = QPushButton(self.tr("HOME"))
        self.btn_home.setFixedHeight(38)
        self.btn_home.clicked.connect(self._on_home)
        btn_row.addWidget(self.btn_home)

        self.btn_private = QPushButton(self.tr("PRIVATE"))
        self.btn_private.setFixedHeight(38)
        self.btn_private.clicked.connect(self._on_private)
        btn_row.addWidget(self.btn_private)

        btn_row.addStretch(1)

        self.btn_start = QPushButton(self.tr("▶  START SESSION"))
        self.btn_start.setFixedHeight(42)
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet(
            "QPushButton:enabled  { font-weight: bold; background-color: #1b5e20; color: #e8e8e8; }"
            "QPushButton:disabled { font-weight: bold; color: #555; }"
        )
        self.btn_start.clicked.connect(self._on_start)
        btn_row.addWidget(self.btn_start)

        inner.addLayout(btn_row)

        outer.addWidget(group, 0, Qt.AlignmentFlag.AlignCenter)
        outer.addStretch(2)

    # ─── logika formularza

    def _on_email_changed(self, text: str):
        self._update_mode_info(text.strip().lower())

    def _update_mode_info(self, email: str):
        if email == "home":
            self.mode_info.setText(self.tr("Local session — photos saved locally, no upload."))
            self.btn_start.setEnabled(True)
            self.btn_home.setEnabled(False)
            self.btn_private.setEnabled(True)
        elif email == "":
            self.mode_info.setText("")
            self.btn_start.setEnabled(False)
            self.btn_home.setEnabled(True)
            self.btn_private.setEnabled(True)
        elif EMAIL_RE.match(email):
            self.mode_info.setText(self.tr("Client session — photos will be uploaded and sent to %1.").replace("%1", email))
            self.btn_start.setEnabled(True)
            self.btn_home.setEnabled(True)
            self.btn_private.setEnabled(True)
        else:
            self.mode_info.setText(self.tr("Enter a valid email address, 'home', or leave empty for private session."))
            self.btn_start.setEnabled(False)
            self.btn_home.setEnabled(True)
            self.btn_private.setEnabled(True)

    def _on_home(self):
        self.email_field.setText("home")
        self.email_field.setEnabled(False)
        self.btn_home.setEnabled(False)
        self.btn_private.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.mode_info.setText(self.tr("Local session — photos saved locally, no upload."))

    def _on_private(self):
        self.email_field.clear()
        self.email_field.setEnabled(False)
        self.btn_home.setEnabled(True)
        self.btn_private.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.mode_info.setText(self.tr("Private session — photos stay on SD card only."))

    def _on_start(self):
        email = self.email_field.text().strip().lower()
        duration = self.duration_slider.value

        if not self.email_field.isEnabled():
            # HOME lub PRIVATE — email jest pusty lub "home"
            if not email:
                # PRIVATE
                self.private_requested.emit(duration)
                return

        self.start_requested.emit(email, duration)

    def reset(self):
        """Przywraca formularz do stanu początkowego."""
        self.email_field.setEnabled(True)
        self.email_field.clear()
        self.mode_info.setText("")
        self.btn_start.setEnabled(False)
        self.btn_home.setEnabled(True)
        self.btn_private.setEnabled(True)


# ─────────────────────────── PANEL AKTYWNEJ SESJI

class ActiveSessionPanel(BackgroundWidget):
    """Ekran z tłem podczas trwania/zakończenia sesji."""

    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.set_background(BG_ACTIVE)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)

        layout.addStretch(2)

        # Countdown
        self.countdown_label = QLabel("--:--")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(72)
        font.setBold(True)
        self.countdown_label.setFont(font)
        self.countdown_label.setStyleSheet("color: #e0e0e0; background: transparent;")
        layout.addWidget(self.countdown_label)

        layout.addSpacing(16)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFixedHeight(12)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                background-color: rgba(0,0,0,120);
                border-radius: 6px;
                border: 1px solid rgba(255,255,255,40);
            }
            QProgressBar::chunk {
                background-color: rgba(255,255,255,200);
                border-radius: 6px;
            }
        """)
        layout.addWidget(self.progress)

        layout.addSpacing(12)

        # Info (email + tryb)
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet(
            "color: rgba(255,255,255,180); font-size: 14px; background: transparent;"
        )
        layout.addWidget(self.info_label)

        layout.addSpacing(20)

        # Import progress (ukryty podczas sesji)
        self.import_label = QLabel("")
        self.import_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_label.setStyleSheet(
            "color: rgba(255,255,255,180); font-size: 13px; background: transparent;"
        )
        self.import_label.hide()
        layout.addWidget(self.import_label)

        layout.addStretch(1)

        # Przycisk STOP
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_stop = QPushButton(self.tr("■  STOP SESSION"))
        self.btn_stop.setFixedSize(220, 48)
        self.btn_stop.setStyleSheet(
            "font-weight: bold; font-size: 14px; "
            "background-color: #b71c1c; color: #e8e8e8; border-radius: 4px;"
        )
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addStretch(1)

    def update_countdown(self, remaining_sec: int, total_sec: int):
        """Aktualizuje wyświetlacz czasu i pasek postępu."""
        m = remaining_sec // 60
        s = remaining_sec % 60
        self.countdown_label.setText(f"{m:02d}:{s:02d}")

        pct = int(remaining_sec / total_sec * 100) if total_sec > 0 else 0
        self.progress.setValue(pct)

    def show_countdown_pre(self, remaining: int):
        """Wyświetla odliczanie przed startem sesji."""
        self.countdown_label.setText(self.tr("Starting in %1...").replace("%1", str(remaining)))
        self.progress.setValue(100)

    def set_session_info(self, context: SessionContext):
        """Ustawia etykietę info (email + tryb + czas)."""
        mode_str = {
            SessionMode.CLIENT:  f"{context.email}",
            SessionMode.HOME:    self.tr("Home session"),
            SessionMode.PRIVATE: self.tr("Private session"),
        }.get(context.mode, "")
        self.info_label.setText(f"{mode_str}  ·  {context.duration_min} min")

    def show_import_progress(self, current: int, total: int, filename: str):
        """Pokazuje postęp importu."""
        self.import_label.show()
        self.import_label.setText(self.tr("Importing %1/%2: %3").replace("%1", str(current)).replace("%2", str(total)).replace("%3", filename))
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText(self.tr("Importing..."))

    def show_result(self, summary: SessionSummary):
        """Przełącza tło i wyświetla wynik sesji."""
        if summary.end_reason == EndReason.TIMEOUT:
            self.set_background(BG_FINISHED)
            self.countdown_label.setText("00:00")
        else:
            self.set_background(BG_INTERRUPTED)
            self.countdown_label.setText(self.tr("Stopped"))

        self.import_label.hide()
        self.btn_stop.hide()
        self.progress.setValue(0)

        shots = summary.shot_count if summary.context.mode != SessionMode.PRIVATE else "—"
        self.info_label.setText(
            f"Duration: {summary.duration_str}  ·  Shots: {shots}"
        )


# ─────────────────────────── PANEL PODSUMOWANIA

class SummaryPanel(QWidget):
    """Ekran po zakończeniu sesji — wyniki i przyciski nawigacji."""

    go_darkroom   = pyqtSignal()
    new_session   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)

        self.title = QLabel(self.tr("Session complete"))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        self.title.setFont(font)
        layout.addWidget(self.title)

        layout.addSpacing(12)

        self.details = QLabel("")
        self.details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details.setStyleSheet("color: #aaa; font-size: 13px;")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)

        layout.addSpacing(8)

        self.warnings_label = QLabel("")
        self.warnings_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warnings_label.setStyleSheet("color: #e65100; font-size: 12px;")
        self.warnings_label.setWordWrap(True)
        layout.addWidget(self.warnings_label)

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_darkroom = QPushButton(self.tr("→ Darkroom"))
        self.btn_darkroom.setFixedHeight(42)
        self.btn_darkroom.setStyleSheet(
            "font-weight: bold; background-color: #1565c0; color: #e8e8e8;"
        )
        self.btn_darkroom.clicked.connect(self.go_darkroom.emit)
        btn_row.addWidget(self.btn_darkroom)

        btn_row.addSpacing(12)

        self.btn_new = QPushButton(self.tr("New Session"))
        self.btn_new.setFixedHeight(42)
        self.btn_new.clicked.connect(self.new_session.emit)
        btn_row.addWidget(self.btn_new)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addStretch(1)

    def populate(self, summary: SessionSummary):
        """Wypełnia panel danymi z podsumowania."""
        ctx = summary.context

        if summary.end_reason == EndReason.TIMEOUT:
            self.title.setText(self.tr("Session finished"))
        elif summary.end_reason == EndReason.USB_DETECTED:
            self.title.setText(self.tr("Session stopped — camera connected"))
        else:
            self.title.setText(self.tr("Session interrupted"))

        shots_str = str(summary.shot_count) if ctx.mode != SessionMode.PRIVATE else self.tr("unknown (private)")
        sync_str  = {
            "done":    self.tr("✓ Synced to Google Drive"),
            "pending": self.tr("Sync pending..."),
            "failed":  self.tr("⚠ Sync failed"),
            "skipped": "",
        }.get(ctx.sync_status, "")

        lines = [
            self.tr("Duration: %1").replace("%1", summary.duration_str),
            self.tr("Shots imported: %1").replace("%1", shots_str),
        ]
        if ctx.session_path:
            lines.append(self.tr("Folder: %1").replace("%1", ctx.session_path))
        if sync_str:
            lines.append(sync_str)

        self.details.setText("\n".join(lines))

        if summary.warnings:
            self.warnings_label.setText(self.tr("Warnings: %1").replace("%1", " · ".join(summary.warnings[:3])))
        else:
            self.warnings_label.setText("")

        # Darkroom niedostępny dla PRIVATE
        self.btn_darkroom.setVisible(ctx.mode != SessionMode.PRIVATE)


# ─────────────────────────── GŁÓWNY WIDOK

class SessionView(QWidget):
    """
    Główny widok sesji fotograficznej.
    Sygnały wychodzące do MainWindow:
      session_finished(summary) — do auto-load w darkroom
      status_message(str)       — do paska stanu
    """

    session_finished = pyqtSignal(object)   # SessionSummary
    status_message   = pyqtSignal(str)
    camera_detected  = pyqtSignal()         # aparat wykryty przez polling — zleca probe

    # Panele stacka
    _PAGE_CONFIG  = 0
    _PAGE_ACTIVE  = 1
    _PAGE_SUMMARY = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._runner: Optional[SessionRunner] = None
        self._settings = QSettings("Grzeza", "SessionsAssistant")
        self._camera_on = False
        self._sd_on = False
        self._settings_worker = None  # Worker ustawień (aktywny gdy widok aktywny i aparat podłączony)
        self._view_active = False     # True gdy session_view jest widoczny
        # Timer do pollingu USB gdy brak aparatu
        self._usb_poll_timer = QTimer(self)
        self._usb_poll_timer.timeout.connect(self._poll_usb)
        self._build_ui()
        self._restore_state()

    # ─────────────────────────── UI

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(12)

        # ── LEWY PANEL: ustawienia kamery ────────────────────────────────
        self._left_panel = QWidget()
        self._left_panel.setMinimumWidth(760)
        left_layout = QVBoxLayout(self._left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # QStackedWidget: 0 = kontrolki, 1 = overlay
        self._left_stack = QStackedWidget()

        # ── Strona 0: dwie kolumny kontrolek (jak w CameraView) ──────────
        controls_widget = QWidget()
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(30)

        # Kolumna 1: Exposure
        col1 = QWidget()
        col1.setMinimumWidth(450)
        col1_layout = QVBoxLayout(col1)
        col1_layout.setContentsMargins(0, 0, 0, 0)
        self.exposure_ctrl = ExposureControls()
        col1_layout.addWidget(self.exposure_ctrl, 3)
        col1_layout.addSpacing(20)
        col1_layout.addStretch(1)

        # Kolumna 2: Image + Focus
        col2 = QWidget()
        col2.setMinimumWidth(280)
        col2_layout = QVBoxLayout(col2)
        col2_layout.setContentsMargins(0, 0, 0, 0)
        self.image_ctrl = ImageControls()
        self.focus_ctrl = AutofocusControls()
        col2_layout.addWidget(self.image_ctrl, 2)
        col2_layout.addSpacing(23)
        col2_layout.addWidget(self.focus_ctrl, 1)
        col2_layout.addSpacing(20)
        col2_layout.addStretch(1)

        controls_layout.addWidget(col1, 5)
        controls_layout.addWidget(col2, 3)

        # ── Strona 1: overlay ─────────────────────────────────────────────
        no_camera_widget = QWidget()
        no_camera_widget.setStyleSheet("background: #3d3d3d;")
        no_cam_layout = QVBoxLayout(no_camera_widget)
        no_cam_layout.setContentsMargins(0, 0, 0, 0)
        no_cam_layout.setSpacing(0)

        # Obraz wypełniający panel z zachowaniem proporcji
        self._no_camera_img = QLabel()
        self._no_camera_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_camera_img.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        img_path = os.path.join(
            "assets", "pictures", "korpus-canon-eos-rp-not-presented-full.jpg"
        )
        self._no_camera_pixmap         = QPixmap(img_path) if os.path.exists(img_path) else QPixmap()
        self._no_camera_pixmap_default = self._no_camera_pixmap   # kopia do przywracania

        session_img_path = os.path.join("assets", "pictures", "session-start.jpg")
        if os.path.exists(session_img_path):
            _raw = QPixmap(session_img_path)
            # Obróć -90° (w lewo) — EXIF ignorowany przez Qt
            _t = QTransform().rotate(-90)
            self._session_pixmap = _raw.transformed(_t, Qt.TransformationMode.SmoothTransformation)
        else:
            self._session_pixmap = QPixmap()
        no_cam_layout.addWidget(self._no_camera_img, 1)

        # Etykieta pod obrazem — tej samej szerokości co wyrenderowany obraz
        self._overlay_label = QLabel(
            self.tr("Insert SD card, then connect camera via USB.\n"
                    "Make sure the camera is turned on.")
        )
        self._overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay_label.setStyleSheet(
            "color: #aaa; font-size: 13px; background: #3d3d3d; padding: 10px 0;"
        )
        self._overlay_label.setWordWrap(True)
        no_cam_layout.addWidget(self._overlay_label, 0)

        # Skalowanie z zachowaniem proporcji + sync szerokości etykiety z obrazem
        def _resize_no_cam(event):
            if not self._no_camera_pixmap.isNull():
                scaled = self._no_camera_pixmap.scaled(
                    self._no_camera_img.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._no_camera_img.setPixmap(scaled)
                w = scaled.width()
                self._overlay_label.setFixedWidth(w)
            QWidget.resizeEvent(no_camera_widget, event)

        no_camera_widget.resizeEvent = _resize_no_cam

        self._left_stack.addWidget(controls_widget)   # index 0
        self._left_stack.addWidget(no_camera_widget)  # index 1

        left_layout.addWidget(self._left_stack)

        # ── PRAWY PANEL: zawartość sesji (stack config/active/summary) ───
        right_panel = QWidget()
        right_panel.setMinimumWidth(300)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()

        self._config_panel  = ConfigPanel()
        self._active_panel  = ActiveSessionPanel()
        self._summary_panel = SummaryPanel()

        self._stack.addWidget(self._config_panel)   # 0
        self._stack.addWidget(self._active_panel)   # 1
        self._stack.addWidget(self._summary_panel)  # 2

        right_layout.addWidget(self._stack)

        # Splitter: lewy = ustawienia, prawy = sesja
        self._splitter.addWidget(self._left_panel)
        self._splitter.addWidget(right_panel)
        self._splitter.setStretchFactor(0, 4)
        self._splitter.setStretchFactor(1, 6)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)

        main_layout.addWidget(self._splitter)

        # Sygnały paneli
        self._config_panel.start_requested.connect(self._on_start_session)
        self._config_panel.private_requested.connect(
            lambda dur: self._on_start_session("", dur)
        )
        self._active_panel.stop_requested.connect(self._on_stop_requested)
        self._summary_panel.new_session.connect(self._on_new_session)
        self._summary_panel.go_darkroom.connect(self._on_go_darkroom)

    # ─────────────────────────── Cykl życia widoku

    def on_enter(self):
        """Wywoływane przez MainWindow przy przejściu do widoku Session."""
        self._view_active = True
        # NIE startujemy workera tu — probe (wywoływane po on_enter) wywoła
        # set_camera_ready, które dopiero uruchomi workera po zwolnieniu USB.

    def on_leave(self):
        """Wywoływane przez MainWindow przy opuszczeniu widoku Session."""
        self._view_active = False
        self._stop_settings_worker()
        self._stop_usb_polling()

    # ─────────────────────────── Worker ustawień (bez LV)

    def _start_settings_worker(self):
        """Uruchamia CameraSettingsWorker z inicjalizacją trybu sesji."""
        if self._settings_worker and self._settings_worker.isRunning():
            return
        from core.camera_settings_worker import CameraSettingsWorker
        self._settings_worker = CameraSettingsWorker(session_mode_init=True)
        self._settings_worker.settings_loaded.connect(self.exposure_ctrl.sync_with_camera)
        self._settings_worker.settings_loaded.connect(self.image_ctrl.sync_with_camera)
        self._settings_worker.settings_loaded.connect(self.focus_ctrl.sync_with_camera)
        self._settings_worker.status_message.connect(self.status_message)
        self.exposure_ctrl.gphoto = self._settings_worker
        self.image_ctrl.gphoto    = self._settings_worker
        self.focus_ctrl.gphoto    = self._settings_worker
        self._settings_worker.start()

    def _stop_settings_worker(self):
        """Zatrzymuje CameraSettingsWorker synchronicznie (max 3s — czas na init gphoto2)."""
        if self._settings_worker:
            self.exposure_ctrl.gphoto = None
            self.image_ctrl.gphoto    = None
            self.focus_ctrl.gphoto    = None
            self._settings_worker.keep_running = False
            if self._settings_worker.isRunning():
                if not self._settings_worker.wait(3000):
                    self._settings_worker.terminate()
            self._settings_worker = None

    def set_camera_ready(self, camera_on: bool, sd_on: bool):
        """Wywoływane z MainWindow — włącza/wyłącza panel ustawień kamery."""
        self._camera_on = camera_on
        self._sd_on = sd_on
        if camera_on and sd_on:
            self._stop_usb_polling()
            self._left_stack.setCurrentIndex(0)
            # Uruchom worker ustawień jeśli widok aktywny i sesja nieaktywna
            if self._view_active and not self.is_session_active():
                self._start_settings_worker()
        else:
            self._stop_settings_worker()
            self._set_overlay_image(self._no_camera_pixmap_default)
            self._overlay_label.setText(
                self.tr("Camera not detected.\n"
                        "Connect camera via USB and insert SD card\n"
                        "to enable camera settings.")
            )
            self._left_stack.setCurrentIndex(1)
            self._start_usb_polling()

    def _start_usb_polling(self):
        """Startuje polling USB — wykrywa podłączenie aparatu."""
        if self._usb_poll_timer.isActive():
            return
        self._usb_poll_timer.start(2000)

    def _stop_usb_polling(self):
        """Zatrzymuje polling USB."""
        self._usb_poll_timer.stop()

    def _poll_usb(self):
        """Sprawdza lsusb — gdy aparat wykryty, włącza kontrolki."""
        if _lsusb_has_canon():
            self._stop_usb_polling()
            # Zlecamy probe do MainWindow przez sygnał
            self.camera_detected.emit()

    def sync_camera_settings(self, settings: dict):
        """Synchronizuje kontrolki z ostatnimi ustawieniami aparatu."""
        if not settings:
            return
        self.exposure_ctrl.sync_with_camera(settings)
        self.image_ctrl.sync_with_camera(settings)
        self.focus_ctrl.sync_with_camera(settings)

    def _set_overlay_image(self, pixmap: 'QPixmap'):
        """Ustawia pixmapę w panelu overlay i od razu ją skaluje."""
        self._no_camera_pixmap = pixmap
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self._no_camera_img.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._no_camera_img.setPixmap(scaled)
            self._overlay_label.setFixedWidth(scaled.width())
        else:
            self._no_camera_img.clear()

    def _lock_camera_panel(self):
        """Blokuje lewy panel — aparat działa bezprzewodowo, zero komunikacji USB."""
        self._set_overlay_image(self._session_pixmap)
        self._overlay_label.setText(
            self.tr("Camera is in wireless mode.\n\n"
                    "USB communication is disabled\n"
                    "during an active session.\n\n"
                    "Use remote shutter to take photos.")
        )
        self._left_stack.setCurrentIndex(1)

    # ─────────────────────────── START SESJI

    def _on_start_session(self, email: str, duration_min: int):
        """Pokazuje dialog USB → tworzy kontekst i uruchamia SessionRunner."""
        # Zatrzymaj worker ustawień — zwalnia USB przed dialogiem
        self._stop_settings_worker()
        # Dialog OFF→ON: bez USB podczas sesji aparat aktywuje moduł BT
        dlg = _UsbDisconnectDialog(self)
        dlg.status_changed.connect(self.status_message)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return  # użytkownik anulował

        # KLUCZOWE: natychmiast blokujemy komunikację z aparatem —
        # aparat działa teraz bezprzewodowo, USB musi być wolny
        self._lock_camera_panel()

        from PyQt6.QtCore import QSettings as _QS
        settings = _QS("Grzeza", "SessionsAssistant")
        base_dir   = settings.value("session/directory",
                                    os.path.expanduser("~/Obrazy/sessions"))
        captures   = settings.value("session/captures_subdir", "captures")
        rclone_rem = settings.value("rclone/remote", "")
        rclone_dst = settings.value("rclone/destination", "Sessions")

        # Snapshot ustawień aparatu (opcjonalny — przekazywany z zewnątrz)
        cam_settings = self._current_camera_settings or CameraSettings()

        ctx = make_session_context(email, duration_min, base_dir, captures, cam_settings)
        store = SessionStore(base_dir)

        self._runner = SessionRunner(ctx, store, rclone_rem, rclone_dst)

        # Podłącz sygnały
        self._runner.state_changed.connect(self._on_state_changed)
        self._runner.timer_tick.connect(self._on_timer_tick)
        self._runner.countdown_tick.connect(self._on_countdown_tick)
        self._runner.import_progress.connect(self._on_import_progress)
        self._runner.sync_progress.connect(self._on_sync_progress)
        self._runner.session_finished.connect(self._on_session_finished)
        self._runner.warning.connect(lambda m: self.status_message.emit(f"⚠ {m}"))
        self._runner.error.connect(lambda m: self.status_message.emit(f"✖ {m}"))

        # Przejdź do ekranu aktywnego
        self._active_panel.set_background(BG_ACTIVE)
        self._active_panel.set_session_info(ctx)
        self._active_panel.btn_stop.setEnabled(True)
        self._active_panel.btn_stop.setText("■  STOP SESSION")
        self._active_panel.import_label.hide()
        self._active_panel.countdown_label.setText(
            f"{duration_min:02d}:00"
        )
        self._active_panel.progress.setValue(100)
        self._stack.setCurrentIndex(self._PAGE_ACTIVE)

        mode_msg = {
            "client":  f"Client session · {ctx.email} · {duration_min} min",
            "home":    f"Home session · {duration_min} min",
            "private": f"Private session · {duration_min} min",
        }.get(ctx.mode.value, "")
        self.status_message.emit(mode_msg)

        self._runner.start()
        self._save_state(duration_min)

    # ─────────────────────────── SYGNAŁY RUNNERA

    def _on_state_changed(self, state: SessionState):
        msgs = {
            SessionState.COUNTDOWN:  "Preparing session...",
            SessionState.ACTIVE:     "Session active",
            SessionState.STOPPING:   "Stopping session...",
            SessionState.IMPORTING:  "Importing photos...",
            SessionState.SYNCING:    "Syncing to Google Drive...",
            SessionState.FINISHED:   "Session finished",
            SessionState.INTERRUPTED:"Session interrupted",
            SessionState.FAILED:     "Session failed",
        }
        if state in msgs:
            self.status_message.emit(msgs[state])

        if state in (SessionState.IMPORTING,):
            self._active_panel.import_label.show()

    def _on_timer_tick(self, remaining: int, total: int):
        self._active_panel.update_countdown(remaining, total)

    def _on_countdown_tick(self, remaining: int):
        self._active_panel.show_countdown_pre(remaining)

    def _on_import_progress(self, current: int, total: int, filename: str):
        self._active_panel.show_import_progress(current, total, filename)

    def _on_sync_progress(self, line: str):
        self.status_message.emit(f"Sync: {line}")

    def _on_session_finished(self, summary: SessionSummary):
        self._active_panel.show_result(summary)
        self._summary_panel.populate(summary)
        self._stack.setCurrentIndex(self._PAGE_SUMMARY)
        self.session_finished.emit(summary)

        # Cleanup runnera
        if self._runner:
            self._runner.deleteLater()
            self._runner = None

    # ─────────────────────────── STOP / NAWIGACJA

    def _on_stop_requested(self):
        if self._runner and self._runner.isRunning():
            self._runner.request_stop()
            self._active_panel.btn_stop.setEnabled(False)
            self._active_panel.btn_stop.setText("Stopping...")
            self.status_message.emit("Stopping session...")

    def _on_new_session(self):
        self._config_panel.reset()
        self._stack.setCurrentIndex(self._PAGE_CONFIG)
        # Przywróć stan panelu kamery (probe zadecyduje czy aktywny czy nie)
        self.set_camera_ready(self._camera_on, self._sd_on)

    def _on_go_darkroom(self):
        """Sygnalizuje MainWindow żeby przełączył na Darkroom."""
        # MainWindow podłącza session_finished i sam nawiguje
        pass

    def is_session_active(self) -> bool:
        """Zwraca True gdy sesja trwa (USB odłączone, aparat bezprzewodowy)."""
        return self._runner is not None and self._runner.isRunning()

    # ─────────────────────────── KAMERA — snapshot ustawień

    _current_camera_settings: Optional[CameraSettings] = None

    def set_camera_settings(self, settings: CameraSettings):
        """Wywoływane z MainWindow gdy Camera view był ostatnio aktywny."""
        self._current_camera_settings = settings

    # ─────────────────────────── PERSISTENCE

    def _save_state(self, duration_min: int):
        self._settings.setValue("session/last_duration", duration_min)

    def _restore_state(self):
        dur = self._settings.value("session/last_duration", 30, type=int)
        if dur in DURATION_VALUES:
            self._config_panel.duration_slider.restore(dur)
