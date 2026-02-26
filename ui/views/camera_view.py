import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QSizePolicy, QDialog
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QPixmap, QTransform

from core.gphoto_interface import GPhotoInterface

from ui.views.camera_components.exposure_controls import ExposureControls
from ui.views.camera_components.image_controls import ImageControls
from ui.views.camera_components.autofocus_controls import AutofocusControls



from core.image_io import (
    RAW_EXTENSIONS,
    is_raw as _is_raw,
    load_pixmap_from_path as _load_pixmap_from_path,
    read_exif as _read_exif,
    ImageLoader as _ImageLoader,
)

# ─────────────────────────────── WB Worker

class _WBWorker(QThread):
    """
    Próbkuje piksel, przelicza korekcję WB i renderuje skorygowany preview.
    Działa w tle — nie blokuje UI ani LV thread.
    """
    finished = pyqtSignal(object, int)   # (QPixmap_corrected, kelvin)

    # Daylight locus: (Kelvin, R/B_ratio) — przybliżone wartości dla sRGB
    DAYLIGHT_LOCUS = [
        (2500, 3.0), (3000, 2.6), (3200, 2.3), (4000, 1.8),
        (5000, 1.4), (5200, 1.3), (5500, 1.1), (6500, 0.85),
        (7500, 0.72), (8000, 0.65), (10000, 0.50),
    ]

    def __init__(self, pixmap: QPixmap, sample_x: int, sample_y: int):
        super().__init__()
        self._pixmap = pixmap
        self._sx = sample_x
        self._sy = sample_y

    def run(self):
        try:
            import numpy as np
            from PyQt6.QtGui import QImage

            img = self._pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
            w, h = img.width(), img.height()

            ptr = img.bits()
            ptr.setsize(h * w * 3)
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 3)).copy()

            # Próbka 9×9 wokół klikniętego piksela
            r = 4
            x0 = max(0, self._sx - r);  x1 = min(w, self._sx + r + 1)
            y0 = max(0, self._sy - r);  y1 = min(h, self._sy + r + 1)
            sample = arr[y0:y1, x0:x1].astype(np.float32)

            avg_r = float(np.mean(sample[:, :, 0]))
            avg_g = float(np.mean(sample[:, :, 1]))
            avg_b = float(np.mean(sample[:, :, 2]))

            if avg_r < 1 or avg_g < 1 or avg_b < 1:
                self.finished.emit(self._pixmap, 5500)
                return

            # Mnożniki: chcemy R=G=B (neutralny)
            mult_r = avg_g / avg_r
            mult_b = avg_g / avg_b

            corrected = arr.astype(np.float32)
            corrected[:, :, 0] *= mult_r
            corrected[:, :, 2] *= mult_b
            np.clip(corrected, 0, 255, out=corrected)
            corrected_u8 = corrected.astype(np.uint8)

            result_img = QImage(
                corrected_u8.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888
            )
            result_pixmap = QPixmap.fromImage(result_img)

            kelvin = self._estimate_kelvin(avg_r / avg_b if avg_b > 1 else 1.0)
            self.finished.emit(result_pixmap, kelvin)

        except Exception as e:
            print(f"WBWorker error: {e}")
            self.finished.emit(self._pixmap, 5500)

    def _estimate_kelvin(self, rb_ratio: float) -> int:
        locus = self.DAYLIGHT_LOCUS
        if rb_ratio >= locus[0][1]:
            return locus[0][0]
        if rb_ratio <= locus[-1][1]:
            return locus[-1][0]
        for i in range(len(locus) - 1):
            k1, r1 = locus[i]
            k2, r2 = locus[i + 1]
            if r2 <= rb_ratio <= r1:
                t = (rb_ratio - r2) / (r1 - r2)
                return int(round(k2 + t * (k1 - k2)))
        return 5500





# ─────────────────────────────── Popup podglądu zdjęcia

