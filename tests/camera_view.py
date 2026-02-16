from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from core.gphoto_interface import GPhotoInterface

from ui.views.camera_components.exposure_controls import ExposureControls
from ui.views.camera_components.image_controls import ImageControls
from ui.views.camera_components.autofocus_controls import AutofocusControls


class CameraView(QWidget):
    def __init__(self, camera_service=None):
        super().__init__()
        self.cs = camera_service
        self.lv_thread = None
        self._camera_ready = False
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # --- SPLITTER ---
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(12)

        # ---- LEFT: Control Panel (2 columns) ----
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

        self.lv_screen = QLabel("LIVE VIEW OFF")
        self.lv_screen.setStyleSheet("background: black; border: 2px solid #333; color: white;")
        self.lv_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lv_screen.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        preview_layout.addWidget(self.lv_screen)

        row3 = QHBoxLayout()
        row3.setContentsMargins(0, 5, 0, 0)
        self.btn_lv = QPushButton("START LIVE VIEW")
        self.btn_cap = QPushButton("CAPTURE TEST PHOTO")
        self.btn_lv.setFixedSize(200, 40)
        self.btn_cap.setFixedSize(180, 40)
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

        # Wszystkie przyciski wyłączone do momentu wykrycia aparatu
        self._set_buttons_enabled(False)

    # --- CAMERA READY STATE ---

    def set_camera_ready(self, ready):
        """Ustawia stan gotowości aparatu — włącza/wyłącza przyciski."""
        self._camera_ready = ready
        # Przyciski aktywne tylko gdy aparat podłączony i LV nieaktywne
        if not (self.lv_thread and self.lv_thread.isRunning()):
            self._set_buttons_enabled(ready)

    def _set_buttons_enabled(self, enabled):
        """Włącza/wyłącza przyciski zależne od aparatu."""
        self.btn_lv.setEnabled(enabled)
        self.btn_cap.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)
        self.btn_update.setEnabled(enabled)

    # --- LIVE VIEW & GPHOTO LOGIC ---

    def _toggle_liveview(self):
        """Przełącza stan wątku interfejsu gphoto."""
        if self.lv_thread and self.lv_thread.isRunning():
            self._stop_lv()
        else:
            self._start_lv()

    def _start_lv(self):
        """Inicjalizuje i uruchamia interfejs gphoto."""
        self.btn_lv.setEnabled(False)  # Blokada wielokrotnego kliknięcia

        self.lv_thread = GPhotoInterface()
        
        self.exposure_ctrl.gphoto = self.lv_thread
        self.image_ctrl.gphoto = self.lv_thread
        self.focus_ctrl.gphoto = self.lv_thread
        
        self.lv_thread.settings_loaded.connect(self.exposure_ctrl.sync_with_camera)
        self.lv_thread.settings_loaded.connect(self.image_ctrl.sync_with_camera)
        self.lv_thread.settings_loaded.connect(self.focus_ctrl.sync_with_camera)
        self.lv_thread.frame_received.connect(self._update_frame)
        self.lv_thread.error_occurred.connect(self._on_lv_error)
        
        self.lv_thread.start()
        
        self.exposure_ctrl.setEnabled(True)
        self.image_ctrl.setEnabled(True)
        self.focus_ctrl.setEnabled(True)
        self.btn_lv.setEnabled(True)  # Teraz działa jako STOP
        self.btn_lv.setText("STOP LIVE VIEW")
        self.btn_lv.setStyleSheet("background-color: #c62828; color: white; font-weight: bold;")

    def _stop_lv(self):
        """Zatrzymuje wątek i czyści widok."""
        if self.lv_thread:
            self.lv_thread.stop()
            self.exposure_ctrl.gphoto = None
            self.image_ctrl.gphoto = None
            self.focus_ctrl.gphoto = None
            
        self.exposure_ctrl.setEnabled(False)
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl.setEnabled(False)
        self.lv_screen.clear()
        self.lv_screen.setText("LIVE VIEW OFF")
        self.lv_screen.setStyleSheet("background: black; border: 2px solid #333; color: white;")
        self.btn_lv.setText("START LIVE VIEW")
        self.btn_lv.setStyleSheet("")
        self._set_buttons_enabled(self._camera_ready)

    def _update_frame(self, frame_data, is_blinking):
        """Wyświetla nową klatkę i obsługuje alarm mrugania."""
        pixmap = QPixmap()
        pixmap.loadFromData(frame_data)
        
        scaled_pixmap = pixmap.scaled(
            self.lv_screen.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.lv_screen.setPixmap(scaled_pixmap)
        
        if is_blinking:
            self.lv_screen.setStyleSheet("background: black; border: 6px solid red; color: white;")
        else:
            self.lv_screen.setStyleSheet("background: black; border: 2px solid #333; color: white;")

    def _on_lv_error(self, error_msg):
        """Graceful stop — przycisk zmienia się na RECONNECT."""
        if self.lv_thread:
            self.lv_thread.stop()
            self.exposure_ctrl.gphoto = None
            self.image_ctrl.gphoto = None
            self.focus_ctrl.gphoto = None
            self.lv_thread = None

        self.exposure_ctrl.setEnabled(False)
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl.setEnabled(False)
        self._set_buttons_enabled(False)
        self.lv_screen.setText(f"CONNECTION LOST\n{error_msg}")
        self.lv_screen.setStyleSheet("background: black; border: 2px solid #c62828; color: #c62828;")
        self.btn_lv.setEnabled(True)  # Tylko RECONNECT aktywny
        self.btn_lv.setText("RECONNECT LIVE VIEW")
        self.btn_lv.setStyleSheet("background-color: #e65100; color: white; font-weight: bold;")

    def on_leave(self):
        """Wywoływane przy opuszczeniu widoku Camera.
        Zamyka sesję PTP i resetuje UI do stanu początkowego."""
        if self.lv_thread and self.lv_thread.isRunning():
            self._stop_lv()
        # Reset UI niezależnie od stanu (np. po RECONNECT)
        self.lv_thread = None
        self.exposure_ctrl.gphoto = None
        self.image_ctrl.gphoto = None
        self.focus_ctrl.gphoto = None
        self.exposure_ctrl.setEnabled(False)
        self.image_ctrl.setEnabled(False)
        self.focus_ctrl.setEnabled(False)
        self.lv_screen.clear()
        self.lv_screen.setText("LIVE VIEW OFF")
        self.lv_screen.setStyleSheet("background: black; border: 2px solid #333; color: white;")
        self.btn_lv.setText("START LIVE VIEW")
        self.btn_lv.setStyleSheet("")
        self._set_buttons_enabled(self._camera_ready)

    def _on_update_clicked(self):
        """Zbiera ustawienia i wysyła (zachowano dla kompatybilności)."""
        settings = {}
        settings.update(self.exposure_ctrl.get_settings())
        settings.update(self.image_ctrl.get_settings())
        settings.update(self.focus_ctrl.get_settings())
        if self.cs:
            self.cs.apply_bulk_settings(settings)
