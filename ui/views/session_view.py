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

from PyQt6.QtCore import Qt, QSettings, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QFont, QColor, QTransform, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QProgressBar, QGroupBox, QFrame, QDialog, QSplitter, QCheckBox,
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
from ui.widgets.camera_settings_panel import CameraSettingsPanel
from ui.styles import BTN_STYLE_RED
from ui.dialogs.profile_browser_dialog import ProfileBrowserDialog
from ui.dialogs.usb_disconnect_dialog import UsbDisconnectDialog, _lsusb_has_canon
from ui.widgets.slider_with_scale import SliderWithScale

import qrcode
import core.session_codes as session_codes
from ui.dialogs.preferences_dialog import PreferencesDialog

# ─────────────────────────── STAŁE

DURATION_VALUES = [1, 3, 5, 10, 15, 30, 45, 60, 90]  # minuty

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

BG_ACTIVE      = os.path.join("assets", "pictures", "session-active.jpg")
BG_FINISHED    = os.path.join("assets", "pictures", "session-finished.jpg")
BG_INTERRUPTED = os.path.join("assets", "pictures", "session-interrupted.jpg")


# ─────────────────────────── SNAPSHOT KARTY SD

def _snapshot_card_files() -> set:
    """
    Szybki snapshot nazw plików na karcie SD aparatu (bez pobierania treści).
    Canon EOS RP zwraca mtime=0 — nie można filtrować po czasie; filtrujemy po tym
    czy plik istniał przed sesją.
    Zwraca pusty zbiór przy braku aparatu lub błędzie.
    """
    import logging as _log
    _logger = _log.getLogger(__name__)
    try:
        import gphoto2 as gp
        ctx = gp.Context()
        pil = gp.PortInfoList(); pil.load()
        al  = gp.CameraAbilitiesList(); al.load(ctx)
        cameras = al.detect(pil, ctx)
        if not cameras:
            return set()
        model, port = cameras[0]
        camera = gp.Camera()
        camera.set_abilities(al[al.lookup_model(model)])
        camera.set_port_info(pil[pil.lookup_path(port)])
        camera.init(ctx)
        filenames: set = set()
        try:
            dcim = camera.folder_list_folders("/store_00020001/DCIM", ctx)
            for i in range(dcim.count()):
                fpath = f"/store_00020001/DCIM/{dcim.get_name(i)}"
                files = camera.folder_list_files(fpath, ctx)
                for j in range(files.count()):
                    filenames.add(files.get_name(j))
        finally:
            camera.exit(ctx)
        _logger.info(f"Snapshot karty: {len(filenames)} plików przed sesją")
        return filenames
    except Exception as e:
        _logger.warning(f"Snapshot karty nie powiódł się: {e}")
        return set()


# ─────────────────────────── WIDGET TŁA

class BackgroundWidget(QWidget):
    """Widget wypełniający tło obrazem (skalowanie z zachowaniem proporcji).
    Nie wpływa na sizeHint okna — bezpieczny w trybie fullscreen/windowed."""

    def __init__(self, fill_color: str = "#000000", parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._fill = QColor(fill_color)

    def set_background(self, path: str):
        """Ładuje nowe tło. Brak pliku = tło kolorem fill."""
        if path and os.path.exists(path):
            self._pixmap = QPixmap(path)
        else:
            self._pixmap = None
        self.update()

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        return QSize(0, 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._fill)
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width()  - scaled.width())  // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)


# ─────────────────────────── SKALOWALNY NAPIS

class _ScalableLabel(QLabel):
    """QLabel który skaluje czcionkę do dostępnej szerokości, bold, #e0e0e0."""

    _MIN_PT = 14

    def __init__(self, text: str, max_pt: int = 50, parent=None):
        super().__init__(text, parent)
        self._max_pt = max_pt
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("color: #e0e0e0; background: transparent;")
        self._apply_font(max_pt)

    def setText(self, text: str):
        super().setText(text)
        self._fit_font()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_font()

    def _fit_font(self):
        avail = self.width()
        if avail <= 0:
            return
        pt = self._max_pt
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


class _ScalableImage(QLabel):
    """QLabel który skaluje obraz do dostępnej szerokości, z ograniczeniem max_h."""

    def __init__(self, max_h: int = 320, parent=None):
        super().__init__(parent)
        self._raw: Optional[QPixmap] = None
        self._max_h = max_h
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_image(self, path: str):
        self._raw = QPixmap(path) if path and os.path.exists(path) else None
        self._rescale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if not self._raw or self._raw.isNull() or self.width() <= 0:
            self.clear()
            return
        scaled = self._raw.scaledToWidth(self.width(), Qt.TransformationMode.SmoothTransformation)
        if scaled.height() > self._max_h:
            scaled = self._raw.scaledToHeight(self._max_h, Qt.TransformationMode.SmoothTransformation)
        super().setPixmap(scaled)


# ─────────────────────────── PANEL KONFIGURACJI

