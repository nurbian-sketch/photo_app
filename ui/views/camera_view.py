import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QSizePolicy, QDialog
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QTransform

from core.gphoto_interface import GPhotoInterface

from ui.views.camera_components.exposure_controls import ExposureControls
from ui.views.camera_components.image_controls import ImageControls
from ui.views.camera_components.autofocus_controls import AutofocusControls



RAW_EXTENSIONS = {'.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng'}


def _is_raw(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in RAW_EXTENSIONS


def _find_companion_jpg(raw_path: str) -> str | None:
    """Szuka pliku JPG o tej samej nazwie bazowej co plik RAW (RAW + L JPEG)."""
    base = os.path.splitext(raw_path)[0]
    for ext in ('.jpg', '.JPG', '.jpeg', '.JPEG'):
        candidate = base + ext
        if os.path.exists(candidate):
            return candidate
    return None


def _exiftool_extract_preview(path: str) -> str | None:
    """
    Wyciąga embedded PreviewImage z pliku RAW do temp JPEG.
    Zwraca ścieżkę do temp pliku (caller odpowiada za usunięcie) lub None.
    """
    import subprocess, tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name
        with open(tmp_path, 'wb') as out_fh:
            result = subprocess.run(
                ['exiftool', '-b', '-PreviewImage', path],
                stdout=out_fh,
                stderr=subprocess.PIPE,
                timeout=10,
            )
        if result.returncode == 0 and os.path.getsize(tmp_path) > 0:
            return tmp_path
        os.unlink(tmp_path)
    except Exception as e:
        print(f"exiftool error ({os.path.basename(path)}): {e}")
    return None


def _load_pixmap_from_path(path: str) -> QPixmap:
    """
    Ładuje pixmapę z pliku JPEG lub RAW.
    Dla RAW: companion JPG (RAW+L) → exiftool PreviewImage.
    UWAGA: wywołuj tylko z wątku roboczego — exiftool blokuje.
    """
    if not _is_raw(path):
        pix = QPixmap(path)
        return pix if not pix.isNull() else QPixmap()

    # RAW + L JPEG — companion JPG w tym samym katalogu
    jpg = _find_companion_jpg(path)
    if jpg:
        pix = QPixmap(jpg)
        if not pix.isNull():
            print(f"RAW+JPG companion: {os.path.basename(jpg)}")
            return pix

    # Embedded preview z RAW przez exiftool
    tmp_path = _exiftool_extract_preview(path)
    if tmp_path:
        pix = QPixmap(tmp_path)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        if not pix.isNull():
            print(f"RAW preview via exiftool: {os.path.basename(path)}")
            return pix

    return QPixmap()


def _read_exif(path: str) -> dict:
    """
    Czyta podstawowe dane EXIF przez piexif.
    Dla RAW: companion JPG → exiftool preview temp JPEG → fallback pusty dict.
    UWAGA: wywołuj tylko z wątku roboczego — może uruchamiać exiftool.
    """
    r = {'shutter': '', 'aperture': '', 'iso': '', 'focal': '',
         'date': '', 'dims': '', 'size': '', 'camera': '', 'orientation': 0}
    tmp_to_clean = None
    try:
        import piexif

        r['size'] = f"{os.path.getsize(path) / (1024 * 1024):.1f}\u00a0MB"

        # Źródło EXIF: companion JPG > exiftool temp > oryginał
        exif_source = path
        if _is_raw(path):
            jpg = _find_companion_jpg(path)
            if jpg:
                exif_source = jpg
            else:
                tmp_to_clean = _exiftool_extract_preview(path)
                if tmp_to_clean:
                    exif_source = tmp_to_clean

        exif = piexif.load(exif_source)
        ifd0 = exif.get('0th', {})
        exif_ifd = exif.get('Exif', {})

        # Orientation
        orientation_map = {1: 0, 3: 180, 6: 90, 8: 270}
        r['orientation'] = orientation_map.get(
            ifd0.get(piexif.ImageIFD.Orientation, 1), 0
        )

        # Dims — z danych obrazu (QImageReader nie blokuje)
        from PyQt6.QtGui import QImageReader as _QIR
        reader = _QIR(exif_source)
        sz = reader.size()
        if sz.isValid():
            r['dims'] = f"{sz.width()}\u00d7{sz.height()}"

        def frac(v):
            if isinstance(v, tuple) and len(v) == 2 and v[1]:
                return v[0], v[1]
            return int(v), 1

        exp = exif_ifd.get(piexif.ExifIFD.ExposureTime)
        if exp:
            n, d = frac(exp)
            if n and d:
                ratio = d / n
                r['shutter'] = f"1/{int(round(ratio))}s" if ratio >= 1 else f"{n / d:.1f}s"

        fn = exif_ifd.get(piexif.ExifIFD.FNumber)
        if fn:
            n, d = frac(fn)
            if d:
                r['aperture'] = f"f/{n / d:.1f}"

        iso = exif_ifd.get(piexif.ExifIFD.ISOSpeedRatings)
        if iso:
            r['iso'] = f"ISO\u00a0{iso}"

        fl = exif_ifd.get(piexif.ExifIFD.FocalLength)
        if fl:
            n, d = frac(fl)
            if d:
                r['focal'] = f"{int(round(n / d))}mm"

        dt = (exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
              or ifd0.get(piexif.ImageIFD.DateTime))
        if dt:
            s = dt.decode('ascii', errors='ignore') if isinstance(dt, bytes) else str(dt)
            r['date'] = s[:10].replace(':', '-') + ' ' + s[11:16]

        make = (ifd0.get(piexif.ImageIFD.Make) or b'').decode('ascii', errors='ignore').strip()
        model = (ifd0.get(piexif.ImageIFD.Model) or b'').decode('ascii', errors='ignore').strip()
        if model:
            r['camera'] = model if model.startswith(make) else (
                f"{make} {model}".strip() if make else model
            )

    except Exception as e:
        print(f"EXIF read error ({os.path.basename(path)}): {e}")
    finally:
        if tmp_to_clean:
            try:
                os.unlink(tmp_to_clean)
            except OSError:
                pass
    return r


# ─────────────────────────────── Async loader (nie blokuje UI)

from PyQt6.QtCore import QThread, pyqtSignal as _pyqtSignal


class _ImageLoader(QThread):
    """
    Ładuje pixmapę i EXIF w tle.
    Emituje loaded(pixmap, exif_dict) gdy gotowe.
    """
    loaded = _pyqtSignal(object, dict)   # QPixmap, dict

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        pixmap = _load_pixmap_from_path(self._path)
        exif = _read_exif(self._path)
        self.loaded.emit(pixmap, exif)

# ─────────────────────────────── Popup podglądu zdjęcia

class CapturePreviewDialog(QDialog):
    """Okno podglądu przechwyconego zdjęcia z kontrolkami zoom/pan/rotate."""

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
        if self._pixmap.isNull():
            self._label.setText(f"Cannot load image:\n{self._image_path}")
            return

        # Oblicz rozmiar obrazu po zoom
        img_w = int(self._pixmap.width() * self._zoom)
        img_h = int(self._pixmap.height() * self._zoom)

        if img_w < 1 or img_h < 1:
            return

        scaled = self._pixmap.scaled(
            img_w, img_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

        # Jeśli obraz mniejszy niż label — wycentruj
        label_size = self._label.size()
        if scaled.width() <= label_size.width() and scaled.height() <= label_size.height():
            self._pan_offset = [0, 0]
            self._label.setPixmap(scaled)
        else:
            # Przytnij do widocznego obszaru z uwzględnieniem pan
            visible_w = min(scaled.width(), label_size.width())
            visible_h = min(scaled.height(), label_size.height())

            # Ogranicz pan do granic obrazu
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
        if self._pixmap.isNull():
            return
        label_size = self._label.size()
        if label_size.width() < 10 or label_size.height() < 10:
            QTimer.singleShot(100, self._zoom_fit)
            return
        scale_w = label_size.width() / self._pixmap.width()
        scale_h = label_size.height() / self._pixmap.height()
        self._zoom = min(scale_w, scale_h, 1.0)  # Nie powiększaj ponad 100%
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

    def __init__(self, camera_service=None):
        super().__init__()
        self.cs = camera_service
        self.lv_thread = None
        self._camera_ready = False
        self._needs_reconnect = False  # Flaga: było zerwane połączenie
        self._error_stopped = False   # Flaga: wątek zatrzymany przez błąd (nie przez user)
        self._stopping = False    # Wątek w trakcie zatrzymywania
        self._reconnecting = False  # Trwa próba reconnect
        self._capture_blocked = False  # Capture zablokowany po błędzie — odblokuj na klatce
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
        """Ustawia stan gotowości aparatu — włącza/wyłącza przyciski."""
        self._camera_ready = ready

        # Nie nadpisujemy btn_lv gdy:
        # - trwa reconnect (_reconnecting)
        # - wątek jest zatrzymywany (_stopping)
        # - jest oczekujący RECONNECT (_needs_reconnect) ← NOWE: chroni pomarańczowy kolor
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

        self.exposure_ctrl.setEnabled(True)
        self.image_ctrl.setEnabled(True)
        self.focus_ctrl.setEnabled(True)
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
        self.btn_cap.setEnabled(False)
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
            dead_thread.finished.connect(self._on_thread_finished)
            # Safety net: force-terminate po 8s gdyby capture_preview wisiał
            QTimer.singleShot(8000, lambda: self._force_terminate(dead_thread))
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
            dead_thread.keep_running = False
            # Wyczyść kolejkę — stare capture nie mogą odpalić po restart
            dead_thread.mutex.lock()
            try:
                dead_thread.command_queue.clear()
            finally:
                dead_thread.mutex.unlock()
            QTimer.singleShot(9000, lambda: self._force_terminate(dead_thread))

    def _force_terminate(self, thread):
        """Ostateczność: terminate jeśli wątek nie zakończył się sam.
        Bez wait() — nie blokuje UI. USB może pozostać zablokowane."""
        try:
            if thread.isRunning():
                thread.terminate()
        except RuntimeError:
            pass

    def _on_thread_finished(self):
        """Wywoływane gdy user kliknął STOP i wątek zakończył run()."""
        self._stopping = False
        # Błędy obsługuje _on_lv_error — tu tylko czysty stop
        if not self._needs_reconnect:
            self.btn_lv.setText("START LIVE VIEW")
            self.btn_lv.setStyleSheet("")
            self.btn_lv.setEnabled(self._camera_ready)

    # --- CAPTURE ---

    def _on_capture_clicked(self):
        """Kolejkuje zdjęcie na wątku gphoto."""
        if self.lv_thread and self.lv_thread.isRunning():
            self.btn_cap.setEnabled(False)  # Blokada wielokrotnego kliknięcia
            self.btn_cap.setText("CAPTURING...")
            self.btn_lv.setEnabled(False)   # STOP niedostępny podczas capture — zablokuje USB
            self.update_capture_directory()
            self.lv_thread.capture_photo(self._capture_dir)

    def _on_image_captured(self, file_path):
        """Callback: zdjęcie zapisane — otwórz podgląd."""
        print(f"Image captured: {file_path}")
        self.btn_cap.setEnabled(True)
        self.btn_cap.setText("CAPTURE PHOTO")
        self.btn_lv.setEnabled(True)  # Odblokuj STOP po zakończeniu capture

        dialog = CapturePreviewDialog(
            file_path, parent=None,
            close_all_callback=self.close_all_previews
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

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
        """Obsługa błędu capture — NIE zabija sesji LV.
        Blokuje btn_cap do następnej udanej klatki (= USB stabilne)."""
        print(f"Capture failed: {error_msg}")
        self._capture_blocked = True
        self.btn_cap.setEnabled(False)
        self.btn_cap.setText("CAPTURE PHOTO")
        self.btn_lv.setEnabled(True)   # STOP dostępny nawet po błędzie capture

    # --- LEAVE / ENTER ---

    def on_leave(self):
        """Wywoływane przy opuszczeniu widoku Camera.
        Zamyka sesję PTP i resetuje UI do stanu początkowego."""
        if self.lv_thread and self.lv_thread.isRunning():
            self._stop_lv()
        # Reset UI niezależnie od stanu (np. po RECONNECT)
        self.lv_thread = None
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
        self.btn_cap.setEnabled(False)
        self.btn_lv_rotate_left.setEnabled(False)
        self.btn_lv_rotate_right.setEnabled(False)
        self._set_buttons_enabled(self._camera_ready)

    def is_lv_active(self) -> bool:
        """True gdy sesja PTP aktywna — dla MainWindow._probe_camera() fix #8."""
        return self.lv_thread is not None and self.lv_thread.isRunning()

    def close_all_previews(self):
        """Zamyka wszystkie otwarte okna podglądu zdjęć."""
        for dialog in list(self._preview_dialogs):
            try:
                dialog.close()
            except Exception:
                pass
        self._preview_dialogs.clear()

    def _on_update_clicked(self):
        """Zbiera ustawienia i wysyła (zachowano dla kompatybilności)."""
        settings = {}
        settings.update(self.exposure_ctrl.get_settings())
        settings.update(self.image_ctrl.get_settings())
        settings.update(self.focus_ctrl.get_settings())
        if self.cs:
            self.cs.apply_bulk_settings(settings)