class CapturePreviewDialog(QDialog):
    """Okno podglądu przechwyconego zdjęcia z kontrolkami zoom/pan/rotate."""

    wb_applied = pyqtSignal(int)   # Kelviny — dla image_controls.apply_wb_temperature

    def __init__(self, image_path, parent=None, close_all_callback=None):
        super().__init__(parent)
        self._close_all_callback = close_all_callback
        self.setWindowTitle(os.path.basename(image_path))
        self.setMinimumSize(640, 480)
        self.resize(1024, 768)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )

        # Ciemny motyw jak main window (#3d3d3d)
        self.setStyleSheet("""
            QDialog { background-color: #3d3d3d; }
            QLabel { color: #ccc; }
        """)

        self._image_path = image_path
        self._original_pixmap = QPixmap()  # placeholder — wypełni _ImageLoader
        self._pixmap = QPixmap()
        self._rotation = 0
        self._zoom = 1.0
        self._pan_offset = [0, 0]
        self._drag_start = None
        self._saved_geometry = None

        # WB picker state
        self._wb_mode = False
        self._wb_pixmap = None    # Skorygowany pixmap (visual preview)
        self._wb_kelvin = None    # Oszacowana temperatura
        self._wb_worker = None

        self._init_ui()

        # Ładuj pixmapę i EXIF w tle — nie blokuj UI thread
        self._loader = _ImageLoader(image_path)
        self._loader.loaded.connect(self._on_image_loaded)
        self._loader.start()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Image label - tło takie samo jak okno
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: #3d3d3d;")
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._label.setMouseTracking(True)
        layout.addWidget(self._label)

        # Control bar - ten sam kolor co tło
        control_bar = QWidget()
        control_bar.setStyleSheet("background: #3d3d3d;")
        control_layout = QHBoxLayout(control_bar)
        control_layout.setContentsMargins(10, 5, 10, 5)
        control_layout.setSpacing(8)

        # Rotation controls
        btn_rotate_left = QPushButton("↶")
        btn_rotate_left.setFixedSize(32, 32)
        btn_rotate_left.setToolTip("Rotate left 90°")
        btn_rotate_left.setStyleSheet("font-size: 16px;")
        btn_rotate_left.clicked.connect(self._rotate_left)
        control_layout.addWidget(btn_rotate_left)

        btn_rotate_right = QPushButton("↷")
        btn_rotate_right.setFixedSize(32, 32)
        btn_rotate_right.setToolTip("Rotate right 90°")
        btn_rotate_right.setStyleSheet("font-size: 16px;")
        btn_rotate_right.clicked.connect(self._rotate_right)
        control_layout.addWidget(btn_rotate_right)

        # Separator
        sep = QLabel("|")
        sep.setStyleSheet("color: #555;")
        control_layout.addWidget(sep)

        # Zoom controls
        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedSize(32, 32)
        btn_zoom_out.setStyleSheet("font-size: 18px; font-weight: bold;")
        btn_zoom_out.clicked.connect(self._zoom_out)
        control_layout.addWidget(btn_zoom_out)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setFixedWidth(50)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet("color: #888;")
        control_layout.addWidget(self._zoom_label)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedSize(32, 32)
        btn_zoom_in.setStyleSheet("font-size: 18px; font-weight: bold;")
        btn_zoom_in.clicked.connect(self._zoom_in)
        control_layout.addWidget(btn_zoom_in)

        btn_fit = QPushButton("Fit")
        btn_fit.setFixedSize(50, 32)
        btn_fit.clicked.connect(self._zoom_fit)
        control_layout.addWidget(btn_fit)

        btn_100 = QPushButton("1:1")
        btn_100.setFixedSize(50, 32)
        btn_100.clicked.connect(self._zoom_100)
        control_layout.addWidget(btn_100)

        # WB Picker separator + controls
        sep_wb = QLabel("|")
        sep_wb.setStyleSheet("color: #555;")
        control_layout.addWidget(sep_wb)

        self.btn_wb = QPushButton("Pick WB")
        self.btn_wb.setFixedSize(80, 32)
        self.btn_wb.setCheckable(True)
        self.btn_wb.setToolTip(
            "Click on a neutral white/grey area to pick white balance"
        )
        control_layout.addWidget(self.btn_wb)

        self._wb_label = QLabel("")
        self._wb_label.setFixedWidth(64)
        self._wb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._wb_label.setStyleSheet("color: #888; font-size: 11px;")
        control_layout.addWidget(self._wb_label)

        self.btn_wb_accept = QPushButton("Apply")
        self.btn_wb_accept.setFixedSize(60, 32)
        self.btn_wb_accept.setVisible(False)
        control_layout.addWidget(self.btn_wb_accept)

        self.btn_wb_cancel = QPushButton("Cancel")
        self.btn_wb_cancel.setFixedSize(60, 32)
        self.btn_wb_cancel.setVisible(False)
        control_layout.addWidget(self.btn_wb_cancel)

        # Spacer
        control_layout.addStretch()

        # File path
        path_label = QLabel(self._image_path)
        path_label.setStyleSheet("color: #555; font-size: 11px;")
        control_layout.addWidget(path_label)

        control_layout.addStretch()

        # Close All button (tylko gdy callback dostępny)
        if self._close_all_callback:
            btn_close_all = QPushButton("Close All")
            btn_close_all.setFixedSize(90, 32)
            btn_close_all.setStyleSheet(
                "background-color: #c62828; color: white; font-weight: bold;"
            )
            btn_close_all.clicked.connect(self._close_all_callback)
            control_layout.addWidget(btn_close_all)

        # Close button
        btn_close = QPushButton("Close")
        btn_close.setFixedSize(80, 32)
        btn_close.clicked.connect(self.close)
        control_layout.addWidget(btn_close)

        # EXIF bar — wypełniany async przez _on_image_loaded
        self._exif_bar = QLabel("Loading…")
        self._exif_bar.setStyleSheet(
            "background: #222; color: #999; font-size: 11px; padding: 3px 10px;"
        )
        self._exif_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._exif_bar)

        layout.addWidget(control_bar)

        # WB picker — obsługa kliknięcia na label
        self.btn_wb.clicked.connect(self._toggle_wb_mode)
        self.btn_wb_accept.clicked.connect(self._accept_wb)
        self.btn_wb_cancel.clicked.connect(self._cancel_wb)
        self._label.installEventFilter(self)

    # ─────────────────────────────── WB PICKER

    def _get_display_pixmap(self) -> QPixmap:
        """Zwraca pixmapę do wyświetlenia: WB preview lub oryginał."""
        if self._wb_pixmap and not self._wb_pixmap.isNull():
            return self._wb_pixmap
        return self._pixmap

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self._label and self._wb_mode:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._on_wb_pick(event.pos())
                    return True
        return super().eventFilter(obj, event)

    def _toggle_wb_mode(self, checked):
        self._wb_mode = checked
        if checked:
            self._label.setCursor(Qt.CursorShape.CrossCursor)
            self._wb_label.setText("Click neutral")
        else:
            self._cancel_wb()

    def _label_pos_to_pixmap_pos(self, label_pos) -> tuple[int, int] | None:
        """Mapuje kliknięcie w QLabel na współrzędne piksela w self._pixmap."""
        pix = self._get_display_pixmap()
        if pix.isNull():
            return None
        lw = self._label.width()
        lh = self._label.height()
        pw = pix.width()
        ph = pix.height()
        img_w = int(pw * self._zoom)
        img_h = int(ph * self._zoom)
        cx = label_pos.x()
        cy = label_pos.y()
        if img_w <= lw and img_h <= lh:
            # Obraz mieści się w label — jest wycentrowany przez AlignCenter
            off_x = (lw - img_w) // 2
            off_y = (lh - img_h) // 2
            px = (cx - off_x) / self._zoom
            py = (cy - off_y) / self._zoom
        else:
            # Obraz większy niż label — widoczny fragment od pan_offset
            px = (cx + self._pan_offset[0]) / self._zoom
            py = (cy + self._pan_offset[1]) / self._zoom
        return (
            int(max(0, min(px, pw - 1))),
            int(max(0, min(py, ph - 1))),
        )

    def _on_wb_pick(self, label_pos):
        pos = self._label_pos_to_pixmap_pos(label_pos)
        if pos is None:
            return
        if self._wb_worker and self._wb_worker.isRunning():
            return   # Poprzednie obliczenie jeszcze trwa
        self._wb_label.setText("…")
        self._wb_worker = _WBWorker(self._pixmap, pos[0], pos[1])
        self._wb_worker.finished.connect(self._on_wb_computed)
        self._wb_worker.start()

    def _on_wb_computed(self, corrected_pixmap: QPixmap, kelvin: int):
        self._wb_pixmap = corrected_pixmap
        snapped = max(2500, min(10000, round(kelvin / 100) * 100))
        self._wb_kelvin = snapped
        self._wb_label.setText(f"{snapped} K")
        self.btn_wb_accept.setVisible(True)
        self.btn_wb_cancel.setVisible(True)

        # Kursor półpełny — kolor próbki w bulwie
        from PyQt6.QtGui import QColor
        sample_color = QColor("#b0c8e8")  # neutralny błękit jako placeholder
        self._label.setCursor(Qt.CursorShape.CrossCursor)

        self._update_preview()

    def _accept_wb(self):
        if self._wb_kelvin is not None:
            self.wb_applied.emit(self._wb_kelvin)
        self._cancel_wb()

    def _cancel_wb(self):
        self._wb_mode = False
        self._wb_pixmap = None
        self._wb_kelvin = None
        self.btn_wb.setChecked(False)
        self.btn_wb.setStyleSheet("")
        self.btn_wb_accept.setVisible(False)
        self.btn_wb_cancel.setVisible(False)
        self._wb_label.setText("")
        self._label.unsetCursor()
        self._update_preview()

    # ─────────────────────────────── ROTATE

    def _rotate_left(self):
        """Obrót o -90°."""
        self._rotation = (self._rotation - 90) % 360
        self._apply_rotation()

    def _rotate_right(self):
        """Obrót o +90°."""
        self._rotation = (self._rotation + 90) % 360
        self._apply_rotation()

    def _apply_rotation(self):
        """Aplikuje rotację do pixmapy."""
        from PyQt6.QtGui import QTransform
        transform = QTransform().rotate(self._rotation)
        self._pixmap = self._original_pixmap.transformed(
            transform, Qt.TransformationMode.SmoothTransformation
        )
        self._pan_offset = [0, 0]
        self._zoom_fit()

    def _on_image_loaded(self, pixmap: QPixmap, exif: dict):
        """Callback z _ImageLoader — aktualizuje UI po załadowaniu w tle."""
        self._original_pixmap = pixmap
        self._rotation = exif.get('orientation', 0)

        if self._rotation != 0:
            self._pixmap = pixmap.transformed(
                QTransform().rotate(self._rotation),
                Qt.TransformationMode.SmoothTransformation
            )
        else:
            self._pixmap = pixmap

        # Aktualizuj EXIF bar
        parts = [v for v in [
            exif.get('camera', ''), exif.get('dims', ''), exif.get('size', ''),
            exif.get('shutter', ''), exif.get('aperture', ''), exif.get('iso', ''),
            exif.get('focal', ''), exif.get('date', '')
        ] if v]
        self._exif_bar.setText("   •   ".join(parts) if parts else "No EXIF data")

        self._zoom_fit()

    def keyPressEvent(self, event):
        """Obsługa F11 fullscreen i Escape."""
        if event.key() == Qt.Key.Key_F11:
            self._toggle_fullscreen()
        elif event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self._toggle_fullscreen()
            else:
                self.close()
        elif event.key() == Qt.Key.Key_Left:
            self._rotate_left()
        elif event.key() == Qt.Key.Key_Right:
            self._rotate_right()
        else:
            super().keyPressEvent(event)

    def _toggle_fullscreen(self):
        """Przełącza tryb pełnoekranowy."""
        if self.isFullScreen():
            self.showNormal()
            if self._saved_geometry:
                self.setGeometry(self._saved_geometry)
        else:
            self._saved_geometry = self.geometry()
            self.showFullScreen()
        QTimer.singleShot(50, self._zoom_fit)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self._zoom_fit)

    def _update_preview(self):
        pixmap = self._get_display_pixmap()
        if pixmap.isNull():
            self._label.setText(f"Cannot load image:\n{self._image_path}")
            return

        img_w = int(pixmap.width() * self._zoom)
        img_h = int(pixmap.height() * self._zoom)

        if img_w < 1 or img_h < 1:
            return

        scaled = pixmap.scaled(
            img_w, img_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        label_size = self._label.size()
        if scaled.width() <= label_size.width() and scaled.height() <= label_size.height():
            self._pan_offset = [0, 0]
            self._label.setPixmap(scaled)
        else:
            visible_w = min(scaled.width(), label_size.width())
            visible_h = min(scaled.height(), label_size.height())
            max_pan_x = max(0, scaled.width() - label_size.width())
            max_pan_y = max(0, scaled.height() - label_size.height())
            self._pan_offset[0] = max(0, min(self._pan_offset[0], max_pan_x))
            self._pan_offset[1] = max(0, min(self._pan_offset[1], max_pan_y))
            cropped = scaled.copy(
                int(self._pan_offset[0]), int(self._pan_offset[1]),
                visible_w, visible_h
            )
            self._label.setPixmap(cropped)

        self._zoom_label.setText(f"{int(self._zoom * 100)}%")

    def _zoom_in(self):
        self._zoom = min(self._zoom * 1.25, 10.0)
        self._update_preview()

    def _zoom_out(self):
        self._zoom = max(self._zoom / 1.25, 0.1)
        self._update_preview()

    def _zoom_fit(self):
        pixmap = self._get_display_pixmap()
        if pixmap.isNull():
            return
        label_size = self._label.size()
        if label_size.width() < 10 or label_size.height() < 10:
            QTimer.singleShot(100, self._zoom_fit)
            return
        scale_w = label_size.width() / pixmap.width()
        scale_h = label_size.height() / pixmap.height()
        self._zoom = min(scale_w, scale_h, 1.0)
        self._pan_offset = [0, 0]
        self._update_preview()

    def _zoom_100(self):
        self._zoom = 1.0
        self._pan_offset = [0, 0]
        self._update_preview()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._update_preview()

    def wheelEvent(self, event):
        """Zoom kółkiem myszy."""
        delta = event.angleDelta().y()
        if delta > 0:
            self._zoom_in()
        elif delta < 0:
            self._zoom_out()

    def mousePressEvent(self, event):
        """Rozpocznij pan."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()

    def mouseMoveEvent(self, event):
        """Pan podczas przeciągania."""
        if self._drag_start is not None:
            delta = event.pos() - self._drag_start
            self._pan_offset[0] -= delta.x()
            self._pan_offset[1] -= delta.y()
            self._drag_start = event.pos()
            self._update_preview()

    def mouseReleaseEvent(self, event):
        """Zakończ pan."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None


# ─────────────────────────────── Widok kamery

# ─────────────────────────────── Profile Browser

from ui.dialogs.profile_browser_dialog import ProfileBrowserDialog

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
        # (brak timera reconnect — probe callback bezpośrednio wywołuje on_probe_completed)
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
        self.btn_lv_rotate_left.clicked.connect(self._rotate_lv_ccw)
        self.btn_lv_rotate_right.clicked.connect(self._rotate_lv_cw)
        self.btn_save.clicked.connect(self._on_save_profile)
        self.btn_load.clicked.connect(self._on_load_profile)

        # Wszystkie przyciski wyłączone do momentu wykrycia aparatu
        self._set_buttons_enabled(False)

    # ─────────────────────────────── FRAME UPDATE

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
                from PyQt6.QtGui import QTransform
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
            if is_blinking:
                self.lv_screen.setStyleSheet(
                    "background: #3d3d3d; border: 2px solid #ff8a65;"
                )
            else:
                self.lv_screen.setStyleSheet(
                    "background: #3d3d3d; border: 2px solid #555;"
                )

    # --- CAMERA READY STATE ---

    # Style stałych stanów przycisku btn_lv
    BTN_STYLE_STOP = "background-color: #c62828; color: white; font-weight: bold;"

    def set_camera_ready(self, ready):
        """Ustawia stan gotowości aparatu — włącza/wyłącza przyciski i kontrolki."""
        self._camera_ready = ready

        # Nie zmieniaj kontrolek gdy USB nadal zajęte przez umierający wątek
        # lub gdy trwa zatrzymywanie — stan ustabilizuje się w _on_thread_finished
        usb_busy = (
            self._stopping
            or (self._dead_thread is not None and self._dead_thread.isRunning())
        )
        if not usb_busy:
            self.exposure_ctrl.setEnabled(ready)
            self.image_ctrl.setEnabled(ready)
            self.focus_ctrl.setEnabled(ready)

        # Nie nadpisujemy btn_lv gdy:
        # - trwa reconnect (_reconnecting)
        # - wątek jest zatrzymywany (_stopping)
        # - jest oczekujący RECONNECT (_needs_reconnect) ← chroni pomarańczowy kolor
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
        Uwaga: btn_lv jest zawsze aktywny (CONNECT/START/STOP/RECONNECT)."""
        # btn_lv NIE jest tutaj — zarządzany osobno w set_camera_ready()
        self.btn_cap.setEnabled(enabled and self.lv_thread is not None
                                and self.lv_thread.isRunning())
        self.btn_save.setEnabled(enabled)
        self.btn_update.setEnabled(enabled)

    # --- LIVE VIEW & GPHOTO LOGIC ---

    def _toggle_liveview(self):
        """Przełącza stan wątku interfejsu gphoto.
        RECONNECT = probe + auto-start LV."""
        if self.lv_thread and self.lv_thread.isRunning():
            # LV aktywne → zatrzymaj
            self._stop_lv()
        elif self._needs_reconnect:
            # Zerwane połączenie → probe i jeśli OK to od razu start LV
            # NIE resetuj _needs_reconnect tutaj — resetuje go _auto_start_after_reconnect przy sukcesie
            self._try_reconnect()
        elif not self._camera_ready:
            # Brak aparatu → tylko probe (bez auto-start)
            self.reconnect_requested.emit()
        else:
            # Aparat gotowy → uruchom LV
            self._start_lv()

    def _try_reconnect(self):
        """Próbuje reconnect: probe + auto-start LV.
        Wynik probe dostarczy on_probe_completed() — bez timera, bez race condition."""
        self._reconnecting = True
        self.btn_lv.setEnabled(False)
        self.btn_lv.setText("Connecting...")
        self.status_message.emit("Reconnecting camera...", 0)
        self.reconnect_requested.emit()  # → _probe_camera → _on_probe_done → on_probe_completed

    def on_probe_completed(self, camera_ready: bool):
        """Wywołane przez main_window po zakończeniu probe (gdy _reconnecting=True).
        Zastępuje timer-based _auto_start_after_reconnect — bez race condition."""
        if not self._reconnecting:
            return  # probe był z innego powodu (change_view), nie z reconnect
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
        self.btn_lv.setEnabled(False)  # Blokada wielokrotnego kliknięcia
        self._error_stopped = False  # Start fresh — nie jesteśmy już w stanie błędu

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

        # Kontrolki już aktywne (set_camera_ready) — tylko podpinamy gphoto
        self.btn_lv.setEnabled(True)  # Teraz działa jako STOP
        self.btn_cap.setEnabled(True)  # Capture dostępny podczas LV
        self.btn_lv_rotate_left.setEnabled(True)
        self.btn_lv_rotate_right.setEnabled(True)
        self.btn_lv.setText("STOP LIVE VIEW")
        self.btn_lv.setStyleSheet(self.BTN_STYLE_STOP)

    def _stop_lv(self):
        """Zatrzymuje wątek. keep_running=False → run() kończy się naturalnie
        → _safe_camera_exit() zwalnia USB → finished emitowany → START aktywny."""
        self._error_stopped = False  # User-initiated stop — nie pokazuj RECONNECT
        self._capture_blocked = False
        dead_thread = self.lv_thread
        self.lv_thread = None
        # Kontrolki pozostają aktywne — aparat nadal podłączony, LV tylko off
        # gphoto = None → zmiany UI nie trafiają do aparatu (flush_pending je odrzuci)
        self.exposure_ctrl.gphoto = None
        self.image_ctrl.gphoto = None
        self.focus_ctrl.gphoto = None
        self.lv_screen.clear()
        self.lv_screen.setText("LIVE VIEW OFF")
        self.lv_screen.setStyleSheet(
            "background: #3d3d3d; border: 2px solid #555; color: white;"
        )
        self.btn_cap.setEnabled(False)
        self.btn_cap.setText("CAPTURE PHOTO")  # reset jeśli utknął na "CAPTURING..."
        self._capture_timer.stop()
        self.btn_lv_rotate_left.setEnabled(False)
        self.btn_lv_rotate_right.setEnabled(False)
        self.btn_lv.setEnabled(False)
        self.btn_lv.setText("Stopping...")

        if dead_thread:
            self._stopping = True
            dead_thread.keep_running = False
            # Wyczyść kolejkę — stare capture/update nie mogą palić po restart
            dead_thread.mutex.lock()
            try:
                dead_thread.command_queue.clear()
            finally:
                dead_thread.mutex.unlock()
            try:
                # Rozłącz niebezpieczne sygnały — NIE rozłączaj image_captured!
                # Qt queued connections: disconnect() kasuje kolejkowane ale niedostarczone zdarzenia.
                # image_captured musi przeżyć żeby podgląd otworzył się nawet po _stop_lv / _on_lv_error.
                dead_thread.frame_received.disconnect()
            except RuntimeError:
                pass
            try:
                dead_thread.settings_loaded.disconnect()
            except RuntimeError:
                pass
            try:
                dead_thread.error_occurred.disconnect()
            except RuntimeError:
                pass
            try:
                dead_thread.capture_failed.disconnect()
            except RuntimeError:
                pass
            # Guard: jeśli wątek zakończył run() zanim dotarliśmy do connect(),
            # sygnał finished już poleciał — wywołujemy callback ręcznie.
            if dead_thread.isRunning():
                dead_thread.finished.connect(self._on_thread_finished)
                # Safety net: force-terminate po 4s gdyby capture_preview wisiał
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

        # Rozłącz niebezpieczne sygnały — NIE rozłączaj image_captured!
        # Jeśli capture był w toku i image_captured jest kolejkowane, musi dotrzeć do UI.
        if dead_thread:
            try:
                # Rozłącz niebezpieczne sygnały — NIE rozłączaj image_captured!
                # Qt queued connections: disconnect() kasuje kolejkowane ale niedostarczone zdarzenia.
                # image_captured musi przeżyć żeby podgląd otworzył się nawet po _stop_lv / _on_lv_error.
                dead_thread.frame_received.disconnect()
            except RuntimeError:
                pass
            try:
                dead_thread.settings_loaded.disconnect()
            except RuntimeError:
                pass
            try:
                dead_thread.error_occurred.disconnect()
            except RuntimeError:
                pass
            try:
                dead_thread.capture_failed.disconnect()
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
        self._camera_ready = False  # USB zgubiony — nie startuj LV ze starym stanem
        self.btn_lv.setText("RECONNECT")
        self.btn_lv.setEnabled(True)
        self.btn_lv.setStyleSheet("")

        # Wątek sam skończy run() w tle — już odcięty od UI
        if dead_thread and dead_thread.isRunning():
            self._dead_thread = dead_thread   # blokuje probe'y przez is_lv_active()
            dead_thread.keep_running = False
            # Wyczyść kolejkę — stare capture nie mogą odpalić po restart
            dead_thread.mutex.lock()
            try:
                dead_thread.command_queue.clear()
            finally:
                dead_thread.mutex.unlock()
            dead_thread.finished.connect(self._on_dead_thread_finished)
            QTimer.singleShot(4000, lambda: self._force_terminate(dead_thread))

    def _force_terminate(self, thread):
        """Ostateczność: terminate jeśli wątek nie zakończył się sam.
        Bez wait() — nie blokuje UI. USB może pozostać zablokowane."""
        try:
            if thread.isRunning():
                thread.terminate()
        except RuntimeError:
            pass

    def _on_dead_thread_finished(self):
        """Wywoływane gdy umierający wątek (po _on_lv_error) zwolnił USB."""
        self._dead_thread = None

    def _on_thread_finished(self):
        """Wywoływane gdy user kliknął STOP i wątek zakończył run()."""
        self._stopping = False
        # Błędy obsługuje _on_lv_error — tu tylko czysty stop
        if not self._needs_reconnect:
            self.btn_lv.setText("START LIVE VIEW")
            self.btn_lv.setStyleSheet("")
            self.btn_lv.setEnabled(self._camera_ready)

    # --- CAPTURE ---

    def _on_capture_tick(self):
        """Timer — aktualizuje tekst przycisku co sekundę podczas capture."""
        self._capture_secs += 1
        self.btn_cap.setText(f"CAPTURING... {self._capture_secs}s")

    def _on_capture_clicked(self):
        """Kolejkuje zdjęcie na wątku gphoto."""
        if self.lv_thread and self.lv_thread.isRunning():
            self.btn_cap.setEnabled(False)  # Blokada wielokrotnego kliknięcia
            self.btn_cap.setText("CAPTURING... 0s")
            self.btn_lv.setEnabled(False)   # STOP niedostępny podczas capture — zablokuje USB
            self._capture_secs = 0
            self._capture_timer.start()
            self.update_capture_directory()
            self.lv_thread.capture_photo(self._capture_dir)

    def _on_image_captured(self, file_path):
        """Callback: zdjęcie zapisane — otwórz podgląd."""
        print(f"Image captured: {file_path}")
        self._capture_timer.stop()
        self.btn_cap.setText("CAPTURE PHOTO")
        # GUARD: sygnał jest queued — może dotrzeć po on_leave() które ustawiło lv_thread=None
        # Jeśli LV już nie żyje — nie włączaj przycisku capture
        lv_alive = self.lv_thread is not None and self.lv_thread.isRunning()
        self.btn_cap.setEnabled(lv_alive)
        self.btn_lv.setEnabled(lv_alive)  # Odblokuj STOP tylko gdy LV aktywne

        dialog = CapturePreviewDialog(
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

    # --- LEAVE / ENTER ---

    def on_leave(self):
        """Wywoływane przy opuszczeniu widoku Camera.
        Zamyka sesję PTP i resetuje UI do stanu początkowego."""
        if self.lv_thread and self.lv_thread.isRunning():
            self._stop_lv()
        # Reset UI niezależnie od stanu (np. po RECONNECT)
        self.lv_thread = None
        self._dead_thread = None
        self._needs_reconnect = False  # Reset flag przy opuszczeniu widoku
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
        """True gdy sesja PTP aktywna LUB gdy umierający wątek nadal trzyma USB."""
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

    # ─────────────────────────────── CAMERA PROFILES

    def _profiles_dir(self) -> str:
        """Zwraca sciezke do katalogu camera_profiles/ w katalogu projektu."""
        project_dir = os.path.dirname(os.path.abspath(__file__))
        # Cofamy sie z ui/views/ do katalogu glownego projektu
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
        """Zapisuje bieżące ustawienia aparatu do pliku JSON w camera_profiles/."""
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        import json

        name, ok = QInputDialog.getText(
            self, "Save Camera Profile", "Profile name:"
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        # Sanitize — zostaw tylko bezpieczne znaki
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
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"name": safe, "settings": settings}, f, indent=2)
            self.status_message.emit(f"Profile saved: {safe}", 3000)
            print(f"Profile saved: {path}")
        except Exception as e:
            QMessageBox.warning(self, "Save Profile", f"Error saving profile:\n{e}")

    def _on_load_profile(self):
        """Otwiera przeglądarkę profili w camera_profiles/."""
        dialog = ProfileBrowserDialog(self._profiles_dir(), parent=self)
        dialog.profile_selected.connect(self._apply_profile)
        dialog.exec()

    def _apply_profile(self, settings: dict):
        """Aplikuje ustawienia z profilu do UI i aparatu."""
        import json

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

        # Image + AF — przez istniejące metody
        img_keys = ('picturestyle', 'imageformat', 'alomode',
                    'whitebalance', 'colortemperature')
        af_keys  = ('focusmode', 'afmethod', 'continuousaf')

        img_s = {k: v for k, v in settings.items() if k in img_keys}
        af_s  = {k: v for k, v in settings.items() if k in af_keys}

        if img_s:
            # Budujemy pseudo-sync dict dla image_ctrl
            pseudo = {k: {"current": v, "choices": []} for k, v in img_s.items()}
            # colortemperature — slider potrzebuje samej wartości
            if 'colortemperature' in img_s:
                self.image_ctrl.ct_slider.set_value(str(img_s['colortemperature']))
                pseudo.pop('colortemperature', None)
            # Bezpośrednie ustawienie combosów (blockSignals — nie wysyłamy podwójnie)
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