class ConfigPanel(QWidget):
    """Formularz przed startem sesji."""

    start_requested = pyqtSignal(str, int)    # email (""|"home"|adres), duration_min

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = ""   # "client" | "home" | "private" | ""
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.addStretch(1)

        prepare_lbl = _ScalableLabel(self.tr("Prepare session..."), max_pt=24)
        outer.addWidget(prepare_lbl)

        outer.addSpacing(24)

        group = QGroupBox(self.tr("New Session"))
        group.setMaximumWidth(520)
        inner = QVBoxLayout(group)
        inner.setSpacing(16)

        # Przyciski wyboru trybu — CLIENT | HOME | PRIVATE
        mode_row = QHBoxLayout()
        self.btn_client  = QPushButton(self.tr("CLIENT"))
        self.btn_home    = QPushButton(self.tr("HOME"))
        self.btn_private = QPushButton(self.tr("PRIVATE"))
        for b in (self.btn_client, self.btn_home, self.btn_private):
            b.setFixedHeight(38)
            mode_row.addWidget(b)
        mode_row.addStretch(1)
        self.btn_client.clicked.connect(self._on_client)
        self.btn_home.clicked.connect(self._on_home)
        self.btn_private.clicked.connect(self._on_private)
        inner.addLayout(mode_row)

        # Email — aktywny tylko w trybie CLIENT
        email_lbl = QLabel(self.tr("Client email"))
        email_lbl.setStyleSheet("font-weight: 600;")
        inner.addWidget(email_lbl)

        self.email_field = QLineEdit()
        self.email_field.setPlaceholderText(self.tr("client@example.com"))
        self.email_field.setFixedHeight(36)
        self.email_field.setEnabled(False)
        self.email_field.textChanged.connect(self._on_email_changed)
        self.email_field.returnPressed.connect(self._try_start)
        inner.addWidget(self.email_field)

        # Wiersz Telegram QR
        tg_row = QHBoxLayout()
        self.tg_icon = QLabel()
        _tg_qicon = QIcon.fromTheme("telegram")
        if not _tg_qicon.isNull():
            self.tg_icon.setPixmap(_tg_qicon.pixmap(20, 20))
        else:
            self.tg_icon.setText("✈")
        tg_row.addWidget(self.tg_icon)
        self.chk_share_code = QCheckBox(self.tr("Create sharing code (Telegram)"))
        tg_row.addWidget(self.chk_share_code)
        tg_row.addStretch()
        inner.addLayout(tg_row)

        # Info trybu
        self.mode_info = QLabel("")
        self.mode_info.setStyleSheet("color: #aaa; font-style: italic;")
        self.mode_info.setWordWrap(True)
        inner.addWidget(self.mode_info)

        inner.addSpacing(8)

        # Suwak czasu
        self.duration_slider = SliderWithScale(
            self.tr("Duration (min)"), [str(v) for v in DURATION_VALUES]
        )
        self.duration_slider.set_value("30")
        inner.addWidget(self.duration_slider)

        inner.addSpacing(12)

        # Przycisk START
        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.btn_start = QPushButton(self.tr("▶  START SESSION"))
        self.btn_start.setFixedHeight(42)
        self.btn_start.setEnabled(False)
        self.btn_start.setAutoDefault(True)
        self.btn_start.clicked.connect(self._on_start)
        start_row.addWidget(self.btn_start)
        start_row.addStretch(1)
        inner.addLayout(start_row)

        outer.addWidget(group, 0, Qt.AlignmentFlag.AlignCenter)
        outer.addStretch(1)

    # ─── helpers

    def _set_mode_bold(self, active_btn):
        """Pogrubia aktywny przycisk trybu, pozostałe normalne."""
        for b in (self.btn_client, self.btn_home, self.btn_private):
            f = b.font(); f.setBold(b is active_btn); b.setFont(f)

    def _set_start_ready(self, enabled: bool):
        self.btn_start.setEnabled(enabled)
        self.btn_start.setDefault(enabled)

    # ─── wybór trybu

    def _on_client(self):
        self._mode = "client"
        self._set_mode_bold(self.btn_client)
        self.email_field.setEnabled(True)
        self.tg_icon.setEnabled(True)
        self.chk_share_code.setEnabled(True)
        self.email_field.setFocus()
        self._validate_client()

    def _on_home(self):
        self._mode = "home"
        self._set_mode_bold(self.btn_home)
        self.email_field.setEnabled(False)
        self.email_field.clear()
        self.tg_icon.setEnabled(True)
        self.chk_share_code.setEnabled(True)
        self._set_start_ready(True)
        self.mode_info.setText(self.tr("Local session — photos saved locally, no upload."))
        self.btn_start.setFocus()

    def _on_private(self):
        self._mode = "private"
        self._set_mode_bold(self.btn_private)
        self.email_field.setEnabled(False)
        self.email_field.clear()
        self.tg_icon.setEnabled(False)
        self.chk_share_code.setChecked(False)
        self.chk_share_code.setEnabled(False)
        self._set_start_ready(True)
        self.mode_info.setText(self.tr("Private session — photos stay on SD card only."))
        self.btn_start.setFocus()

    # ─── walidacja emaila (tylko CLIENT)

    def _on_email_changed(self):
        if self._mode == "client":
            self._validate_client()

    def _validate_client(self):
        email = self.email_field.text().strip().lower()
        if EMAIL_RE.match(email):
            self.mode_info.setText(
                self.tr("Client session — photos will be sent to: %1.").replace("%1", email)
            )
            self._set_start_ready(True)
        elif email:
            self.mode_info.setText(self.tr("Enter a valid email address."))
            self._set_start_ready(False)
        else:
            self.mode_info.setText("")
            self._set_start_ready(False)

    # ─── start

    def _try_start(self):
        if self.btn_start.isEnabled():
            self._on_start()

    def _on_start(self):
        duration = int(self.duration_slider.get_value())
        if self._mode == "private":
            self.start_requested.emit("", duration)
        elif self._mode == "home":
            self.start_requested.emit("home", duration)
        else:
            self.start_requested.emit(self.email_field.text().strip().lower(), duration)

    @property
    def share_code_requested(self) -> bool:
        return self.chk_share_code.isChecked()

    def reset(self):
        """Przywraca formularz do stanu początkowego."""
        self._mode = ""
        self._set_mode_bold(None)
        self.email_field.setEnabled(False)
        self.email_field.clear()
        self.mode_info.setText("")
        self._set_start_ready(False)
        self.tg_icon.setEnabled(True)
        self.chk_share_code.setChecked(False)
        self.chk_share_code.setEnabled(True)


