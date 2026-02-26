"""
ui/widgets/photo_preview_dialog.py

Współdzielone okno podglądu zdjęcia z kontrolkami zoom/pan/rotate/WB picker.
Używane przez CameraView (podgląd po capture) i DarkroomView (inspekcja + WB).

Sygnały:
    wb_applied(int kelvin) — użytkownik zaakceptował WB picker → temperatura w Kelwinach
"""
import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QTransform

from core.image_io import ImageLoader


# ─────────────────────────────── WB Worker

class _WBWorker(QThread):
    """
    Próbkuje piksel, przelicza korekcję WB i renderuje skorygowany preview.
    Działa w tle — nie blokuje UI ani wątku LV.
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


# ─────────────────────────────── Dialog podglądu zdjęcia

class PhotoPreviewDialog(QDialog):
    """
    Okno podglądu zdjęcia z zoom/pan/rotate i WB picker.

    Sygnały:
        wb_applied(int) — zaakceptowana temperatura WB w Kelwinach
    """

    wb_applied = pyqtSignal(int)

    def __init__(self, image_path: str, parent=None, close_all_callback=None):
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
        self.setStyleSheet("""
            QDialog { background-color: #3d3d3d; }
            QLabel  { color: #ccc; }
        """)

        self._image_path = image_path
        self._original_pixmap = QPixmap()
        self._pixmap = QPixmap()
        self._rotation = 0
        self._zoom = 1.0
        self._pan_offset = [0, 0]
        self._drag_start = None
        self._saved_geometry = None

        # Stan WB picker
        self._wb_mode = False
        self._wb_pixmap = None
        self._wb_kelvin = None
        self._wb_worker = None

        self._init_ui()

        # Ładuj asynchronicznie
        self._loader = ImageLoader(image_path)
        self._loader.loaded.connect(self._on_image_loaded)
        self._loader.start()

    # ─────────────────────────────── UI

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Obszar obrazu
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: #3d3d3d;")
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._label.setMouseTracking(True)
        layout.addWidget(self._label)

        # Pasek EXIF
        self._exif_bar = QLabel("Loading…")
        self._exif_bar.setStyleSheet(
            "background: #222; color: #999; font-size: 11px; padding: 3px 10px;"
        )
        self._exif_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._exif_bar)

        # Pasek sterowania
        control_bar = QWidget()
        control_bar.setStyleSheet("background: #3d3d3d;")
        control_layout = QHBoxLayout(control_bar)
        control_layout.setContentsMargins(10, 5, 10, 5)
        control_layout.setSpacing(8)

        # Rotacja
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

        sep1 = QLabel("|")
        sep1.setStyleSheet("color: #555;")
        control_layout.addWidget(sep1)

        # Zoom
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

        sep2 = QLabel("|")
        sep2.setStyleSheet("color: #555;")
        control_layout.addWidget(sep2)

        # WB Picker
        self.btn_wb = QPushButton("Pick WB")
        self.btn_wb.setFixedSize(80, 32)
        self.btn_wb.setCheckable(True)
        self.btn_wb.setToolTip("Click on a neutral white/grey area to pick white balance")
        self.btn_wb.clicked.connect(self._toggle_wb_mode)
        control_layout.addWidget(self.btn_wb)

        self._wb_label = QLabel("")
        self._wb_label.setFixedWidth(64)
        self._wb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._wb_label.setStyleSheet("color: #888; font-size: 11px;")
        control_layout.addWidget(self._wb_label)

        self.btn_wb_accept = QPushButton("Apply")
        self.btn_wb_accept.setFixedSize(60, 32)
        self.btn_wb_accept.setVisible(False)
        self.btn_wb_accept.clicked.connect(self._accept_wb)
        control_layout.addWidget(self.btn_wb_accept)

        self.btn_wb_cancel = QPushButton("Cancel")
        self.btn_wb_cancel.setFixedSize(60, 32)
        self.btn_wb_cancel.setVisible(False)
        self.btn_wb_cancel.clicked.connect(self._cancel_wb)
        control_layout.addWidget(self.btn_wb_cancel)

        control_layout.addStretch()

        # Ścieżka pliku
        path_label = QLabel(self._image_path)
        path_label.setStyleSheet("color: #555; font-size: 11px;")
        control_layout.addWidget(path_label)

        control_layout.addStretch()

        # Close All (opcjonalny)
        if self._close_all_callback:
            btn_close_all = QPushButton("Close All")
            btn_close_all.setFixedSize(90, 32)
            btn_close_all.setStyleSheet(
                "background-color: #c62828; color: white; font-weight: bold;"
            )
            btn_close_all.clicked.connect(self._close_all_callback)
            control_layout.addWidget(btn_close_all)

        btn_close = QPushButton("Close")
        btn_close.setFixedSize(80, 32)
        btn_close.clicked.connect(self.close)
        control_layout.addWidget(btn_close)

        layout.addWidget(control_bar)

        # Obsługa kliknięcia na obraz (WB picker)
        self._label.installEventFilter(self)

    # ─────────────────────────────── Ładowanie obrazu

    def _on_image_loaded(self, pixmap: QPixmap, exif: dict):
        """Callback z ImageLoader — aktualizuje UI po załadowaniu w tle."""
        self._original_pixmap = pixmap
        self._rotation = exif.get('orientation', 0)

        if self._rotation != 0:
            self._pixmap = pixmap.transformed(
                QTransform().rotate(self._rotation),
                Qt.TransformationMode.SmoothTransformation
            )
        else:
            self._pixmap = pixmap

        parts = [v for v in [
            exif.get('camera', ''), exif.get('dims', ''), exif.get('size', ''),
            exif.get('shutter', ''), exif.get('aperture', ''), exif.get('iso', ''),
            exif.get('focal', ''), exif.get('date', '')
        ] if v]
        self._exif_bar.setText("   •   ".join(parts) if parts else "No EXIF data")

        self._zoom_fit()

    # ─────────────────────────────── WB Picker

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
        """Mapuje kliknięcie w QLabel na współrzędne piksela w pixmapie."""
        pix = self._get_display_pixmap()
        if pix.isNull():
            return None
        lw, lh = self._label.width(), self._label.height()
        pw, ph = pix.width(), pix.height()
        img_w = int(pw * self._zoom)
        img_h = int(ph * self._zoom)
        cx, cy = label_pos.x(), label_pos.y()
        if img_w <= lw and img_h <= lh:
            off_x = (lw - img_w) // 2
            off_y = (lh - img_h) // 2
            px = (cx - off_x) / self._zoom
            py = (cy - off_y) / self._zoom
        else:
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
            return
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
        self._update_display()

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
        self._update_display()

    # ─────────────────────────────── Rotacja

    def _rotate_left(self):
        self._rotation = (self._rotation - 90) % 360
        self._apply_rotation()

    def _rotate_right(self):
        self._rotation = (self._rotation + 90) % 360
        self._apply_rotation()

    def _apply_rotation(self):
        transform = QTransform().rotate(self._rotation)
        self._pixmap = self._original_pixmap.transformed(
            transform, Qt.TransformationMode.SmoothTransformation
        )
        self._pan_offset = [0, 0]
        self._zoom_fit()

    # ─────────────────────────────── Zoom / Pan

    def _update_display(self):
        """Renderuje aktualny widok (zoom + pan + WB)."""
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
            Qt.TransformationMode.SmoothTransformation,
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
                visible_w, visible_h,
            )
            self._label.setPixmap(cropped)

        self._zoom_label.setText(f"{int(self._zoom * 100)}%")

    def _zoom_in(self):
        self._zoom = min(self._zoom * 1.25, 10.0)
        self._update_display()

    def _zoom_out(self):
        self._zoom = max(self._zoom / 1.25, 0.1)
        self._update_display()

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
        self._update_display()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._update_display()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self._zoom_fit)

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
            self._update_display()

    def mouseReleaseEvent(self, event):
        """Zakończ pan."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None

    def keyPressEvent(self, event):
        """F11 — fullscreen, Escape — zamknij / wyjdź z fullscreen."""
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
        if self.isFullScreen():
            self.showNormal()
            if self._saved_geometry:
                self.setGeometry(self._saved_geometry)
        else:
            self._saved_geometry = self.geometry()
            self.showFullScreen()
        QTimer.singleShot(50, self._zoom_fit)
