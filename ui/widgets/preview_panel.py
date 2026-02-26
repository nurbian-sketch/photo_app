"""
PreviewPanel — wielokrotnego użytku widget podglądu zdjęcia.
Zoom, pan, rotate, wheel, klawiatura, EXIF bar, auto-resize.
Logika identyczna z CapturePreviewDialog z camera_view.py.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QTransform


class PreviewPanel(QWidget):
    """
    Widget podglądu do osadzania wewnątrz widoków (nie dialog).
    API:
        panel.set_pixmap(pixmap, orientation=0)  — załaduj obraz
        panel.set_exif(exif_dict)                — zaktualizuj pasek EXIF
        panel.set_message(text)                  — pokaż komunikat (loading/error)
        panel.clear()                            — wyczyść
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._original_pixmap = QPixmap()
        self._pixmap = QPixmap()
        self._rotation = 0
        self._zoom = 1.0
        self._pan_offset = [0, 0]
        self._drag_start = None

        self._build_ui()

    # ─────────────────────────── UI

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Obraz
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: #3d3d3d;")
        self._label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._label.setMouseTracking(True)
        self._label.setMinimumSize(1, 1)  # zapobiega rozpychaniu okna przez duza pixmape
        layout.addWidget(self._label, 1)

        # EXIF bar
        self._exif_bar = QLabel("No image")
        self._exif_bar.setStyleSheet(
            "background: #222; color: #999; font-size: 11px; padding: 3px 10px;"
        )
        self._exif_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._exif_bar)

        # Control bar — identyczna z CapturePreviewDialog
        control_bar = QWidget()
        control_bar.setStyleSheet("background: #3d3d3d;")
        ctrl = QHBoxLayout(control_bar)
        ctrl.setContentsMargins(10, 5, 10, 5)
        ctrl.setSpacing(8)

        btn_rotate_left = QPushButton("↶")
        btn_rotate_left.setFixedSize(32, 32)
        btn_rotate_left.setToolTip("Rotate left 90° [←]")
        btn_rotate_left.setStyleSheet("font-size: 16px;")
        btn_rotate_left.clicked.connect(self.rotate_left)
        ctrl.addWidget(btn_rotate_left)

        btn_rotate_right = QPushButton("↷")
        btn_rotate_right.setFixedSize(32, 32)
        btn_rotate_right.setToolTip("Rotate right 90° [→]")
        btn_rotate_right.setStyleSheet("font-size: 16px;")
        btn_rotate_right.clicked.connect(self.rotate_right)
        ctrl.addWidget(btn_rotate_right)

        sep = QLabel("|")
        sep.setStyleSheet("color: #555;")
        ctrl.addWidget(sep)

        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedSize(32, 32)
        btn_zoom_out.setStyleSheet("font-size: 18px; font-weight: bold;")
        btn_zoom_out.clicked.connect(self._zoom_out)
        ctrl.addWidget(btn_zoom_out)

        self._zoom_label = QLabel("Fit")
        self._zoom_label.setFixedWidth(50)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_label.setStyleSheet("color: #888;")
        ctrl.addWidget(self._zoom_label)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedSize(32, 32)
        btn_zoom_in.setStyleSheet("font-size: 18px; font-weight: bold;")
        btn_zoom_in.clicked.connect(self._zoom_in)
        ctrl.addWidget(btn_zoom_in)

        btn_fit = QPushButton("Fit")
        btn_fit.setFixedSize(50, 32)
        btn_fit.setToolTip("Fit to window [0]")
        btn_fit.clicked.connect(self._zoom_fit)
        ctrl.addWidget(btn_fit)

        btn_100 = QPushButton("1:1")
        btn_100.setFixedSize(50, 32)
        btn_100.setToolTip("100% zoom [1]")
        btn_100.clicked.connect(self._zoom_100)
        ctrl.addWidget(btn_100)

        ctrl.addStretch()
        layout.addWidget(control_bar)

    # ─────────────────────────── PUBLIC API

    def set_pixmap(self, pixmap: QPixmap, orientation: int = 0):
        """Załaduj obraz z opcjonalną orientacją EXIF."""
        self._original_pixmap = pixmap
        self._rotation = orientation
        self._apply_rotation()
        self._pan_offset = [0, 0]
        QTimer.singleShot(0, self._zoom_fit)

    def set_exif(self, exif: dict):
        parts = [v for v in [
            exif.get('camera', ''), exif.get('dims', ''), exif.get('size', ''),
            exif.get('shutter', ''), exif.get('aperture', ''), exif.get('iso', ''),
            exif.get('focal', ''), exif.get('date', '')
        ] if v]
        self._exif_bar.setText("   •   ".join(parts) if parts else "No EXIF data")

    def set_message(self, text: str):
        """Pokaż komunikat (loading/error) zamiast obrazu."""
        self._label.setPixmap(QPixmap())
        self._label.setText(text)
        self._exif_bar.setText("")

    def clear(self):
        self._original_pixmap = QPixmap()
        self._pixmap = QPixmap()
        self._label.clear()
        self._label.setText("No image")
        self._exif_bar.setText("")

    # ─────────────────────────── ROTATE

    def rotate_left(self):
        self._rotation = (self._rotation - 90) % 360
        self._apply_rotation()
        self._pan_offset = [0, 0]
        self._zoom_fit()

    def rotate_right(self):
        self._rotation = (self._rotation + 90) % 360
        self._apply_rotation()
        self._pan_offset = [0, 0]
        self._zoom_fit()

    def _apply_rotation(self):
        if self._original_pixmap.isNull():
            self._pixmap = QPixmap()
            return
        if self._rotation:
            self._pixmap = self._original_pixmap.transformed(
                QTransform().rotate(self._rotation),
                Qt.TransformationMode.SmoothTransformation
            )
        else:
            self._pixmap = self._original_pixmap

    # ─────────────────────────── ZOOM

    def _zoom_in(self):
        self._zoom = min(self._zoom * 1.25, 10.0)
        self._update_preview()

    def _zoom_out(self):
        self._zoom = max(self._zoom / 1.25, 0.05)
        self._update_preview()

    def _zoom_fit(self):
        if self._pixmap.isNull():
            return
        lw = self._label.width()
        lh = self._label.height()
        if lw < 10 or lh < 10:
            QTimer.singleShot(50, self._zoom_fit)
            return
        self._zoom = min(lw / self._pixmap.width(), lh / self._pixmap.height())
        self._pan_offset = [0, 0]
        self._update_preview()

    def _zoom_100(self):
        self._zoom = 1.0
        self._pan_offset = [0, 0]
        self._update_preview()

    # ─────────────────────────── RENDER — identyczny z CapturePreviewDialog

    def _update_preview(self):
        if self._pixmap.isNull():
            return
        img_w = int(self._pixmap.width() * self._zoom)
        img_h = int(self._pixmap.height() * self._zoom)
        if img_w < 1 or img_h < 1:
            return
        scaled = self._pixmap.scaled(
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

    # ─────────────────────────── EVENTS — identyczne z CapturePreviewDialog

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._on_resize)

    def _on_resize(self):
        if self._pixmap.isNull():
            return
        lw = self._label.width()
        lh = self._label.height()
        if lw < 10 or lh < 10:
            return
        # Jeśli byliśmy na Fit (lub pan=0) — przelicz Fit do nowego rozmiaru
        fit_zoom = min(lw / self._pixmap.width(), lh / self._pixmap.height())
        if self._pan_offset == [0, 0] or abs(self._zoom - fit_zoom) / max(fit_zoom, 0.001) < 0.02:
            self._zoom_fit()
        else:
            self._update_preview()

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self._zoom_in()
        else:
            self._zoom_out()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            delta = event.pos() - self._drag_start
            self._pan_offset[0] -= delta.x()
            self._pan_offset[1] -= delta.y()
            self._drag_start = event.pos()
            self._update_preview()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key.Key_Left:
            self.rotate_left()
        elif k == Qt.Key.Key_Right:
            self.rotate_right()
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom_in()
        elif k == Qt.Key.Key_Minus:
            self._zoom_out()
        elif k == Qt.Key.Key_0:
            self._zoom_fit()
        elif k == Qt.Key.Key_1:
            self._zoom_100()
        else:
            super().keyPressEvent(event)
