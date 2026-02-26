import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QPixmap, QTransform

from core.gphoto_interface import GPhotoInterface

from ui.views.camera_components.exposure_controls import ExposureControls
from ui.views.camera_components.image_controls import ImageControls
from ui.views.camera_components.autofocus_controls import AutofocusControls
from ui.dialogs.profile_browser_dialog import ProfileBrowserDialog
from ui.widgets.photo_preview_dialog import PhotoPreviewDialog


# ─────────────────────────────── Widok kamery

class CameraView(QWidget):

    # Sygnał żądania ponownego połączenia z aparatem
    reconnect_requested = pyqtSignal()
    # Emitowany gdy lista otwartych podglądów się zmienia (open/close)
    preview_list_changed = pyqtSignal(list)  # lista (title, dialog) par
    # Komunikaty do status bar main window
    status_message = pyqtSignal(str, int)  # tekst, timeout_ms (0=permanentny)

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
        self._needs_reconnect = False  # Flaga: było zerwane połączenie
        self._error_stopped = False   # Flaga: wątek zatrzymany przez błąd (nie przez user)
        self._stopping = False    # Wątek w trakcie zatrzymywania
        self._reconnecting = False  # Trwa próba reconnect
        self._capture_blocked = False  # Capture zablokowany po błędzie — odblokuj na klatce
        self._capture_secs = 0         # Licznik sekund oczekiwania na capture
        self._capture_timer = QTimer()
        self._capture_timer.setInterval(1000)
        self._capture_timer.timeout.connect(self._on_capture_tick)
        self._settings = QSettings("Grzeza", "SessionsAssistant")
        self._capture_dir = self._get_capture_directory()
        self._preview_dialogs = []  # Referencje do otwartych podglądów
        self._lv_rotation = 0       # Rotacja live view: 0, 90, 180, 270
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

        # ---- LEFT: Panel sterowania (2 kolumny) ----
        control_panel = QWidget()
        control_panel.setMinimumWidth(760)
        control_layout = QHBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(30)

        # Kolumna 1: Exposure + przyciski profili
        col1 = QWidget()
        col1.setMinimumWidth(450)
        col1_layout = QVBoxLayout(col1)
        col1_layout.setContentsMargins(0, 0, 0, 0)

        self.exposure_ctrl = ExposureControls()
        self.exposure_ctrl.setEnabled(False)
        col1_layout.addWidget(self.exposure_ctrl, 3)
        col1_layout.addSpacing(20)
        col1_layout.addStretch(1)

        row1 = QHBoxLayout()
        self.btn_save = QPushButton("Save")
        self.btn_load = QPushButton("Load")
        row1.addWidget(self.btn_save)
        row1.addWidget(self.btn_load)
        row1.addStretch()
        col1_layout.addLayout(row1)

        # Kolumna 2: Image + Focus + przyciski
        col2 = QWidget()
        col2.setMinimumWidth(280)
        col2_layout = QVBoxLayout(col2)
        col2_layout.setContentsMargins(0, 0, 0, 0)

        self.image_ctrl = ImageControls()
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl = AutofocusControls()
        self.focus_ctrl.setEnabled(False)
        col2_layout.addWidget(self.image_ctrl, 2)
        col2_layout.addSpacing(23)
        col2_layout.addWidget(self.focus_ctrl, 1)
        col2_layout.addSpacing(20)
        col2_layout.addStretch(1)

        row2 = QHBoxLayout()
        self.btn_update = QPushButton("UPDATE")
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_update.setStyleSheet("font-weight: bold; color: #2e7d32;")
        row2.addWidget(self.btn_update)
        row2.addWidget(self.btn_cancel)
        row2.addStretch()
        col2_layout.addLayout(row2)

        control_layout.addWidget(col1, 5)
        control_layout.addWidget(col2, 3)

        # ---- RIGHT: Live View ----
        preview_panel = QWidget()
        preview_panel.setMinimumWidth(400)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        self.lv_screen = QLabel("LIVE VIEW OFF")
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
        self.btn_lv = QPushButton("START LIVE VIEW")
        self.btn_cap = QPushButton("CAPTURE PHOTO")
        self.btn_lv.setFixedSize(200, 40)
        self.btn_cap.setFixedSize(180, 40)
        self.btn_cap.setStyleSheet("font-weight: bold;")

        self.btn_lv_rotate_left = QPushButton("↶ 90°")
        self.btn_lv_rotate_left.setFixedSize(65, 40)
        self.btn_lv_rotate_left.setToolTip("Rotate live view 90° CCW")
        self.btn_lv_rotate_left.setEnabled(False)

        self.btn_lv_rotate_right = QPushButton("↷ 90°")
        self.btn_lv_rotate_right.setFixedSize(65, 40)
        self.btn_lv_rotate_right.setToolTip("Rotate live view 90° CW")
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
        self.btn_update.clicked.connect(self._on_update_clicked)
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
                    self.btn_cap.setText("CAPTURE PHOTO")
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
                "background: #3d3d3d; border: 2px solid #ff8a65;"
                if is_blinking else
                "background: #3d3d3d; border: 2px solid #555;"
            )

    # ─────────────────────────────── Stan aparatu

    BTN_STYLE_STOP = "background-color: #c62828; color: white; font-weight: bold;"

    def set_camera_ready(self, ready):
        """Ustawia stan gotowości aparatu — włącza/wyłącza przyciski i kontrolki."""
        self._camera_ready = ready

        usb_busy = (
            self._stopping
            or (self._dead_thread is not None and self._dead_thread.isRunning())
        )
        if not usb_busy:
            self.exposure_ctrl.setEnabled(ready)
            self.image_ctrl.setEnabled(ready)
            self.focus_ctrl.setEnabled(ready)

        if self._reconnecting or self._stopping or self._needs_reconnect:
            pass
        elif not ready:
            self.btn_lv.setText("CONNECT CAMERA")
            self.btn_lv.setStyleSheet("")
            self.btn_lv.setEnabled(True)
        elif not (self.lv_thread and self.lv_thread.isRunning()):
            self.btn_lv.setText("START LIVE VIEW")
            self.btn_lv.setStyleSheet("")
            self.btn_lv.setEnabled(True)

        if not (self.lv_thread and self.lv_thread.isRunning()):
            self._set_buttons_enabled(ready)

    def _set_buttons_enabled(self, enabled):
        """Włącza/wyłącza przyciski zależne od aparatu.
        btn_lv zarządzany osobno w set_camera_ready()."""
        self.btn_cap.setEnabled(enabled and self.lv_thread is not None
                                and self.lv_thread.isRunning())
        self.btn_save.setEnabled(enabled)
        self.btn_update.setEnabled(enabled)

    # ─────────────────────────────── Live View — sterowanie

    def _toggle_liveview(self):
        """Przełącza stan wątku gphoto: CONNECT / START / STOP / RECONNECT."""
        if self.lv_thread and self.lv_thread.isRunning():
            self._stop_lv()
        elif self._needs_reconnect:
            self._try_reconnect()
        elif not self._camera_ready:
            self.reconnect_requested.emit()
        else:
            self._start_lv()

    def _try_reconnect(self):
        """Próbuje reconnect: probe + auto-start LV."""
        self._reconnecting = True
        self.btn_lv.setEnabled(False)
        self.btn_lv.setText("Connecting...")
        self.status_message.emit("Reconnecting camera...", 0)
        self.reconnect_requested.emit()

    def on_probe_completed(self, camera_ready: bool):
        """Wywołane przez MainWindow po zakończeniu probe (gdy _reconnecting=True)."""
        if not self._reconnecting:
            return
        self._reconnecting = False
        if self._stopping:
            self._needs_reconnect = True
            self.btn_lv.setText("RECONNECT")
            self.btn_lv.setEnabled(True)
            self.btn_lv.setStyleSheet("")
            self.status_message.emit("Camera not found — try again", 4000)
            return
        if camera_ready and not (self.lv_thread and self.lv_thread.isRunning()):
            self._needs_reconnect = False
            self._error_stopped = False
            self.status_message.emit("Camera connected", 3000)
            self._start_lv()
        else:
            self._needs_reconnect = True
            self.btn_lv.setText("RECONNECT")
            self.btn_lv.setEnabled(True)
            self.btn_lv.setStyleSheet("")
            self.status_message.emit("Camera not found — try again", 4000)

    def _start_lv(self):
        """Inicjalizuje i uruchamia interfejs gphoto."""
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
        self.btn_lv.setText("STOP LIVE VIEW")
        self.btn_lv.setStyleSheet(self.BTN_STYLE_STOP)

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
        self.lv_screen.setText("LIVE VIEW OFF")
        self.lv_screen.setStyleSheet(
            "background: #3d3d3d; border: 2px solid #555; color: white;"
        )
        self.btn_cap.setEnabled(False)
        self.btn_cap.setText("CAPTURE PHOTO")
        self._capture_timer.stop()
        self.btn_lv_rotate_left.setEnabled(False)
        self.btn_lv_rotate_right.setEnabled(False)
        self.btn_lv.setEnabled(False)
        self.btn_lv.setText("Stopping...")

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
        self._reconnecting = False
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
        self.btn_cap.setText("CAPTURE PHOTO")

        self.lv_screen.setText("Connection lost.\nClick to reconnect.")
        self.lv_screen.setStyleSheet(
            "background: #3d3d3d; border: 2px solid #555; color: #888;"
        )

        self._needs_reconnect = True
        self._error_stopped = True
        self._camera_ready = False
        self.btn_lv.setText("RECONNECT")
        self.btn_lv.setEnabled(True)
        self.btn_lv.setStyleSheet("")

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

    def _force_terminate(self, thread):
        """Ostateczność: terminate jeśli wątek nie zakończył się sam."""
        try:
            if thread.isRunning():
                thread.terminate()
        except RuntimeError:
            pass

    def _on_dead_thread_finished(self):
        """Wywoływane gdy umierający wątek zwolnił USB."""
        self._dead_thread = None

    def _on_thread_finished(self):
        """Wywoływane gdy user kliknął STOP i wątek zakończył run()."""
        self._stopping = False
        if not self._needs_reconnect:
            self.btn_lv.setText("START LIVE VIEW")
            self.btn_lv.setStyleSheet("")
            self.btn_lv.setEnabled(self._camera_ready)

    # ─────────────────────────────── Capture

    def _on_capture_tick(self):
        """Timer — aktualizuje tekst przycisku co sekundę podczas capture."""
        self._capture_secs += 1
        self.btn_cap.setText(f"CAPTURING... {self._capture_secs}s")

    def _on_capture_clicked(self):
        """Kolejkuje zdjęcie na wątku gphoto."""
        if self.lv_thread and self.lv_thread.isRunning():
            self.btn_cap.setEnabled(False)
            self.btn_cap.setText("CAPTURING... 0s")
            self.btn_lv.setEnabled(False)
            self._capture_secs = 0
            self._capture_timer.start()
            self.update_capture_directory()
            self.lv_thread.capture_photo(self._capture_dir)

    def _on_image_captured(self, file_path):
        """Callback: zdjęcie zapisane — otwórz podgląd."""
        print(f"Image captured: {file_path}")
        self._capture_timer.stop()
        self.btn_cap.setText("CAPTURE PHOTO")
        lv_alive = self.lv_thread is not None and self.lv_thread.isRunning()
        self.btn_cap.setEnabled(lv_alive)
        self.btn_lv.setEnabled(lv_alive)

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
        self.btn_cap.setText("CAPTURE PHOTO")
        self.btn_lv.setEnabled(True)

    # ─────────────────────────────── Leave / Enter

    def on_leave(self):
        """Wywoływane przy opuszczeniu widoku Camera — zamyka sesję PTP."""
        if self.lv_thread and self.lv_thread.isRunning():
            self._stop_lv()
        self.lv_thread = None
        self._dead_thread = None
        self._needs_reconnect = False
        self._error_stopped = False
        self._reconnecting = False
        self.exposure_ctrl.gphoto = None
        self.image_ctrl.gphoto = None
        self.focus_ctrl.gphoto = None
        self.exposure_ctrl.setEnabled(False)
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl.setEnabled(False)
        self.lv_screen.clear()
        self.lv_screen.setText("LIVE VIEW OFF")
        self.lv_screen.setStyleSheet(
            "background: #3d3d3d; border: 2px solid #555; color: white;"
        )
        self.btn_lv.setText("START LIVE VIEW")
        self.btn_lv.setStyleSheet("")
        self.btn_lv.setEnabled(self._camera_ready)
        self._capture_timer.stop()
        self.btn_cap.setEnabled(False)
        self.btn_cap.setText("CAPTURE PHOTO")
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

        name, ok = QInputDialog.getText(self, "Save Camera Profile", "Profile name:")
        if not ok or not name.strip():
            return

        name = name.strip()
        safe = "".join(c for c in name if c.isalnum() or c in " _-()").strip()
        if not safe:
            QMessageBox.warning(self, "Save Profile", "Invalid profile name.")
            return

        path = os.path.join(self._profiles_dir(), f"{safe}.json")

        if os.path.exists(path):
            ans = QMessageBox.question(
                self, "Overwrite?",
                f"Profile '{safe}' already exists. Overwrite?",
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
            QMessageBox.warning(self, "Save Profile", f"Error saving profile:\n{e}")

    def _on_load_profile(self):
        """Otwiera przeglądarkę profili."""
        dialog = ProfileBrowserDialog(self._profiles_dir(), parent=self)
        dialog.profile_selected.connect(self._apply_profile)
        dialog.exec()

    def _apply_profile(self, settings: dict):
        """Aplikuje ustawienia z profilu do UI i aparatu."""
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
                if self.lv_thread and self.lv_thread.isRunning():
                    self.lv_thread.update_camera_param(key, settings[key])

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
            if self.lv_thread and self.lv_thread.isRunning():
                for k, v in img_s.items():
                    self.lv_thread.update_camera_param(k, str(v))

        if af_s:
            for param, val in af_s.items():
                combo = self.focus_ctrl._get_combo(param)
                if combo:
                    display = self.focus_ctrl._to_display(param, str(val))
                    combo.blockSignals(True)
                    combo.setCurrentText(display)
                    combo.blockSignals(False)
            if self.lv_thread and self.lv_thread.isRunning():
                for k, v in af_s.items():
                    self.lv_thread.update_camera_param(k, str(v))

        self.status_message.emit("Profile loaded", 3000)

    def _on_update_clicked(self):
        """Zbiera ustawienia i wysyła (zachowano dla kompatybilności)."""
        settings = {}
        settings.update(self.exposure_ctrl.get_settings())
        settings.update(self.image_ctrl.get_settings())
        settings.update(self.focus_ctrl.get_settings())
        if self.cs:
            self.cs.apply_bulk_settings(settings)
