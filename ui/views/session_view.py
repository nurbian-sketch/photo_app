"""
Widok sesji fotograficznej.
Lewy panel: ustawienia aparatu.
Prawy panel: formularz konfiguracji sesji.
Aktywna sesja i podsumowanie wyświetlane są jako osobne dialogi.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QSettings, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QTransform, QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QGroupBox, QFrame, QDialog, QSplitter,
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
from ui.styles import (
    BTN_STYLE_RED,
    CONFIG_MODE_INFO_STYLE,
    OVERLAY_LABEL_STYLE,
    SESSION_WIRELESS_FRAME_STYLE,
    SESSION_WIRELESS_MSG_STYLE,
    SESSION_PANEL_BG,
)
from ui.dialogs.profile_browser_dialog import ProfileBrowserDialog
from ui.dialogs.usb_disconnect_dialog import UsbDisconnectDialog, _lsusb_has_canon
from ui.widgets.slider_with_scale import SliderWithScale

import core.session_codes as session_codes
from ui.dialogs.preferences_dialog import PreferencesDialog

# ─────────────────────────── STAŁE

DURATION_VALUES = [1, 3, 5, 10, 15, 30, 45, 60, 90]  # minuty
DURATION_TEST_LABEL = "5 sec"  # opcja testowa — 5 sekund zamiast minut

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


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


# ─────────────────────────── PANEL KONFIGURACJI

class ConfigPanel(QWidget):
    """Formularz przed startem sesji."""

    start_requested = pyqtSignal(str, int)    # email (""|"home"|adres), duration_min

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = ""   # "cloud" | "home" | "private" | ""
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.addStretch(1)

        prepare_lbl = QLabel(self.tr("Prepare session..."))
        prepare_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = prepare_lbl.font(); f.setPointSize(18); f.setBold(True)
        prepare_lbl.setFont(f)
        outer.addWidget(prepare_lbl)

        outer.addSpacing(24)

        group = QGroupBox(self.tr("New Session"))
        group.setMaximumWidth(520)
        inner = QVBoxLayout(group)
        inner.setSpacing(16)

        # Przyciski wyboru trybu — CLOUD | HOME | PRIVATE
        mode_row = QHBoxLayout()
        self.btn_cloud   = QPushButton(self.tr("CLOUD"))
        self.btn_home    = QPushButton(self.tr("HOME"))
        self.btn_private = QPushButton(self.tr("PRIVATE"))
        for b in (self.btn_cloud, self.btn_home, self.btn_private):
            b.setFixedHeight(38)
            mode_row.addWidget(b)
        mode_row.addStretch(1)
        self.btn_cloud.clicked.connect(self._on_cloud)
        self.btn_home.clicked.connect(self._on_home)
        self.btn_private.clicked.connect(self._on_private)
        inner.addLayout(mode_row)

        # Email — aktywny tylko w trybie CLOUD
        email_lbl = QLabel(self.tr("Email"))
        email_lbl.setStyleSheet("font-weight: 600;")
        inner.addWidget(email_lbl)

        self.email_field = QLineEdit()
        self.email_field.setPlaceholderText(self.tr("client@example.com"))
        self.email_field.setFixedHeight(36)
        self.email_field.setEnabled(False)
        self.email_field.textChanged.connect(self._on_email_changed)
        self.email_field.returnPressed.connect(self._try_start)
        inner.addWidget(self.email_field)

        # Info trybu
        self.mode_info = QLabel("")
        self.mode_info.setStyleSheet(CONFIG_MODE_INFO_STYLE)
        self.mode_info.setWordWrap(True)
        inner.addWidget(self.mode_info)

        inner.addSpacing(8)

        # Suwak czasu
        self.duration_slider = SliderWithScale(
            self.tr("Duration (min)"), [DURATION_TEST_LABEL] + [str(v) for v in DURATION_VALUES]
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
        for b in (self.btn_cloud, self.btn_home, self.btn_private):
            f = b.font(); f.setBold(b is active_btn); b.setFont(f)

    def _set_start_ready(self, enabled: bool):
        self.btn_start.setEnabled(enabled)
        self.btn_start.setDefault(enabled)

    # ─── wybór trybu

    def _on_cloud(self):
        self._mode = "cloud"
        self._set_mode_bold(self.btn_cloud)
        self.email_field.setEnabled(True)
        self.email_field.setFocus()
        self._validate_cloud()

    def _on_home(self):
        self._mode = "home"
        self._set_mode_bold(self.btn_home)
        self.email_field.setEnabled(False)
        self.email_field.clear()
        self._set_start_ready(True)
        self.mode_info.setText(
            self.tr("Home session — photos saved locally.")
        )
        self.btn_start.setFocus()

    def _on_private(self):
        self._mode = "private"
        self._set_mode_bold(self.btn_private)
        self.email_field.setEnabled(False)
        self.email_field.clear()
        self._set_start_ready(True)
        self.mode_info.setText(self.tr("Private session — photos stay on SD card only."))
        self.btn_start.setFocus()

    # ─── walidacja emaila (tylko CLOUD)

    def _on_email_changed(self):
        if self._mode == "cloud":
            self._validate_cloud()

    def _validate_cloud(self):
        email = self.email_field.text().strip().lower()
        if EMAIL_RE.match(email):
            self.mode_info.setText(
                self.tr("Cloud session — photos will be sent to: %1.").replace("%1", email)
            )
            self._set_start_ready(True)
        elif email:
            self.mode_info.setText(self.tr("Enter a valid email address."))
            self._set_start_ready(False)
        else:
            self.mode_info.setText(
                self.tr("Cloud session — photos uploaded to remote server. Enter client email.")
            )
            self._set_start_ready(False)

    # ─── start

    def _try_start(self):
        if self.btn_start.isEnabled():
            self._on_start()

    def _on_start(self):
        raw = self.duration_slider.get_value()
        duration = 1 if raw == DURATION_TEST_LABEL else int(raw)
        if self._mode == "private":
            self.start_requested.emit("", duration)
        elif self._mode == "home":
            self.start_requested.emit("home", duration)
        else:  # cloud
            self.start_requested.emit(self.email_field.text().strip().lower(), duration)

    def reset(self):
        """Przywraca formularz do stanu początkowego."""
        self._mode = ""
        self._set_mode_bold(None)
        self.email_field.setEnabled(False)
        self.email_field.clear()
        self.mode_info.setText(self.tr("Select a session mode to continue."))
        self._set_start_ready(False)


# ─────────────────────────── GŁÓWNY WIDOK

class SessionView(QWidget):
    """
    Główny widok sesji fotograficznej.
    Sygnały wychodzące do MainWindow:
      session_finished(summary) — do auto-load w darkroom
      status_message(str)       — do paska stanu
    """

    session_finished    = pyqtSignal(object)   # SessionSummary
    status_message      = pyqtSignal(str)
    camera_detected     = pyqtSignal()         # aparat wykryty przez polling — zleca probe
    developer_requested = pyqtSignal(str)      # session_path — przekazuje żądanie do MainWindow

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
        self._session_running = False  # True gdy sesja aktywna (exec() w toku)
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

        # QStackedWidget: 0 = kontrolki, 1 = overlay (brak aparatu / tryb wireless)
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
        self.btn_save_profile.setMinimumHeight(28)
        self.btn_load_profile.setMinimumHeight(28)
        row_profiles.addWidget(self.btn_save_profile)
        row_profiles.addWidget(self.btn_load_profile)
        row_profiles.addStretch()
        self.btn_save_profile.clicked.connect(self._on_save_profile)
        self.btn_load_profile.clicked.connect(self._on_load_profile)
        controls_layout.addWidget(self._profiles_row)

        # Ramka z komunikatem o trybie bezprzewodowym — widoczna tylko podczas sesji
        self._session_msg = QFrame()
        self._session_msg.setFrameShape(QFrame.Shape.StyledPanel)
        self._session_msg.setStyleSheet(SESSION_WIRELESS_FRAME_STYLE)
        msg_layout = QVBoxLayout(self._session_msg)
        msg_layout.setContentsMargins(16, 16, 16, 16)
        self._session_msg_label = QLabel(
            self.tr("Camera is in wireless mode.\n\n"
                    "USB communication is disabled\n"
                    "during an active session.\n\n"
                    "Use remote shutter to take photos.")
        )
        self._session_msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_msg_label.setStyleSheet(SESSION_WIRELESS_MSG_STYLE)
        self._session_msg_label.setWordWrap(True)
        msg_layout.addWidget(self._session_msg_label)
        self._session_msg.hide()
        controls_layout.addWidget(self._session_msg)

        # ── Strona 1: overlay (brak aparatu) ─────────────────────────────
        no_camera_widget = QWidget()
        no_camera_widget.setStyleSheet(f"background: {SESSION_PANEL_BG};")
        no_cam_layout = QVBoxLayout(no_camera_widget)
        no_cam_layout.setContentsMargins(0, 0, 0, 0)
        no_cam_layout.setSpacing(0)

        self._no_camera_img = QLabel()
        self._no_camera_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_camera_img.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        img_path = os.path.join(
            "assets", "pictures", "korpus-canon-eos-rp-not-presented-full.jpg"
        )
        self._no_camera_pixmap         = QPixmap(img_path) if os.path.exists(img_path) else QPixmap()
        self._no_camera_pixmap_default = self._no_camera_pixmap

        session_img_path = os.path.join("assets", "pictures", "session-start.jpg")
        if os.path.exists(session_img_path):
            _raw = QPixmap(session_img_path)
            _t = QTransform().rotate(-90)
            self._session_pixmap = _raw.transformed(_t, Qt.TransformationMode.SmoothTransformation)
        else:
            self._session_pixmap = QPixmap()
        no_cam_layout.addWidget(self._no_camera_img, 1)

        self._overlay_label = QLabel(
            self.tr("Insert SD card, then connect camera via USB.\n"
                    "Make sure the camera is turned on.")
        )
        self._overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay_label.setStyleSheet(OVERLAY_LABEL_STYLE)
        self._overlay_label.setWordWrap(True)
        no_cam_layout.addWidget(self._overlay_label, 0)

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

        # ── PRAWY PANEL: konfiguracja sesji ──────────────────────────────
        right_panel = QWidget()
        right_panel.setMinimumWidth(300)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._config_panel = ConfigPanel()
        right_layout.addWidget(self._config_panel)

        # Splitter: lewy = ustawienia, prawy = sesja
        self._splitter.addWidget(self._left_panel)
        self._splitter.addWidget(right_panel)
        self._splitter.setStretchFactor(0, 4)
        self._splitter.setStretchFactor(1, 6)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)

        main_layout.addWidget(self._splitter)

        # Sygnały panelu konfiguracji
        self._config_panel.start_requested.connect(self._on_start_session)

    # ─────────────────────────── Cykl życia widoku

    def on_enter(self):
        """Wywoływane przez MainWindow przy przejściu do widoku Session."""
        self._view_active = True
        self._last_bad_state = None
        self._config_panel.reset()
        QTimer.singleShot(0, self._config_panel.btn_cloud.setFocus)

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

        self._restore_overlay()

        if camera_on and sd_on:
            self._last_bad_state = None
            self._start_usb_polling()
            self._left_stack.setCurrentIndex(0)
            self._config_panel.setEnabled(True)
            if self._view_active and not self._session_running:
                self._settings_panel.activate()
                self.exposure_ctrl.setEnabled(True)
                self.image_ctrl.setEnabled(True)
                self.focus_ctrl.setEnabled(True)
                QTimer.singleShot(0, self._config_panel.btn_cloud.setFocus)

        elif camera_on and not sd_on:
            self._start_usb_polling()
            self._left_stack.setCurrentIndex(0)
            self._config_panel.setEnabled(False)
            if self._view_active and not self._session_running:
                self._settings_panel.activate()
                self.exposure_ctrl.setEnabled(True)
                self.image_ctrl.setEnabled(True)
                self.focus_ctrl.setEnabled(True)
            if self._view_active and self._last_bad_state != "no_sd":
                self._last_bad_state = "no_sd"
                from ui.dialogs.no_sd_card_dialog import NoSdCardDialog
                dlg = NoSdCardDialog(self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self.camera_detected.emit()

        else:
            self._settings_panel.deactivate()
            self._config_panel.setEnabled(False)
            self._left_stack.setCurrentIndex(0)
            if self._view_active and self._last_bad_state != "no_camera":
                self._last_bad_state = "no_camera"
                from ui.dialogs.no_camera_dialog import NoCameraDialog
                dlg = NoCameraDialog(self)
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self.camera_detected.emit()
            self._start_usb_polling()

    def _start_usb_polling(self):
        if self._usb_poll_timer.isActive():
            return
        self._usb_poll_timer.start(2000)

    def _stop_settings_worker(self):
        self._settings_panel._stop_worker()

    def _stop_usb_polling(self):
        self._usb_poll_timer.stop()

    def _poll_usb(self):
        canon_present = _lsusb_has_canon()
        if self._camera_on and not canon_present:
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
        self._stop_usb_polling()
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
        """Pokazuje dialog USB → uruchamia sesję → otwiera dialogi aktywnej sesji i podsumowania."""
        # Ustaw samowyzwalacz 2s — pilot BT działa tylko w tym trybie
        self._settings_panel.set_drivemode("Timer 2 sec")

        # Zatrzymaj worker ustawień i polling USB
        self._settings_panel.deactivate()
        self._stop_usb_polling()

        # Snapshot nazw plików na karcie SD przed sesją — filtrowanie importu
        # Canon EOS RP zwraca mtime=0, więc filtrujemy po nazwie pliku, nie czasie
        pre_session_files = _snapshot_card_files()

        # Zapamiętaj czas startu przed dialogiem — bez kontaktu z aparatem
        session_start_time = datetime.now()

        # Dialog OFF→ON: bez USB aparat aktywuje moduł BT
        dlg = UsbDisconnectDialog(self)
        dlg.status_changed.connect(self.status_message)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            if self._view_active:
                self._settings_panel.activate()
            return

        # Natychmiast blokuj komunikację z aparatem
        self._lock_camera_panel()

        from PyQt6.QtCore import QSettings as _QS
        settings = _QS("Grzeza", "SessionsAssistant")
        base_dir   = settings.value("session/directory",
                                    os.path.expanduser("~/Obrazy/sessions"))
        captures   = settings.value("session/captures_subdir", "captures")
        rclone_rem = settings.value("rclone/remote", "")
        rclone_dst = settings.value("rclone/destination", "Sessions")

        cam_settings = self._current_camera_settings or CameraSettings()
        ctx = make_session_context(email, duration_min, base_dir, captures, cam_settings)
        # Tryb testowy: 5 sec zamiast duration_min minut
        if self._config_panel.duration_slider.get_value() == DURATION_TEST_LABEL:
            ctx.duration_sec_override = 5

        # Kod sesji i ścieżka generowane przez runner.finalize() po zakończeniu

        store = SessionStore(base_dir)
        self._runner = SessionRunner(ctx, store, rclone_rem, rclone_dst,
                                     pre_session_files=pre_session_files,
                                     session_start_time=session_start_time)
        self._runner.warning.connect(lambda m: self.status_message.emit(f"⚠ {m}"))
        self._runner.error.connect(lambda m: self.status_message.emit(f"✖ {m}"))
        self._runner.state_changed.connect(self._on_state_changed)
        self._runner.sync_progress.connect(self._on_sync_progress)
        self._runner.developer_requested.connect(self.developer_requested)

        self._runner.start()
        self._save_state(duration_min)

        contact = ctx.email
        mode_msg = {
            "cloud":   f"Cloud session · {contact} · {duration_min} min",
            "home":    f"Home session · {duration_min} min",
            "private": f"Private session · {duration_min} min",
        }.get(ctx.mode.value, "")
        self.status_message.emit(mode_msg)

        # Otwórz dialog aktywnej sesji (exec() = zagnieżdżona pętla zdarzeń)
        from ui.dialogs.session_active_dialog import SessionActiveDialog
        self._session_running = True
        active_dlg = SessionActiveDialog(ctx, parent=self)
        active_dlg.connect_runner(self._runner)
        active_dlg.btn_stop.clicked.connect(self._runner.request_stop)
        active_dlg.exec()
        self._session_running = False

        summary = active_dlg.get_summary()
        if summary is None:
            # Edge case — runner nie skończył (błąd)
            if self._runner:
                self._runner.deleteLater()
                self._runner = None
            return

        # Zarejestruj kod sesji jeśli istnieje
        if summary.context.share_code and summary.context.session_path:
            session_codes.register(
                summary.context.share_code,
                summary.context.session_path,
            )

        # Przywróć lewy panel — aparat był i jest podłączony przez USB (sesja BT, nie USB-disconnect).
        # Re-probe zamiast ręcznego ustawiania False — main_window ustawi prawidłowy stan.
        self._left_panel.show()
        self._camera_on = False
        self._sd_on = False
        self._last_bad_state = "no_camera"   # blokuje NoCameraDialog zanim probe wróci
        self.camera_detected.emit()          # wywołuje _probe_camera w main_window

        # Wyemituj session_finished (MainWindow auto-load w darkroom)
        self.session_finished.emit(summary)

        if summary.context.mode == SessionMode.PRIVATE:
            # Brak podsumowania — zdjęcia zostają na karcie SD, brak importu/kodu
            if self._runner:
                self._runner.deleteLater()
                self._runner = None
            self._on_new_session()
            return

        # Otwórz dialog podsumowania (CLIENT/HOME)
        from ui.dialogs.session_summary_dialog import (
            SessionSummaryDialog, ACTION_DARKROOM, ACTION_NEW_SESSION,
        )
        summary_dlg = SessionSummaryDialog(summary, parent=self)
        result = summary_dlg.exec()

        # Zaktualizuj summary po ewentualnym imporcie
        final = summary_dlg.get_final_summary()
        if final and final is not summary:
            self.session_finished.emit(final)

        # Posprzątaj runner
        if self._runner:
            self._runner.deleteLater()
            self._runner = None

        # Nawigacja
        if result == ACTION_DARKROOM:
            pass  # MainWindow obsługuje nawigację przez session_finished
        else:
            self._on_new_session()

    # ─────────────────────────── SYGNAŁY RUNNERA (status bar)

    def _on_state_changed(self, state: SessionState):
        msgs = {
            SessionState.COUNTDOWN:  "Preparing session...",
            SessionState.ACTIVE:     "Session active",
            SessionState.STOPPING:   "Stopping session...",
            SessionState.IMPORTING:  "Importing photos...",
            SessionState.SYNCING:    "Syncing to Google Drive...",
            SessionState.FINISHED:   "Session finished",
            SessionState.INTERRUPTED: "Session interrupted",
            SessionState.FAILED:     "Session failed",
        }
        if state in msgs:
            self.status_message.emit(msgs[state])

    def _on_sync_progress(self, line: str):
        self.status_message.emit(f"Sync: {line}")

    # ─────────────────────────── NAWIGACJA

    def _on_new_session(self):
        self._left_panel.show()
        self._config_panel.reset()
        QTimer.singleShot(0, self._config_panel.btn_cloud.setFocus)
        self.set_camera_ready(self._camera_on, self._sd_on)

    def is_session_active(self) -> bool:
        """Zwraca True gdy sesja trwa (USB odłączone, aparat bezprzewodowy)."""
        return self._session_running

    def is_settings_active(self) -> bool:
        """Zwraca True gdy worker ustawień trzyma USB."""
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
        project_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(project_dir))
        d = os.path.join(project_root, "camera_profiles")
        os.makedirs(d, exist_ok=True)
        return d

    def _collect_current_settings(self) -> dict:
        s = {}
        s.update(self.exposure_ctrl.get_settings())
        s.update(self.image_ctrl.get_settings())
        s.update(self.focus_ctrl.get_settings())
        return s

    def _on_save_profile(self):
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
            self.status_message.emit(f"Profile saved: {safe}")
        except Exception as e:
            QMessageBox.warning(self, self.tr("Save Profile"),
                                self.tr("Error saving profile:\n%1").replace("%1", str(e)))

    def _on_load_profile(self):
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
