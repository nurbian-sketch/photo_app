import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QPixmap, QTransform

from core.gphoto_interface import GPhotoInterface

from ui.widgets.camera_settings_panel import CameraSettingsPanel
from ui.dialogs.profile_browser_dialog import ProfileBrowserDialog
from ui.widgets.photo_preview_dialog import PhotoPreviewDialog
from ui.styles import BTN_STYLE_RED


# ─────────────────────────────── Widok kamery

class CameraView(QWidget):

    # Emitowany gdy lista otwartych podglądów się zmienia (open/close)
    preview_list_changed = pyqtSignal(list)  # lista (title, dialog) par
    # Komunikaty do status bar main window
    status_message = pyqtSignal(str, int)  # tekst, timeout_ms (0=permanentny)
    # Emitowany gdy USB zostaje zwolnione po zatrzymaniu LV (do triggera probe w innych widokach)
    camera_released = pyqtSignal()

    # Klucz QSettings — taki sam jak w PreferencesDialog
    KEY_SESSION_DIR = "session/directory"

    # Domyślny katalog na sesje
    DEFAULT_SESSION_DIR = os.path.expanduser("~/Obrazy/sessions")
    DEFAULT_CAPTURE_SUBDIR = "captures"  # zdjęcia trafiają do sessions/captures/
    DEFAULT_PROFILES_SUBDIR = "camera_profiles"

    def __init__(self, camera_service=None):
        super().__init__()
        self.cs = camera_service
        self.lv_thread = None
        self._dead_thread = None    # Wątek po _on_lv_error — USB nadal zajęte do czasu finish
        self._camera_ready = False
        self._error_stopped = False   # Flaga: wątek zatrzymany przez błąd (nie przez user)
        self._stopping = False    # Wątek w trakcie zatrzymywania
        self._capture_blocked = False  # Capture zablokowany po błędzie — odblokuj na klatce
        self._capture_secs = 0         # Licznik sekund oczekiwania na capture
        self._capture_timer = QTimer()
        self._capture_timer.setInterval(1000)
        self._capture_timer.timeout.connect(self._on_capture_tick)
        self._settings = QSettings("Grzeza", "SessionsAssistant")
        self._capture_dir = self._get_capture_directory()
        self._preview_dialogs = []  # Referencje do otwartych podglądów
        self._lv_rotation = 0       # Rotacja live view: 0, 90, 180, 270
        # Worker ustawień zarządzany przez _settings_panel.activate()/deactivate()
        self._view_active = False     # True gdy camera_view jest widoczny
        self._init_ui()

    def _get_capture_directory(self) -> str:
        """Pobiera katalog sesji z QSettings. Zdjęcia trafiają do sessions/captures/."""
        saved = self._settings.value(self.KEY_SESSION_DIR, "")

        # Migracja: stara domyślna ścieżka → nowa
        if not saved or "Pictures/sessions" in saved or "Pictures/SessionsAssistant" in saved:
            self._settings.setValue(self.KEY_SESSION_DIR, self.DEFAULT_SESSION_DIR)
            base = self.DEFAULT_SESSION_DIR
        else:
            base = saved

        # Zawsze zapisuj do podkatalogu captures/
        return os.path.join(base, self.DEFAULT_CAPTURE_SUBDIR)

    def update_capture_directory(self):
        """Odświeża katalog sesji z QSettings (po zmianie w Preferences)."""
        self._capture_dir = self._get_capture_directory()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # --- SPLITTER ---
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(12)

        # ---- LEFT: Panel sterowania (wspólny widget) ----
        control_panel = QWidget()
        control_panel.setMinimumWidth(760)
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(0)

        self._settings_panel = CameraSettingsPanel()
        self.exposure_ctrl = self._settings_panel.exposure_ctrl
        self.image_ctrl    = self._settings_panel.image_ctrl
        self.focus_ctrl    = self._settings_panel.focus_ctrl
        self.exposure_ctrl.setEnabled(False)
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl.setEnabled(False)
        control_layout.addWidget(self._settings_panel)

        # Przyciski profili (camera_view-specific)
        row1 = QHBoxLayout()
        self.btn_save = QPushButton(self.tr("Save"))
        self.btn_load = QPushButton(self.tr("Load"))
        row1.addWidget(self.btn_save)
        row1.addWidget(self.btn_load)
        row1.addStretch()
        control_layout.addLayout(row1)

        # ---- RIGHT: Live View ----
        preview_panel = QWidget()
        preview_panel.setMinimumWidth(400)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        self.lv_screen = QLabel(self.tr("LIVE VIEW OFF"))
        self.lv_screen.setStyleSheet(
            "background: #3d3d3d; border: 2px solid #555; color: white;"
        )
        self.lv_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lv_screen.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        preview_layout.addWidget(self.lv_screen)

        row3 = QHBoxLayout()
        row3.setContentsMargins(0, 5, 0, 0)
        self.btn_lv = QPushButton(self.tr("START LIVE VIEW"))
        self.btn_cap = QPushButton(self.tr("CAPTURE PHOTO"))
        self.btn_lv.setFixedSize(200, 40)
        self.btn_cap.setFixedSize(180, 40)
        self.btn_lv.setStyleSheet(self.BTN_STYLE_NORMAL)
        self.btn_cap.setStyleSheet(
            "QPushButton { font-weight: bold; }"
            " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: palette(button); }"
            " QPushButton:focus:hover { background-color: palette(midlight); }"
        )

        self.btn_lv_rotate_left = QPushButton("↶ 90°")
        self.btn_lv_rotate_left.setFixedSize(65, 40)
        self.btn_lv_rotate_left.setToolTip(self.tr("Rotate live view 90° CCW"))
        self.btn_lv_rotate_left.setEnabled(False)

        self.btn_lv_rotate_right = QPushButton("↷ 90°")
        self.btn_lv_rotate_right.setFixedSize(65, 40)
        self.btn_lv_rotate_right.setToolTip(self.tr("Rotate live view 90° CW"))
        self.btn_lv_rotate_right.setEnabled(False)

        row3.addStretch()
        row3.addWidget(self.btn_lv_rotate_left)
        row3.addWidget(self.btn_lv_rotate_right)
        row3.addWidget(self.btn_lv)
        row3.addWidget(self.btn_cap)
        row3.addStretch()
        preview_layout.addLayout(row3)

        # Splitter
        self.main_splitter.addWidget(control_panel)
        self.main_splitter.addWidget(preview_panel)
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 6)
        main_layout.addWidget(self.main_splitter)

        # --- SYGNAŁY ---
        self.btn_lv.clicked.connect(self._toggle_liveview)
        self.btn_cap.clicked.connect(self._on_capture_clicked)
        self.btn_lv_rotate_left.clicked.connect(self._rotate_lv_ccw)
        self.btn_lv_rotate_right.clicked.connect(self._rotate_lv_cw)
        self.btn_save.clicked.connect(self._on_save_profile)
        self.btn_load.clicked.connect(self._on_load_profile)

        self._set_buttons_enabled(False)

    # ─────────────────────────────── Live view — rotacja i klatka

    def _rotate_lv_ccw(self):
        """Obraca live view o -90° (CCW)."""
        self._lv_rotation = (self._lv_rotation - 90) % 360

    def _rotate_lv_cw(self):
        """Obraca live view o +90° (CW)."""
        self._lv_rotation = (self._lv_rotation + 90) % 360

    def _update_frame(self, data, is_blinking):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            # Udana klatka = USB stabilne → odblokuj capture jeśli było zablokowane
            if self._capture_blocked:
                self._capture_blocked = False
                if self.lv_thread and self.lv_thread.isRunning():
                    self.btn_cap.setEnabled(True)
                    self.btn_cap.setText(self.tr("CAPTURE PHOTO"))
            if self._lv_rotation != 0:
                pixmap = pixmap.transformed(
                    QTransform().rotate(self._lv_rotation),
                    Qt.TransformationMode.FastTransformation
                )
            scaled = pixmap.scaled(
                self.lv_screen.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation
            )
            self.lv_screen.setPixmap(scaled)
            self.lv_screen.setStyleSheet(
                "background: #3d3d3d; border: 2px solid #924040;"
                if is_blinking else
                "background: #3d3d3d; border: 2px solid #555;"
            )

    # ─────────────────────────────── Stan aparatu

    BTN_STYLE_NORMAL = (
        "QPushButton { background-color: palette(button); }"
        " QPushButton:hover { background-color: palette(midlight); }"
        " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: palette(button); }"
        " QPushButton:focus:hover { background-color: palette(midlight); }"
    )
    BTN_STYLE_STOP = BTN_STYLE_RED

    def set_camera_ready(self, ready):
        """Ustawia stan gotowości aparatu — włącza/wyłącza przyciski i kontrolki."""
        self._camera_ready = ready

        # Worker ustawień: start gdy aparat gotowy i LV nieaktywne (i widok aktywny)
        lv_running = self.lv_thread and self.lv_thread.isRunning()
        if ready and not lv_running and self._view_active:
            self._settings_panel.activate()
        elif not ready:
            self._settings_panel.deactivate()

        usb_busy = (
            self._stopping
            or (self._dead_thread is not None and self._dead_thread.isRunning())
        )
        if not usb_busy:
            self.exposure_ctrl.setEnabled(ready)
            self.image_ctrl.setEnabled(ready)
            self.focus_ctrl.setEnabled(ready)

        if self._stopping:
            pass  # LV zatrzymuje się — nie zmieniaj przycisku
        elif not ready:
            self.btn_lv.setEnabled(False)
        elif not (self.lv_thread and self.lv_thread.isRunning()):
            self.btn_lv.setText(self.tr("START LIVE VIEW"))
            self.btn_lv.setStyleSheet(self.BTN_STYLE_NORMAL)
            self.btn_lv.setEnabled(True)
            if self._view_active:
                QTimer.singleShot(50, self.btn_lv.setFocus)

        if not (self.lv_thread and self.lv_thread.isRunning()):
            self._set_buttons_enabled(ready)

    def _set_buttons_enabled(self, enabled):
        """Włącza/wyłącza przyciski zależne od aparatu.
        btn_lv zarządzany osobno w set_camera_ready()."""
        self.btn_cap.setEnabled(enabled and self.lv_thread is not None
                                and self.lv_thread.isRunning())
        self.btn_save.setEnabled(enabled)

    # ─────────────────────────────── Live View — sterowanie

    def _toggle_liveview(self):
        """Przełącza LV: START lub STOP."""
        if self.lv_thread and self.lv_thread.isRunning():
            self._stop_lv()
        elif self._camera_ready:
            self._start_lv()

    def _start_lv(self):
        """Inicjalizuje i uruchamia interfejs gphoto."""
        # Zatrzymaj worker i wyłącz panel — zwalnia USB dla GPhotoInterface
        self._settings_panel.deactivate()

        self.btn_lv.setEnabled(False)
        self._error_stopped = False

        self.lv_thread = GPhotoInterface()

        self.exposure_ctrl.gphoto = self.lv_thread
        self.image_ctrl.gphoto = self.lv_thread
        self.focus_ctrl.gphoto = self.lv_thread

        self.lv_thread.settings_loaded.connect(self.exposure_ctrl.sync_with_camera)
        self.lv_thread.settings_loaded.connect(self.image_ctrl.sync_with_camera)
        self.lv_thread.settings_loaded.connect(self.focus_ctrl.sync_with_camera)
        self.lv_thread.frame_received.connect(self._update_frame)
        self.lv_thread.error_occurred.connect(self._on_lv_error)
        self.lv_thread.image_captured.connect(self._on_image_captured)
        self.lv_thread.capture_failed.connect(self._on_capture_failed)

        self.lv_thread.start()

        self.btn_lv.setEnabled(True)
        self.btn_cap.setEnabled(True)
        self.btn_lv_rotate_left.setEnabled(True)
        self.btn_lv_rotate_right.setEnabled(True)
        self.btn_lv.setText(self.tr("STOP LIVE VIEW"))
        self.btn_lv.setStyleSheet(self.BTN_STYLE_STOP)

        # Kontrolki ustawień działają przez lv_thread podczas LV — re-enable panelu
        self._settings_panel.setEnabled(True)
        self.exposure_ctrl.setEnabled(True)
        self.image_ctrl.setEnabled(True)
        self.focus_ctrl.setEnabled(True)

    def _stop_settings_worker(self):
        """Deleguje zatrzymanie workera ustawień do panelu."""
        self._settings_panel._stop_worker()

    def _stop_lv(self):
        """Zatrzymuje wątek. USB zwolnione po finished → START aktywny."""
        self._error_stopped = False
        self._capture_blocked = False
        dead_thread = self.lv_thread
        self.lv_thread = None
        self.exposure_ctrl.gphoto = None
        self.image_ctrl.gphoto = None
        self.focus_ctrl.gphoto = None
        self.lv_screen.clear()
        self.lv_screen.setText(self.tr("LIVE VIEW OFF"))
        self.lv_screen.setStyleSheet(
            "background: #3d3d3d; border: 2px solid #555; color: white;"
        )
        self.btn_cap.setEnabled(False)
        self.btn_cap.setText(self.tr("CAPTURE PHOTO"))
        self._capture_timer.stop()
        self.btn_lv_rotate_left.setEnabled(False)
        self.btn_lv_rotate_right.setEnabled(False)
        self.btn_lv.setStyleSheet(self.BTN_STYLE_STOP)
        self.btn_lv.setEnabled(False)
        self.btn_lv.setText(self.tr("Stopping..."))

        if dead_thread:
            self._stopping = True
            dead_thread.keep_running = False
            dead_thread.mutex.lock()
            try:
                dead_thread.command_queue.clear()
            finally:
                dead_thread.mutex.unlock()
            for sig in (dead_thread.frame_received, dead_thread.settings_loaded,
                        dead_thread.error_occurred, dead_thread.capture_failed):
                try:
                    sig.disconnect()
                except RuntimeError:
                    pass
            if dead_thread.isRunning():
                dead_thread.finished.connect(self._on_thread_finished)
                QTimer.singleShot(4000, lambda: self._force_terminate(dead_thread))
            else:
                self._on_thread_finished()
        else:
            self._on_thread_finished()

    def _on_lv_error(self, error_msg):
        """Obsługa błędów live view — pokazuje RECONNECT natychmiast."""
        self._stopping = False

        dead_thread = self.lv_thread
        self.lv_thread = None
        self.exposure_ctrl.gphoto = None
        self.image_ctrl.gphoto = None
        self.focus_ctrl.gphoto = None

        if dead_thread:
            for sig in (dead_thread.frame_received, dead_thread.settings_loaded,
                        dead_thread.error_occurred, dead_thread.capture_failed):
                try:
                    sig.disconnect()
                except RuntimeError:
                    pass

        self.exposure_ctrl.setEnabled(False)
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl.setEnabled(False)
        self._set_buttons_enabled(False)
        self.btn_cap.setText(self.tr("CAPTURE PHOTO"))
        self.lv_screen.setText(self.tr("Connection lost."))
        self.lv_screen.setStyleSheet(
            "background: #3d3d3d; border: 2px solid #555; color: #888;"
        )

        self._error_stopped = True
        self._camera_ready = False
        self.btn_lv.setEnabled(False)  # aparat auto-wykryty — ponownie włączy się po probe

        if dead_thread and dead_thread.isRunning():
            self._dead_thread = dead_thread
            dead_thread.keep_running = False
            dead_thread.mutex.lock()
            try:
                dead_thread.command_queue.clear()
            finally:
                dead_thread.mutex.unlock()
            dead_thread.finished.connect(self._on_dead_thread_finished)
            QTimer.singleShot(4000, lambda: self._force_terminate(dead_thread))
        else:
            # Wątek już martwy — USB wolne, od razu uruchom probe.
            self.camera_released.emit()

    def _force_terminate(self, thread):
        """Ostateczność: terminate jeśli wątek nie zakończył się sam."""
        try:
            if thread.isRunning():
                thread.terminate()
        except RuntimeError:
            pass

    def _on_dead_thread_finished(self):
        """Wywoływane gdy umierający wątek zwolnił USB po błędzie LV."""
        self._dead_thread = None
        # USB zwolnione — uruchom probe żeby wykryć powrót aparatu.
        self.camera_released.emit()

    def _on_thread_finished(self):
        """Wywoływane gdy user kliknął STOP i wątek zakończył run()."""
        self._stopping = False
        self.btn_lv.setText(self.tr("START LIVE VIEW"))
        self.btn_lv.setStyleSheet(self.BTN_STYLE_NORMAL)
        self.btn_lv.setEnabled(self._camera_ready)
        # USB zwolnione — sygnał do main_window żeby uruchomił probe.
        # Probe wywoła set_camera_ready(True) → dopiero wtedy worker startuje.
        self.camera_released.emit()

    # ─────────────────────────────── Capture

    def _on_capture_tick(self):
        """Timer — aktualizuje tekst przycisku co sekundę podczas capture."""
        self._capture_secs += 1
        self.btn_cap.setText(self.tr("CAPTURING... %1s").replace("%1", str(self._capture_secs)))

    def _on_capture_clicked(self):
        """Kolejkuje zdjęcie na wątku gphoto."""
        if self.lv_thread and self.lv_thread.isRunning():
            self.btn_cap.setEnabled(False)
            self.btn_cap.setText(self.tr("CAPTURING... 0s"))
            self.btn_lv.setEnabled(False)
            self._capture_secs = 0
            self._capture_timer.start()
            self.update_capture_directory()
            self.lv_thread.capture_photo(self._capture_dir)

    def _on_image_captured(self, file_path):
        """Callback: zdjęcie zapisane — otwórz podgląd."""
        print(f"Image captured: {file_path}")
        self._capture_timer.stop()
        self.btn_cap.setText(self.tr("CAPTURE PHOTO"))
        lv_alive = self.lv_thread is not None and self.lv_thread.isRunning()
        self.btn_lv.setEnabled(lv_alive)
        # Nie odblokowuj capture natychmiast — aparat potrzebuje czasu na recovery LV.
        # _update_frame odblokuje przycisk po pierwszej stabilnej klatce.
        if lv_alive:
            self._capture_blocked = True
        else:
            self.btn_cap.setEnabled(False)

        dialog = PhotoPreviewDialog(
            file_path, parent=None,
            close_all_callback=self.close_all_previews
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.wb_applied.connect(self.image_ctrl.apply_wb_temperature)

        def _on_dialog_closed():
            if dialog in self._preview_dialogs:
                self._preview_dialogs.remove(dialog)
            self._emit_preview_list()

        dialog.destroyed.connect(_on_dialog_closed)
        self._preview_dialogs.append(dialog)
        dialog.show()
        self._emit_preview_list()

    def _emit_preview_list(self):
        """Emituje aktualną listę podglądów do MainWindow (dla menu View)."""
        pairs = [(os.path.basename(d.windowTitle()), d)
                 for d in self._preview_dialogs]
        self.preview_list_changed.emit(pairs)

    def _on_capture_failed(self, error_msg):
        """Obsługa błędu capture — NIE zabija sesji LV."""
        print(f"Capture failed: {error_msg}")
        self._capture_timer.stop()
        self._capture_blocked = True
        self.btn_cap.setEnabled(False)
        self.btn_cap.setText(self.tr("CAPTURE PHOTO"))
        self.btn_lv.setEnabled(True)

    # ─────────────────────────────── Leave / Enter

    def on_enter(self):
        """Wywoływane przez MainWindow przy przejściu do widoku Camera."""
        self._view_active = True
        # NIE startujemy workera tu — probe (wywoływane po on_enter) wywoła
        # set_camera_ready(True), które dopiero uruchomi workera po zwolnieniu USB.
        # Focus: jeśli aparat już gotowy i przycisk enabled — ustaw od razu.
        if self._camera_ready and self.btn_lv.isEnabled():
            QTimer.singleShot(150, self.btn_lv.setFocus)

    def on_leave(self):
        """Wywoływane przy opuszczeniu widoku Camera — zamyka sesję PTP."""
        self._view_active = False
        self._settings_panel.deactivate()
        if self.lv_thread and self.lv_thread.isRunning():
            self._stop_lv()
        self.lv_thread = None
        self._dead_thread = None
        self._error_stopped = False
        self.exposure_ctrl.gphoto = None
        self.image_ctrl.gphoto = None
        self.focus_ctrl.gphoto = None
        self.exposure_ctrl.setEnabled(False)
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl.setEnabled(False)
        self.lv_screen.clear()
        self.lv_screen.setText(self.tr("LIVE VIEW OFF"))
        self.lv_screen.setStyleSheet(
            "background: #3d3d3d; border: 2px solid #555; color: white;"
        )
        self.btn_lv.setText(self.tr("START LIVE VIEW"))
        self.btn_lv.setStyleSheet(self.BTN_STYLE_NORMAL)
        self.btn_lv.setEnabled(self._camera_ready)
        self._capture_timer.stop()
        self.btn_cap.setEnabled(False)
        self.btn_cap.setText(self.tr("CAPTURE PHOTO"))
        self.btn_lv_rotate_left.setEnabled(False)
        self.btn_lv_rotate_right.setEnabled(False)
        self._set_buttons_enabled(self._camera_ready)

    def is_lv_active(self) -> bool:
        """True gdy sesja PTP aktywna LUB gdy umierający wątek trzyma USB."""
        if self.lv_thread is not None and self.lv_thread.isRunning():
            return True
        if self._dead_thread is not None and self._dead_thread.isRunning():
            return True
        return False

    def close_all_previews(self):
        """Zamyka wszystkie otwarte okna podglądu zdjęć."""
        for dialog in list(self._preview_dialogs):
            try:
                dialog.close()
            except Exception:
                pass
        self._preview_dialogs.clear()

    # ─────────────────────────────── Profile aparatu

    def _profiles_dir(self) -> str:
        """Zwraca ścieżkę do katalogu camera_profiles/ w katalogu projektu."""
        project_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(project_dir))
        d = os.path.join(project_root, self.DEFAULT_PROFILES_SUBDIR)
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
            import json
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"name": safe, "settings": settings}, f, indent=2)
            self.status_message.emit(f"Profile saved: {safe}", 3000)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.tr("Save Profile"), self.tr("Error saving profile:\n%1").replace("%1", str(e)))

    def _on_load_profile(self):
        """Otwiera przeglądarkę profili."""
        dialog = ProfileBrowserDialog(self._profiles_dir(), parent=self)
        dialog.profile_selected.connect(self._apply_profile)
        dialog.exec()

    def _apply_profile(self, settings: dict):
        """Aplikuje ustawienia z profilu do UI i aparatu."""
        # Wybierz aktywny worker: LV lub settings panel
        lv_active = self.lv_thread and self.lv_thread.isRunning()
        worker = self.lv_thread if lv_active else self._settings_panel.worker

        # Exposure
        for key in ('shutterspeed', 'aperture', 'iso', 'exposurecompensation'):
            if key in settings:
                ctrl = self.exposure_ctrl.controls.get(key)
                if ctrl and ctrl["slider"]:
                    ctrl["slider"].set_value(str(settings[key]))
                    if ctrl["auto"]:
                        self.exposure_ctrl._update_auto_visuals(
                            key, settings[key] == "Auto"
                        )
                if worker:
                    worker.update_camera_param(key, str(settings[key]))

        # Image
        img_keys = ('picturestyle', 'imageformat', 'alomode',
                    'whitebalance', 'colortemperature')
        af_keys = ('focusmode', 'afmethod', 'continuousaf')

        img_s = {k: v for k, v in settings.items() if k in img_keys}
        af_s = {k: v for k, v in settings.items() if k in af_keys}

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

        self.status_message.emit("Profile loaded", 3000)