# ─────────────────────────── PANEL AKTYWNEJ SESJI

class ActiveSessionPanel(QWidget):
    """Ekran z tłem podczas trwania/zakończenia sesji."""

    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.set_background(BG_ACTIVE)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Góra: odliczanie + pasek postępu ---
        top = QWidget()
        top.setStyleSheet("background-color: #3d3d3d;")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(40, 20, 40, 12)
        top_layout.setSpacing(12)

        self.countdown_label = QLabel("--:--")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(50)
        font.setBold(True)
        self.countdown_label.setFont(font)
        self.countdown_label.setStyleSheet("color: #e0e0e0; background: transparent;")
        top_layout.addWidget(self.countdown_label)

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
        top_layout.addWidget(self.progress)

        layout.addWidget(top)

        # --- Środek: obrazek z zachowaniem proporcji ---
        # BackgroundWidget rysuje przez paintEvent — nie wpływa na sizeHint okna
        self._img_label = BackgroundWidget(fill_color="#3d3d3d")
        self._img_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._img_label, 1)

        # --- Dół: info + przycisk STOP ---
        bottom = QWidget()
        bottom.setStyleSheet("background-color: #3d3d3d;")
        bot_layout = QVBoxLayout(bottom)
        bot_layout.setContentsMargins(40, 12, 40, 20)
        bot_layout.setSpacing(8)

        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet(
            "color: rgba(255,255,255,180); font-size: 14px; background: transparent;"
        )
        bot_layout.addWidget(self.info_label)

        self.import_label = QLabel("")
        self.import_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_label.setStyleSheet(
            "color: rgba(255,255,255,180); font-size: 13px; background: transparent;"
        )
        self.import_label.hide()
        bot_layout.addWidget(self.import_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_stop = QPushButton(self.tr("■  STOP SESSION"))
        self.btn_stop.setFixedSize(220, 48)
        self.btn_stop.setStyleSheet(BTN_STYLE_RED)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch(1)
        bot_layout.addLayout(btn_row)

        layout.addWidget(bottom)

    def set_background(self, path: str):
        """Ładuje nowe tło."""
        self._img_label.set_background(path)

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

    go_darkroom      = pyqtSignal()
    new_session      = pyqtSignal()
    import_requested = pyqtSignal()   # użytkownik chce importować (INTERRUPTED)
    delete_requested = pyqtSignal()   # użytkownik chce usunąć bez importu (INTERRUPTED)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)

        self.title = _ScalableLabel(self.tr("Session complete"), max_pt=24)
        layout.addWidget(self.title)

        layout.addSpacing(12)

        # Obrazek instrukcji SD card — widoczny tylko dla trybu PRIVATE
        self.sd_card_image = _ScalableImage(max_h=320)
        self.sd_card_image.set_image(os.path.join("assets", "pictures", "remove-sdcard.jpg"))
        self.sd_card_image.hide()
        layout.addWidget(self.sd_card_image)

        layout.addSpacing(8)

        self.details = QLabel("")
        self.details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details.setStyleSheet("color: #aaa; font-size: 13px;")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)

        layout.addSpacing(8)

        # Ramka z przypomnieniem o karcie SD — widoczna tylko dla trybu PRIVATE
        self._sd_reminder_frame = QFrame()
        self._sd_reminder_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._sd_reminder_frame.setStyleSheet(
            "QFrame { border: 2px solid #888; border-radius: 6px; margin: 8px 40px; }"
        )
        _sd_rem_layout = QVBoxLayout(self._sd_reminder_frame)
        _sd_rem_layout.setContentsMargins(16, 12, 16, 12)
        self._sd_reminder_label = QLabel("")
        self._sd_reminder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sd_reminder_label.setStyleSheet("color: #c0c0c0; font-size: 15px; border: none;")
        self._sd_reminder_label.setWordWrap(True)
        _sd_rem_layout.addWidget(self._sd_reminder_label)
        self._sd_reminder_frame.hide()
        layout.addWidget(self._sd_reminder_frame)

        layout.addSpacing(8)

        # Widget QR kodu (domyślnie ukryty)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.hide()
        layout.addWidget(self.qr_label)

        self.code_label = QLabel()
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_code = QFont()
        font_code.setPointSize(16)
        font_code.setBold(True)
        font_code.setFamily("monospace")
        self.code_label.setFont(font_code)
        self.code_label.hide()
        layout.addWidget(self.code_label)

        self.warnings_label = QLabel("")
        self.warnings_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warnings_label.setStyleSheet("color: #e65100; font-size: 12px;")
        self.warnings_label.setWordWrap(True)
        layout.addWidget(self.warnings_label)

        layout.addStretch(1)

        # Przyciski dla sesji przerwanej (CLIENT/HOME) — domyślnie ukryte
        self._interrupted_row = QHBoxLayout()
        self._interrupted_row_widget = QWidget()
        irw = QHBoxLayout(self._interrupted_row_widget)
        irw.setContentsMargins(0, 0, 0, 0)
        irw.setSpacing(12)

        irw.addStretch(1)

        self.btn_import_card = QPushButton(self.tr("⬇  Import photos from card"))
        self.btn_import_card.setFixedHeight(42)
        self.btn_import_card.clicked.connect(self.import_requested.emit)
        irw.addWidget(self.btn_import_card)

        self.btn_delete_card = QPushButton(self.tr("🗑  Delete photos"))
        self.btn_delete_card.setFixedHeight(42)
        self.btn_delete_card.clicked.connect(self.delete_requested.emit)
        irw.addWidget(self.btn_delete_card)

        irw.addStretch(1)

        self._interrupted_row_widget.hide()
        layout.addWidget(self._interrupted_row_widget)

        layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_darkroom = QPushButton(self.tr("→ Darkroom"))
        self.btn_darkroom.setFixedHeight(42)
        self.btn_darkroom.setStyleSheet(
            "QPushButton { font-weight: bold; background-color: #1565c0; color: #e8e8e8; }"
            " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: #1565c0; }"
            " QPushButton:focus:hover { background-color: #1976d2; }"
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
        interrupted = summary.end_reason not in (EndReason.TIMEOUT, EndReason.USB_DETECTED)
        needs_import = ctx.mode in (SessionMode.CLIENT, SessionMode.HOME)

        # Tytuł
        if summary.end_reason == EndReason.TIMEOUT:
            self.title.setText(self.tr("Session finished"))
        elif summary.end_reason == EndReason.USB_DETECTED:
            self.title.setText(self.tr("Session stopped — camera connected"))
        else:
            self.title.setText(self.tr("Session interrupted"))

        # Szczegóły
        if ctx.mode == SessionMode.PRIVATE:
            self.sd_card_image.show()
            self._sd_reminder_frame.show()
            self.details.setText(
                self.tr("Duration: %1").replace("%1", summary.duration_str) + "\n" +
                self.tr("Your photos are on the camera's SD card.")
            )
            self._sd_reminder_label.setText(
                self.tr("Don't forget to disconnect the camera, turn it off and remove the SD card.")
            )
        else:
            self.sd_card_image.hide()
            self._sd_reminder_frame.hide()
            shots_str = str(summary.shot_count) if not interrupted else "—"
            sync_str  = {
                "done":    self.tr("✓ Synced to Google Drive"),
                "pending": self.tr("Sync pending..."),
                "failed":  self.tr("⚠ Sync failed"),
                "skipped": "",
            }.get(ctx.sync_status, "")
            lines = [self.tr("Duration: %1").replace("%1", summary.duration_str)]
            if not interrupted:
                lines.append(self.tr("Shots imported: %1").replace("%1", shots_str))
            if ctx.session_path:
                lines.append(self.tr("Folder: %1").replace("%1", ctx.session_path))
            if sync_str:
                lines.append(sync_str)
            self.details.setText("\n".join(lines))

        if summary.warnings:
            self.warnings_label.setText(self.tr("Warnings: %1").replace("%1", " · ".join(summary.warnings[:3])))
        else:
            self.warnings_label.setText("")

        # Przyciski przerwanej sesji — tylko dla CLIENT/HOME
        self._interrupted_row_widget.setVisible(interrupted and needs_import)

        # Darkroom: niedostępny dla PRIVATE i dla przerwanych (brak importu)
        self.btn_darkroom.setVisible(needs_import and not interrupted)

        # QR kod
        if ctx.share_code:
            self._show_qr(ctx.share_code)
        else:
            self.qr_label.hide()
            self.code_label.hide()

    def _show_qr(self, code: str) -> None:
        """Generuje i wyświetla QR kod z deep linkiem do bota."""
        bot_username = "pryzmat_studio_bot"
        url = f"https://t.me/{bot_username}?start={code}"

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        # Czarno-biały QR
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")

        # Logo w centrum (maks. 28% szerokości — ERROR_CORRECT_H toleruje 30%)
        import io
        from PIL import Image as _PilImage
        logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "assets", "icons", "pryzmat-ico.png")
        if os.path.exists(logo_path):
            logo = _PilImage.open(logo_path).convert("RGBA")
            max_logo = int(qr_img.width * 0.20)
            logo.thumbnail((max_logo, max_logo), _PilImage.LANCZOS)
            # Białe tło z marginesem pod logo
            pad = 12
            bg = _PilImage.new("RGBA", (logo.width + pad * 2, logo.height + pad * 2), (255, 255, 255, 255))
            bg.paste(logo, (pad, pad), logo)
            pos = ((qr_img.width - bg.width) // 2, (qr_img.height - bg.height) // 2)
            qr_img.paste(bg, pos)

        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        pixmap_raw = QPixmap()
        pixmap_raw.loadFromData(buf.getvalue())
        pixmap_scaled = pixmap_raw.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        # Zaokrąglone rogi — maska przez QPainterPath
        from PyQt6.QtGui import QPainterPath
        radius = 16
        pixmap = QPixmap(pixmap_scaled.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(pixmap.rect().toRectF(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap_scaled)
        painter.end()

        self.qr_label.setPixmap(pixmap)
        self.qr_label.show()
        self.code_label.setText(self.tr("Session code: %1").replace("%1", code))
        self.code_label.show()


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
        # Worker ustawień zarządzany przez _settings_panel.activate()/deactivate()
        self._view_active = False     # True gdy session_view jest widoczny
        self._last_bad_state: Optional[str] = None  # 'no_camera' | 'no_sd' | None
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

        # ── Strona 0: wspólny panel ustawień aparatu ──────────────────────
        self._settings_panel = CameraSettingsPanel(session_mode_init=True)
        self._settings_panel.settings_captured.connect(self._on_settings_captured)
        self._settings_panel.status_message.connect(self.status_message)
        self.exposure_ctrl = self._settings_panel.exposure_ctrl
        self.image_ctrl    = self._settings_panel.image_ctrl
        self.focus_ctrl    = self._settings_panel.focus_ctrl

        # Kontener strony 0: panel ustawień + przyciski profili na dole
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(0)
        controls_layout.addWidget(self._settings_panel)

        # Rząd Load/Save — widoczny tylko poza sesją
        self._profiles_row = QWidget()
        row_profiles = QHBoxLayout(self._profiles_row)
        row_profiles.setContentsMargins(6, 4, 6, 4)
        self.btn_save_profile = QPushButton(self.tr("Save"))
        self.btn_load_profile = QPushButton(self.tr("Load"))
        row_profiles.addWidget(self.btn_save_profile)
        row_profiles.addWidget(self.btn_load_profile)
        row_profiles.addStretch()
        self.btn_save_profile.clicked.connect(self._on_save_profile)
        self.btn_load_profile.clicked.connect(self._on_load_profile)
        controls_layout.addWidget(self._profiles_row)

        # Ramka z komunikatem o trybie bezprzewodowym — widoczna tylko podczas sesji
        self._session_msg = QFrame()
        self._session_msg.setFrameShape(QFrame.Shape.StyledPanel)
        self._session_msg.setStyleSheet(
            "QFrame { border: 2px solid #888; border-radius: 6px; margin: 12px; }"
        )
        msg_layout = QVBoxLayout(self._session_msg)
        msg_layout.setContentsMargins(16, 16, 16, 16)
        self._session_msg_label = QLabel(
            self.tr("Camera is in wireless mode.\n\n"
                    "USB communication is disabled\n"
                    "during an active session.\n\n"
                    "Use remote shutter to take photos.")
        )
        self._session_msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_msg_label.setStyleSheet("color: #c0c0c0; font-size: 15px; border: none;")
        self._session_msg_label.setWordWrap(True)
        msg_layout.addWidget(self._session_msg_label)
        self._session_msg.hide()
        controls_layout.addWidget(self._session_msg)

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
        self._active_panel.stop_requested.connect(self._on_stop_requested)
        self._summary_panel.new_session.connect(self._on_new_session)
        self._summary_panel.go_darkroom.connect(self._on_go_darkroom)
        self._summary_panel.import_requested.connect(self._on_import_requested)
        self._summary_panel.delete_requested.connect(self._on_delete_requested)

    # ─────────────────────────── Cykl życia widoku

    def on_enter(self):
        """Wywoływane przez MainWindow przy przejściu do widoku Session."""
        self._view_active = True
        self._last_bad_state = None   # reset — dialogi pokażą się przy pierwszym probe
        # NIE startujemy workera tu — probe (wywoływane po on_enter) wywoła
        # set_camera_ready, które dopiero uruchomi workera po zwolnieniu USB.
        QTimer.singleShot(0, self._config_panel.email_field.setFocus)

    def on_leave(self):
        """Wywoływane przez MainWindow przy opuszczeniu widoku Session."""
        self._view_active = False
        self._settings_panel.deactivate()
        self._stop_usb_polling()

    def _on_settings_captured(self, d: dict):
        """Zapisuje snapshot ustawień aparatu przed startem sesji."""
        self._current_camera_settings = CameraSettings.from_dict(
            {k: v["current"] if isinstance(v, dict) else v for k, v in d.items()}
        )

    def set_camera_ready(self, camera_on: bool, sd_on: bool):
        """Wywoływane z MainWindow — włącza/wyłącza panele w zależności od stanu aparatu/karty."""
        self._camera_on = camera_on
        self._sd_on = sd_on

        self._restore_overlay()  # przywróć overlay po ewentualnej sesji

        if camera_on and sd_on:
            # Aparat i karta SD — oba panele aktywne
            self._last_bad_state = None
            self._start_usb_polling()  # monitoruj odłączenie
            self._left_stack.setCurrentIndex(0)
            self._config_panel.setEnabled(True)
            if self._view_active and not self.is_session_active():
                self._settings_panel.activate()
                # Jawne włączenie kontrolek — Qt propaguje setEnabled przez C++
                # bez wywoływania Python-owych overrides, więc _apply_locks() nie odpala
                self.exposure_ctrl.setEnabled(True)
                self.image_ctrl.setEnabled(True)
                self.focus_ctrl.setEnabled(True)
                if self._stack.currentIndex() == self._PAGE_CONFIG:
                    QTimer.singleShot(0, self._config_panel.email_field.setFocus)

        elif camera_on and not sd_on:
            # Aparat wykryty, brak karty SD — lewy panel aktywny, prawy zablokowany
            self._start_usb_polling()  # monitoruj odłączenie
            self._left_stack.setCurrentIndex(0)
            self._config_panel.setEnabled(False)
            if self._view_active and not self.is_session_active():
                self._settings_panel.activate()
                self.exposure_ctrl.setEnabled(True)
                self.image_ctrl.setEnabled(True)
                self.focus_ctrl.setEnabled(True)
            if self._view_active and self._last_bad_state != "no_sd":
                self._last_bad_state = "no_sd"
                from ui.dialogs.no_sd_card_dialog import NoSdCardDialog
                dlg = NoSdCardDialog(self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    # OK: użytkownik włożył kartę — zlecamy re-probe
                    self.camera_detected.emit()

        else:
            # Brak aparatu — oba panele zablokowane, lewy panel wyszarzony
            self._settings_panel.deactivate()
            self._config_panel.setEnabled(False)
            self._left_stack.setCurrentIndex(0)
            if self._view_active and self._last_bad_state != "no_camera":
                self._last_bad_state = "no_camera"
                from ui.dialogs.no_camera_dialog import NoCameraDialog
                dlg = NoCameraDialog(self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    # Canon wykryty przez dialog — zlecamy re-probe
                    self.camera_detected.emit()
            self._start_usb_polling()

    def _start_usb_polling(self):
        """Startuje polling USB — wykrywa podłączenie aparatu."""
        if self._usb_poll_timer.isActive():
            return
        self._usb_poll_timer.start(2000)

    def _stop_settings_worker(self):
        """Deleguje zatrzymanie workera ustawień do panelu."""
        self._settings_panel._stop_worker()

    def _stop_usb_polling(self):
        """Zatrzymuje polling USB."""
        self._usb_poll_timer.stop()

    def _poll_usb(self):
        """Sprawdza lsusb — wykrywa pojawienie i zniknięcie aparatu."""
        canon_present = _lsusb_has_canon()
        if self._camera_on and not canon_present:
            # Aparat zniknął — zatrzymaj worker (odblokuje probe), zleć probe
            self._settings_panel.deactivate()
            self.camera_detected.emit()
        elif not self._camera_on and canon_present:
            self._stop_usb_polling()
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
        self._stop_usb_polling()   # żaden probe nie może dotknąć USB podczas sesji
        self._settings_panel.deactivate()
        self._profiles_row.hide()
        self._session_msg.show()
        self._left_stack.setCurrentIndex(0)

    def _restore_overlay(self):
        """Przywraca lewy panel do stanu domyślnego po zakończeniu sesji."""
        self._profiles_row.show()
        self._session_msg.hide()

    # ─────────────────────────── START SESJI

    def _on_start_session(self, email: str, duration_min: int):
        """Pokazuje dialog USB → tworzy kontekst i uruchamia SessionRunner."""
        # Ustaw samowyzwalacz 2s — pilot BT działa tylko w tym trybie.
        # Musi być przed deactivate(), bo worker przetwarza kolejkę przy zamknięciu.
        self._settings_panel.set_drivemode("Timer 2 sec")

        # Zatrzymaj worker ustawień i polling USB — zwalnia USB przed dialogiem.
        # KRYTYCZNE: polling NIE może odpalać probe podczas disconnectu w dialogu.
        self._settings_panel.deactivate()
        self._stop_usb_polling()

        # Snapshot plików na karcie PRZED sesją — aparat jeszcze w trybie USB
        pre_session_files = _snapshot_card_files()

        # Dialog OFF→ON: bez USB podczas sesji aparat aktywuje moduł BT
        dlg = UsbDisconnectDialog(self)
        dlg.status_changed.connect(self.status_message)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            # Przywróć worker ustawień — polling nie był aktywny (aparat był podłączony)
            if self._view_active:
                self._settings_panel.activate()
            return

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

        # Tryb kodu: checkbox zaznaczony + brak emaila → wymusz CLIENT (pliki muszą być importowane)
        if self._config_panel.share_code_requested and ctx.mode == SessionMode.PRIVATE:
            ctx.mode = SessionMode.CLIENT
            ctx.session_path  = os.path.join(base_dir, ctx.session_id)
            ctx.captures_path = ctx.session_path

        # Generuj kod udostępniania jeśli zaznaczono checkbox
        if self._config_panel.share_code_requested:
            code = session_codes.generate_code()
            ctx.share_code = code

        store = SessionStore(base_dir)

        self._runner = SessionRunner(ctx, store, rclone_rem, rclone_dst, pre_session_files)

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
        self._active_panel.btn_stop.show()
        self._active_panel.import_label.hide()
        self._active_panel.countdown_label.setText(
            f"{duration_min:02d}:00"
        )
        self._active_panel.progress.setValue(100)
        self._stack.setCurrentIndex(self._PAGE_ACTIVE)
        QTimer.singleShot(0, self._active_panel.btn_stop.setFocus)

        contact = ctx.email
        mode_msg = {
            "client":  f"Client session · {contact} · {duration_min} min",
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

        # Zarejestruj kod sesji jeśli istnieje
        if summary.context.share_code and summary.context.session_path:
            session_codes.register(
                summary.context.share_code,
                summary.context.session_path,
            )

        self._left_panel.hide()
        self._stack.setCurrentIndex(self._PAGE_SUMMARY)
        self.session_finished.emit(summary)

        needs_import = summary.context.mode in (SessionMode.CLIENT, SessionMode.HOME)
        interrupted  = summary.end_reason not in (EndReason.TIMEOUT, EndReason.USB_DETECTED)

        if needs_import and not interrupted:
            # TIMEOUT + CLIENT/HOME: autoimport już zrobiony — zapytaj o usunięcie z karty
            self._ask_delete_from_card()
        elif not (interrupted and needs_import):
            # PRIVATE lub INTERRUPTED bez potrzeby importu — wyczyść runner
            if self._runner:
                self._runner.deleteLater()
                self._runner = None
        # else: INTERRUPTED + CLIENT/HOME — runner żyje, obsługują go przyciski SummaryPanel

        # Aparat jest teraz bezprzewodowy (USB odłączone) — czekaj na podłączenie
        self._camera_on = False
        self._sd_on = False
        self._start_usb_polling()

    def _on_import_requested(self):
        """Użytkownik kliknął 'Import photos from card' w SummaryPanel (sesja przerwana)."""
        if not self._runner:
            return
        self._summary_panel.btn_import_card.setEnabled(False)
        self._summary_panel.btn_delete_card.setEnabled(False)
        self._summary_panel.btn_import_card.setText(self.tr("Importing..."))
        # Połącz sygnały importu do panelu aktywnego i słuchaj zakończenia
        self._runner.import_progress.connect(self._active_panel.show_import_progress)
        self._runner.session_finished.connect(self._on_deferred_import_finished)
        self._runner.start_import_only()

    def _on_deferred_import_finished(self, summary: SessionSummary):
        """Import na żądanie zakończony — aktualizuj SummaryPanel i zapytaj o usunięcie."""
        self._summary_panel.populate(summary)
        self._summary_panel._interrupted_row_widget.hide()
        self._summary_panel.btn_darkroom.setVisible(True)
        if self._runner:
            self._runner.deleteLater()
            self._runner = None
        self._ask_delete_from_card()

    def _on_delete_requested(self):
        """Użytkownik kliknął 'Delete photos' w SummaryPanel — usuń bez importu."""
        from PyQt6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self,
            self.tr("Delete photos?"),
            self.tr("Delete all photos from this session from the camera's SD card?\n"
                    "This cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        if self._runner:
            self._summary_panel.btn_delete_card.setEnabled(False)
            self._summary_panel.btn_delete_card.setText(self.tr("Deleting..."))
            self._runner.session_finished.connect(self._on_delete_finished)
            self._runner.start_delete_from_card()

    def _on_delete_finished(self, _summary):
        """Usuwanie zakończone — zamknij runner."""
        self._summary_panel.btn_import_card.hide()
        self._summary_panel.btn_delete_card.hide()
        if self._runner:
            self._runner.deleteLater()
            self._runner = None

    def _ask_delete_from_card(self):
        """Po imporcie (CLIENT/HOME) — pytanie o usunięcie z karty SD."""
        if not self._runner:
            return
        from PyQt6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self,
            self.tr("Delete from SD card?"),
            self.tr("Photos imported successfully.\n"
                    "Delete imported photos from the camera's SD card?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._runner.session_finished.connect(self._on_delete_finished)
            self._runner.start_delete_from_card()
        else:
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
        self._left_panel.show()
        self._config_panel.reset()
        self._stack.setCurrentIndex(self._PAGE_CONFIG)
        QTimer.singleShot(0, self._config_panel.email_field.setFocus)
        # Przywróć stan panelu kamery (probe zadecyduje czy aktywny czy nie)
        self.set_camera_ready(self._camera_on, self._sd_on)

    def _on_go_darkroom(self):
        """Sygnalizuje MainWindow żeby przełączył na Darkroom."""
        # MainWindow podłącza session_finished i sam nawiguje
        pass

    def is_session_active(self) -> bool:
        """Zwraca True gdy sesja trwa (USB odłączone, aparat bezprzewodowy)."""
        return self._runner is not None and self._runner.isRunning()

    def is_settings_active(self) -> bool:
        """Zwraca True gdy worker ustawień trzyma USB (analogicznie do is_lv_active w CameraView).
        Probe powinien być pomijany gdy worker aktywny — nie przerywaj konfiguracji."""
        w = self._settings_panel.worker
        return w is not None and w.isRunning()

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
            self._config_panel.duration_slider.set_value(str(dur))

    # ─────────────────────────── Profile aparatu

    def _profiles_dir(self) -> str:
        """Zwraca ścieżkę do katalogu camera_profiles/ — wspólny z CameraView."""
        project_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(project_dir))
        d = os.path.join(project_root, "camera_profiles")
        os.makedirs(d, exist_ok=True)
        return d

    def _collect_current_settings(self) -> dict:
        """Zbiera aktualne ustawienia ze wszystkich kontrolek."""
        s = {}
        s.update(self.exposure_ctrl.get_settings())
        s.update(self.image_ctrl.get_settings())
        s.update(self.focus_ctrl.get_settings())
        return s

    def _on_save_profile(self):
        """Zapisuje bieżące ustawienia aparatu do pliku JSON."""
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        import json

        name, ok = QInputDialog.getText(self, self.tr("Save Camera Profile"), self.tr("Profile name:"))
        if not ok or not name.strip():
            return
        name = name.strip()
        safe = "".join(c for c in name if c.isalnum() or c in " _-()").strip()
        if not safe:
            QMessageBox.warning(self, self.tr("Save Profile"), self.tr("Invalid profile name."))
            return
        path = os.path.join(self._profiles_dir(), f"{safe}.json")
        if os.path.exists(path):
            ans = QMessageBox.question(
                self, self.tr("Overwrite?"),
                self.tr("Profile '%1' already exists. Overwrite?").replace("%1", safe),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        settings = self._collect_current_settings()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"name": safe, "settings": settings}, f, indent=2)
            self.status_message.emit(f"Profile saved: {safe}", 3000)
        except Exception as e:
            QMessageBox.warning(self, self.tr("Save Profile"),
                                self.tr("Error saving profile:\n%1").replace("%1", str(e)))

    def _on_load_profile(self):
        """Otwiera przeglądarkę profili."""
        dialog = ProfileBrowserDialog(self._profiles_dir(), parent=self)
        dialog.profile_selected.connect(self._apply_profile)
        dialog.exec()

    def _apply_profile(self, settings: dict):
        """Aplikuje ustawienia z profilu do UI i aparatu (przez settings worker)."""
        worker = self._settings_panel.worker

        # Exposure
        for key in ('shutterspeed', 'aperture', 'iso', 'exposurecompensation'):
            if key in settings:
                ctrl = self.exposure_ctrl.controls.get(key)
                if ctrl and ctrl["slider"]:
                    ctrl["slider"].set_value(str(settings[key]))
                    if ctrl["auto"]:
                        self.exposure_ctrl._update_auto_visuals(key, settings[key] == "Auto")
                if worker:
                    worker.update_camera_param(key, str(settings[key]))

        # Image
        img_keys = ('picturestyle', 'imageformat', 'alomode', 'whitebalance', 'colortemperature')
        af_keys  = ('focusmode', 'afmethod', 'continuousaf')
        img_s = {k: v for k, v in settings.items() if k in img_keys}
        af_s  = {k: v for k, v in settings.items() if k in af_keys}
        if img_s:
            pseudo = {k: {"current": v, "choices": []} for k, v in img_s.items()}
            if 'colortemperature' in img_s:
                self.image_ctrl.ct_slider.set_value(str(img_s['colortemperature']))
                pseudo.pop('colortemperature', None)
            for param, val in pseudo.items():
                combo = self.image_ctrl._get_combo(param)
                if combo:
                    display = self.image_ctrl._to_display(param, str(val['current']))
                    combo.blockSignals(True)
                    combo.setCurrentText(display)
                    combo.blockSignals(False)
            if worker:
                for k, v in img_s.items():
                    worker.update_camera_param(k, str(v))

        if af_s:
            for param, val in af_s.items():
                combo = self.focus_ctrl._get_combo(param)
                if combo:
                    display = self.focus_ctrl._to_display(param, str(val))
                    combo.blockSignals(True)
                    combo.setCurrentText(display)
                    combo.blockSignals(False)
            if worker:
                for k, v in af_s.items():
                    worker.update_camera_param(k, str(v))

        self.status_message.emit("Profile loaded")
