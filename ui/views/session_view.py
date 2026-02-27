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

from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QFont, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QProgressBar, QGroupBox, QFrame,
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

# ─────────────────────────── STAŁE

DURATION_VALUES = [1, 3, 5, 10, 15, 30, 45, 60, 90]  # minuty

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

BG_ACTIVE      = os.path.join("assets", "pictures", "session-active.jpg")
BG_FINISHED    = os.path.join("assets", "pictures", "session-finished.jpg")
BG_INTERRUPTED = os.path.join("assets", "pictures", "session-interrupted.jpg")


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

        self._label = QLabel("Duration: 30 min")
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
        self._label.setText(f"Duration: {val} min")
        self.value_changed.emit(val)

    @property
    def value(self) -> int:
        return self._values[self._index]

    def restore(self, minutes: int):
        if minutes in self._values:
            self._slider.setValue(self._values.index(minutes))


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

        group = QGroupBox("New Session")
        group.setMaximumWidth(520)
        inner = QVBoxLayout(group)
        inner.setSpacing(16)

        # Email
        email_lbl = QLabel("Email / Home / Private")
        email_lbl.setStyleSheet("font-weight: 600;")
        inner.addWidget(email_lbl)

        self.email_field = QLineEdit()
        self.email_field.setPlaceholderText("client@example.com  |  home  |  (empty = private)")
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

        self.btn_home = QPushButton("HOME")
        self.btn_home.setFixedHeight(38)
        self.btn_home.clicked.connect(self._on_home)
        btn_row.addWidget(self.btn_home)

        self.btn_private = QPushButton("PRIVATE")
        self.btn_private.setFixedHeight(38)
        self.btn_private.clicked.connect(self._on_private)
        btn_row.addWidget(self.btn_private)

        btn_row.addStretch(1)

        self.btn_start = QPushButton("▶  START SESSION")
        self.btn_start.setFixedHeight(42)
        self.btn_start.setEnabled(False)
        self.btn_start.setStyleSheet(
            "QPushButton:enabled  { font-weight: bold; background-color: #1b5e20; color: white; }"
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
            self.mode_info.setText("Local session — photos saved locally, no upload.")
            self.btn_start.setEnabled(True)
            self.btn_home.setEnabled(False)
            self.btn_private.setEnabled(True)
        elif email == "":
            self.mode_info.setText("")
            self.btn_start.setEnabled(False)
            self.btn_home.setEnabled(True)
            self.btn_private.setEnabled(True)
        elif EMAIL_RE.match(email):
            self.mode_info.setText(f"Client session — photos will be uploaded and sent to {email}.")
            self.btn_start.setEnabled(True)
            self.btn_home.setEnabled(True)
            self.btn_private.setEnabled(True)
        else:
            self.mode_info.setText("Enter a valid email address, 'home', or leave empty for private session.")
            self.btn_start.setEnabled(False)
            self.btn_home.setEnabled(True)
            self.btn_private.setEnabled(True)

    def _on_home(self):
        self.email_field.setText("home")
        self.email_field.setEnabled(False)
        self.btn_home.setEnabled(False)
        self.btn_private.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.mode_info.setText("Local session — photos saved locally, no upload.")

    def _on_private(self):
        self.email_field.clear()
        self.email_field.setEnabled(False)
        self.btn_home.setEnabled(True)
        self.btn_private.setEnabled(False)
        self.btn_start.setEnabled(True)
        self.mode_info.setText("Private session — photos stay on SD card only.")

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
        self.countdown_label.setStyleSheet("color: white; background: transparent;")
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
        self.btn_stop = QPushButton("■  STOP SESSION")
        self.btn_stop.setFixedSize(220, 48)
        self.btn_stop.setStyleSheet(
            "font-weight: bold; font-size: 14px; "
            "background-color: #b71c1c; color: white; border-radius: 4px;"
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
        self.countdown_label.setText(f"Starting in {remaining}...")
        self.progress.setValue(100)

    def set_session_info(self, context: SessionContext):
        """Ustawia etykietę info (email + tryb + czas)."""
        mode_str = {
            SessionMode.CLIENT:  f"{context.email}",
            SessionMode.HOME:    "Home session",
            SessionMode.PRIVATE: "Private session",
        }.get(context.mode, "")
        self.info_label.setText(f"{mode_str}  ·  {context.duration_min} min")

    def show_import_progress(self, current: int, total: int, filename: str):
        """Pokazuje postęp importu."""
        self.import_label.show()
        self.import_label.setText(f"Importing {current}/{total}: {filename}")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Importing...")

    def show_result(self, summary: SessionSummary):
        """Przełącza tło i wyświetla wynik sesji."""
        if summary.end_reason == EndReason.TIMEOUT:
            self.set_background(BG_FINISHED)
            self.countdown_label.setText("00:00")
        else:
            self.set_background(BG_INTERRUPTED)
            self.countdown_label.setText("Stopped")

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

        self.title = QLabel("Session complete")
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

        self.btn_darkroom = QPushButton("→ Darkroom")
        self.btn_darkroom.setFixedHeight(42)
        self.btn_darkroom.setStyleSheet(
            "font-weight: bold; background-color: #1565c0; color: white;"
        )
        self.btn_darkroom.clicked.connect(self.go_darkroom.emit)
        btn_row.addWidget(self.btn_darkroom)

        btn_row.addSpacing(12)

        self.btn_new = QPushButton("New Session")
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
            self.title.setText("Session finished")
        elif summary.end_reason == EndReason.USB_DETECTED:
            self.title.setText("Session stopped — camera connected")
        else:
            self.title.setText("Session interrupted")

        shots_str = str(summary.shot_count) if ctx.mode != SessionMode.PRIVATE else "unknown (private)"
        sync_str  = {
            "done":    "✓ Synced to Google Drive",
            "pending": "Sync pending...",
            "failed":  "⚠ Sync failed",
            "skipped": "",
        }.get(ctx.sync_status, "")

        lines = [
            f"Duration: {summary.duration_str}",
            f"Shots imported: {shots_str}",
        ]
        if ctx.session_path:
            lines.append(f"Folder: {ctx.session_path}")
        if sync_str:
            lines.append(sync_str)

        self.details.setText("\n".join(lines))

        if summary.warnings:
            self.warnings_label.setText("Warnings: " + " · ".join(summary.warnings[:3]))
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

    # Panele stacka
    _PAGE_CONFIG  = 0
    _PAGE_ACTIVE  = 1
    _PAGE_SUMMARY = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._runner: Optional[SessionRunner] = None
        self._settings = QSettings("Grzeza", "SessionsAssistant")
        self._build_ui()
        self._restore_state()

    # ─────────────────────────── UI

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()

        self._config_panel  = ConfigPanel()
        self._active_panel  = ActiveSessionPanel()
        self._summary_panel = SummaryPanel()

        self._stack.addWidget(self._config_panel)   # 0
        self._stack.addWidget(self._active_panel)   # 1
        self._stack.addWidget(self._summary_panel)  # 2

        layout.addWidget(self._stack)

        # Sygnały paneli
        self._config_panel.start_requested.connect(self._on_start_session)
        self._config_panel.private_requested.connect(
            lambda dur: self._on_start_session("", dur)
        )
        self._active_panel.stop_requested.connect(self._on_stop_requested)
        self._summary_panel.new_session.connect(self._on_new_session)
        self._summary_panel.go_darkroom.connect(self._on_go_darkroom)

    # ─────────────────────────── START SESJI

    def _on_start_session(self, email: str, duration_min: int):
        """Tworzy kontekst i uruchamia SessionRunner."""
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

    def _on_go_darkroom(self):
        """Sygnalizuje MainWindow żeby przełączył na Darkroom."""
        # MainWindow podłącza session_finished i sam nawiguje
        pass

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
