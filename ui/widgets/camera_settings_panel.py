"""
CameraSettingsPanel — wspólny panel ustawień aparatu.
Dwie kolumny: ExposureControls (lewa) i ImageControls + AutofocusControls (prawa).
Zarządza CameraSettingsWorker — activate()/deactivate() zamiast duplikowania logiki.
Używany w CameraView i SessionView.
"""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout

from ui.views.camera_components.exposure_controls import ExposureControls
from ui.views.camera_components.image_controls import ImageControls
from ui.views.camera_components.autofocus_controls import AutofocusControls


class CameraSettingsPanel(QWidget):
    """
    Panel z dwoma kolumnami kontrolek aparatu.

    Atrybuty publiczne: exposure_ctrl, image_ctrl, focus_ctrl.

    Sygnały:
        settings_captured(dict) — emitowany po załadowaniu ustawień z aparatu
        status_message(str)     — komunikaty statusu z workera
    """

    settings_captured = pyqtSignal(dict)
    status_message    = pyqtSignal(str)

    def __init__(self, session_mode_init: bool = False, parent=None):
        super().__init__(parent)
        self._session_mode_init = session_mode_init
        self._worker = None
        self._build_ui()
        self.setEnabled(False)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(30)

        col1 = QWidget()
        col1.setMinimumWidth(450)
        col1_layout = QVBoxLayout(col1)
        col1_layout.setContentsMargins(0, 0, 0, 0)
        self.exposure_ctrl = ExposureControls()
        col1_layout.addWidget(self.exposure_ctrl, 3)
        col1_layout.addSpacing(20)
        col1_layout.addStretch(1)

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

        layout.addWidget(col1, 5)
        layout.addWidget(col2, 3)

    # ─────────────────────────── API publiczne

    def activate(self):
        """Aparat podłączony — uruchom workera, włącz kontrolki."""
        self._start_worker()
        self.setEnabled(True)

    def deactivate(self):
        """Brak aparatu lub sesja aktywna — zatrzymaj workera, wyłącz kontrolki."""
        self._stop_worker()
        self.setEnabled(False)

    # ─────────────────────────── Worker

    def _start_worker(self):
        if self._worker and self._worker.isRunning():
            return
        from core.camera_settings_worker import CameraSettingsWorker
        self._worker = CameraSettingsWorker(session_mode_init=self._session_mode_init)
        self._worker.settings_loaded.connect(self.exposure_ctrl.sync_with_camera)
        self._worker.settings_loaded.connect(self.image_ctrl.sync_with_camera)
        self._worker.settings_loaded.connect(self.focus_ctrl.sync_with_camera)
        self._worker.settings_loaded.connect(self.settings_captured)
        self._worker.status_message.connect(self.status_message)
        self.exposure_ctrl.gphoto = self._worker
        self.image_ctrl.gphoto    = self._worker
        self.focus_ctrl.gphoto    = self._worker
        self._worker.start()

    def _stop_worker(self):
        if self._worker:
            self.exposure_ctrl.gphoto = None
            self.image_ctrl.gphoto    = None
            self.focus_ctrl.gphoto    = None
            self._worker.keep_running = False
            if self._worker.isRunning():
                if not self._worker.wait(3000):
                    self._worker.terminate()
            self._worker = None

    @property
    def worker(self):
        """Aktywny worker (lub None) — potrzebny przy zatrzymywaniu widoku."""
        return self._worker
