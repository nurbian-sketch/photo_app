import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QSizePolicy, QDialog
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QPixmap

from core.gphoto_interface import GPhotoInterface

from ui.views.camera_components.exposure_controls import ExposureControls
from ui.views.camera_components.image_controls import ImageControls
from ui.views.camera_components.autofocus_controls import AutofocusControls


# ─────────────────────────────────────────── Popup podglądu zdjęcia

class CapturePreviewDialog(QDialog):
    """Okno podglądu przechwyconego zdjęcia — niezależne od trybu okna/fullscreen."""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(image_path))
        self.setMinimumSize(640, 480)
        self.resize(1024, 768)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: #1a1a1a;")
        self._label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        layout.addWidget(self._label)

        info = QLabel(image_path)
        info.setStyleSheet("color: #aaa; padding: 4px; font-size: 11px;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)

        self._pixmap = QPixmap(image_path)
        self._update_preview()

    def _update_preview(self):
        if self._pixmap.isNull():
            self._label.setText("Cannot load image")
            return
        scaled = self._pixmap.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self._label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()


# ─────────────────────────────────────────── Widok kamery

class CameraView(QWidget):

    DEFAULT_CAPTURE_DIR = os.path.expanduser("~/Pictures/SessionsAssistant")

    # Stany przycisku LV
    _LV_STATE_IDLE       = 'idle'       # START LIVE VIEW
    _LV_STATE_RUNNING    = 'running'    # STOP LIVE VIEW
    _LV_STATE_RECONNECT  = 'reconnect'  # RECONNECT LIVE VIEW

    def __init__(self, camera_service=None):
        super().__init__()
        self.cs = camera_service
        self.lv_thread = None
        self._camera_ready = False
        self._lv_state = self._LV_STATE_IDLE
        self._settings = QSettings("Grzeza", "SessionsAssistant")
        self._capture_dir = self._settings.value(
            "capture/directory", self.DEFAULT_CAPTURE_DIR
        )
        self._preview_dialogs = []
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # --- SPLITTER ---
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(12)

        # ---- LEFT: Control Panel (2 kolumny) ----
        control_panel = QWidget()
        control_panel.setMinimumWidth(760)
        control_layout = QHBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(30)

        # Column 1: Exposure + buttons
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

        # Column 2: Image + Focus + buttons
        col2 = QWidget()
        col2.setMinimumWidth(280)
        col2_layout = QVBoxLayout(col2)
        col2_layout.setContentsMargins(0, 0, 0, 0)

        self.image_ctrl = ImageControls()
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl = AutofocusControls()
        self.focus_ctrl.setEnabled(False)
        col2_layout.addWidget(self.image_ctrl, 2)
        col2_layout.addSpacing(8)
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

        # Connect button — widoczny tylko gdy brak aparatu
        self.btn_connect = QPushButton("CONNECT CAMERA")
        self.btn_connect.setFixedHeight(40)
        self.btn_connect.setStyleSheet(
            "font-weight: bold; background-color: #1565c0; color: white;"
        )
        self.btn_connect.setVisible(False)
        preview_layout.addWidget(self.btn_connect)

        self.lv_screen = QLabel("LIVE VIEW OFF")
        self.lv_screen.setStyleSheet(
            "background: black; border: 2px solid #333; color: white;"
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
        row3.addStretch()
        row3.addWidget(self.btn_lv)
        row3.addWidget(self.btn_cap)
        row3.addStretch()
        preview_layout.addLayout(row3)

        # Splitter setup
        self.main_splitter.addWidget(control_panel)
        self.main_splitter.addWidget(preview_panel)
        self.main_splitter.setCollapsible(0, False)
        self.main_splitter.setCollapsible(1, False)
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 6)
        main_layout.addWidget(self.main_splitter)

        # --- SIGNALS ---
        self.btn_update.clicked.connect(self._on_update_clicked)
        self.btn_lv.clicked.connect(self._toggle_liveview)
        self.btn_cap.clicked.connect(self._on_capture_clicked)

        self._set_buttons_enabled(False)

    # ─────────────────────────────────────────── FRAME UPDATE

    def _update_frame(self, data, is_blinking):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            scaled = pixmap.scaled(
                self.lv_screen.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation
            )
            self.lv_screen.setPixmap(scaled)
            if is_blinking:
                self.lv_screen.setStyleSheet(
                    "background: black; border: 2px solid #ff8a65;"
                )
            else:
                self.lv_screen.setStyleSheet(
                    "background: black; border: 2px solid #333;"
                )

    # ─────────────────────────────────────────── CAMERA READY STATE

    def set_camera_ready(self, ready):
        """Ustawia stan gotowości aparatu — włącza/wyłącza przyciski."""
        self._camera_ready = ready
        self.btn_connect.setVisible(not ready)
        if not self._lv_running():
            self._set_buttons_enabled(ready)

    def _lv_running(self) -> bool:
        """True gdy wątek LV jest aktywny."""
        return self.lv_thread is not None and self.lv_thread.isRunning()

    def _set_buttons_enabled(self, enabled):
        """Włącza/wyłącza przyciski zależne od aparatu."""
        self.btn_lv.setEnabled(enabled)
        self.btn_cap.setEnabled(enabled and self._lv_running())
        self.btn_save.setEnabled(enabled)
        self.btn_update.setEnabled(enabled)

    # ─────────────────────────────────────────── LV STATE MACHINE

    def _set_lv_state(self, state: str):
        """
        Centralny punkt zarządzania stanem przycisku LV.
        Trzy stany: idle / running / reconnect.
        """
        self._lv_state = state

        if state == self._LV_STATE_IDLE:
            self.btn_lv.setText("START LIVE VIEW")
            self.btn_lv.setStyleSheet("")
            self.btn_lv.setEnabled(self._camera_ready)
            self.btn_cap.setEnabled(False)

        elif state == self._LV_STATE_RUNNING:
            self.btn_lv.setText("STOP LIVE VIEW")
            self.btn_lv.setStyleSheet(
                "background-color: #c62828; color: white; font-weight: bold;"
            )
            self.btn_lv.setEnabled(True)
            self.btn_cap.setEnabled(True)

        elif state == self._LV_STATE_RECONNECT:
            self.btn_lv.setText("RECONNECT LIVE VIEW")
            self.btn_lv.setStyleSheet(
                "background-color: #e65100; color: white; font-weight: bold;"
            )
            self.btn_lv.setEnabled(True)
            self.btn_cap.setEnabled(False)

    def _toggle_liveview(self):
        """Przełącza stan LV — obsługuje wszystkie trzy stany przycisku."""
        if self._lv_state == self._LV_STATE_RUNNING:
            self._stop_lv()
        else:
            # idle lub reconnect — oba startują od nowa
            self._start_lv()

    # ─────────────────────────────────────────── START / STOP LV

    def _start_lv(self):
        """Inicjalizuje i uruchamia wątek gphoto. Działa zarówno przy
        pierwszym starcie jak i przy reconnect."""
        self.btn_lv.setEnabled(False)  # blokada wielokrotnego kliknięcia

        # Fix #3 — zawsze tworzymy nowy wątek; poprzedni jest już zatrzymany
        # (przez _stop_lv lub przez error_occurred → lv_thread=None)
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

        # Fix #3 — sygnał finished czyści referencję po cichym zakończeniu wątku
        self.lv_thread.finished.connect(self._on_thread_finished)

        self.lv_thread.start()

        self.exposure_ctrl.setEnabled(True)
        self.image_ctrl.setEnabled(True)
        self.focus_ctrl.setEnabled(True)
        self._set_lv_state(self._LV_STATE_RUNNING)

    def _stop_lv(self):
        """Zatrzymuje wątek i czyści widok."""
        if self.lv_thread:
            self.lv_thread.stop()
            self.lv_thread = None

        self._cleanup_controls()
        self._set_lv_state(self._LV_STATE_IDLE)
        self._set_lv_screen_off()

    def _cleanup_controls(self):
        """Odłącza gphoto od kontrolek i wyłącza je."""
        self.exposure_ctrl.gphoto = None
        self.image_ctrl.gphoto = None
        self.focus_ctrl.gphoto = None
        self.exposure_ctrl.setEnabled(False)
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl.setEnabled(False)

    def _set_lv_screen_off(self, message="LIVE VIEW OFF"):
        """Resetuje ekran podglądu do stanu nieaktywnego."""
        self.lv_screen.clear()
        self.lv_screen.setText(message)
        self.lv_screen.setStyleSheet(
            "background: black; border: 2px solid #333; color: white;"
        )

    # ─────────────────────────────────────────── ERROR / RECONNECT

    def _on_lv_error(self, error_msg):
        """
        Fix #3 — obsługa błędu krytycznego z wątku gphoto.
        Wątek sam się zatrzymuje przed emisją sygnału,
        więc tylko czyścimy stan UI i oferujemy reconnect.
        """
        if self.lv_thread:
            self.lv_thread.stop()
            self.lv_thread = None  # Fix #3 — kluczowe: nowy wątek przy reconnect

        self._cleanup_controls()
        self._set_lv_screen_off(f"CONNECTION LOST\n{error_msg}")
        self.lv_screen.setStyleSheet(
            "background: black; border: 2px solid #c62828; color: #c62828;"
        )
        # Fix #3 — stan reconnect: przycisk aktywny, kliknięcie → _start_lv()
        self._set_lv_state(self._LV_STATE_RECONNECT)

    def _on_thread_finished(self):
        """
        Fix #3 — wątek zakończył się (normalnie lub przez stop()).
        Jeśli nie było error_occurred, UI może być w stanie running —
        wtedy cicho przechodzimy do idle.
        """
        if self._lv_state == self._LV_STATE_RUNNING:
            # Wątek skończył bez błędu (np. keep_running=False z zewnątrz)
            self.lv_thread = None
            self._cleanup_controls()
            self._set_lv_state(self._LV_STATE_IDLE)
            self._set_lv_screen_off()

    # ─────────────────────────────────────────── CAPTURE

    def _on_capture_clicked(self):
        """Kolejkuje zdjęcie na wątku gphoto."""
        if self._lv_running():
            self.btn_cap.setEnabled(False)
            self.btn_cap.setText("CAPTURING...")
            self.lv_thread.capture_photo(self._capture_dir)

    def _on_image_captured(self, file_path):
        """Callback: zdjęcie zapisane — otwórz podgląd."""
        print(f"Image captured: {file_path}")
        self.btn_cap.setEnabled(True)
        self.btn_cap.setText("CAPTURE PHOTO")

        dialog = CapturePreviewDialog(file_path, parent=None)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.destroyed.connect(
            lambda: self._preview_dialogs.remove(dialog)
            if dialog in self._preview_dialogs else None
        )
        self._preview_dialogs.append(dialog)
        dialog.show()

    # ─────────────────────────────────────────── LEAVE / ENTER

    def on_leave(self):
        """Wywoływane przy opuszczeniu widoku Camera.
        Zatrzymuje LV i resetuje UI do stanu początkowego."""
        if self._lv_running():
            self._stop_lv()
        else:
            # Upewnij się że kontrolki są wyłączone nawet przy reconnect state
            self._cleanup_controls()
            self.lv_thread = None

        self._set_lv_state(self._LV_STATE_IDLE)
        self._set_lv_screen_off()
        self._set_buttons_enabled(self._camera_ready)

    def is_lv_active(self) -> bool:
        """
        Fix #8 — publiczna metoda dla MainWindow._probe_camera().
        Zwraca True gdy sesja PTP jest aktywna.
        """
        return self._lv_running()

    def _on_update_clicked(self):
        """Zbiera ustawienia i wysyła (zachowano dla kompatybilności)."""
        settings = {}
        settings.update(self.exposure_ctrl.get_settings())
        settings.update(self.image_ctrl.get_settings())
        settings.update(self.focus_ctrl.get_settings())
        if self.cs:
            self.cs.apply_bulk_settings(settings)
