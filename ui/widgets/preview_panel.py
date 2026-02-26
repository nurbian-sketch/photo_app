"""
PreviewPanel — wielokrotnego użytku widget podglądu zdjęcia.
Zoom, pan, rotate, wheel, klawiatura, EXIF bar, auto-resize.
Wbudowany WB picker z podglądem korekcji w miejscu.
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
        panel.activate_wb_mode()                 — aktywuje tryb WB picker
    Sygnały:
        wb_applied(int kelvin)                   — użytkownik zaakceptował WB
    """

    wb_applied = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._original_pixmap = QPixmap()
        self._pixmap = QPixmap()
        self._rotation = 0
        self._zoom = 1.0
        self._pan_offset = [0, 0]
        self._drag_start = None

        # Stan WB picker
        self._wb_mode = False
        self._wb_pixmap = None
        self._wb_kelvin = None
        self._wb_worker = None

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
        self._label.setMinimumSize(1, 1)
        layout.addWidget(self._label, 1)

        # EXIF bar
        self._exif_bar = QLabel("No image")
        self._exif_bar.setStyleSheet(
            "background: #222; color: #999; font-size: 11px; padding: 3px 10px;"
        )
        self._exif_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._exif_bar)

        # Control bar
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

        sep_wb = QLabel("|")
        sep_wb.setStyleSheet("color: #555;")
        ctrl.addWidget(sep_wb)

        # WB picker
        self._btn_wb = QPushButton("Pick WB")
        self._btn_wb.setFixedSize(70, 32)
        self._btn_wb.setCheckable(True)
        self._btn_wb.setToolTip("Click on a neutral white/grey area to pick white balance")
        self._btn_wb.clicked.connect(self._toggle_wb_mode)
        ctrl.addWidget(self._btn_wb)

        self._wb_label = QLabel("")
        self._wb_label.setFixedWidth(60)
        self._wb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._wb_label.setStyleSheet("color: #888; font-size: 11px;")
        ctrl.addWidget(self._wb_label)

        self._btn_wb_accept = QPushButton("Apply")
        self._btn_wb_accept.setFixedSize(55, 32)
        self._btn_wb_accept.setVisible(False)
        self._btn_wb_accept.clicked.connect(self._accept_wb)
        ctrl.addWidget(self._btn_wb_accept)

        self._btn_wb_cancel = QPushButton("Cancel")
        self._btn_wb_cancel.setFixedSize(55, 32)
        self._btn_wb_cancel.setVisible(False)
        self._btn_wb_cancel.clicked.connect(self._cancel_wb)
        ctrl.addWidget(self._btn_wb_cancel)

        ctrl.addStretch()
        layout.addWidget(control_bar)

        # Event filter — przechwytuje kliknięcia w trybie WB picker
        self._label.installEventFilter(self)

    # ─────────────────────────── PUBLIC API

    def set_pixmap(self, pixmap: QPixmap, orientation: int = 0):
        """Załaduj obraz z opcjonalną orientacją EXIF."""
        self._cancel_wb()
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
        self._cancel_wb()
        self._original_pixmap = QPixmap()
        self._pixmap = QPixmap()
        self._label.clear()
        self._label.setText("No image")
        self._exif_bar.setText("")

    def activate_wb_mode(self):
        """Aktywuje tryb WB picker (wywoływane z DarkroomView)."""
        if not self._pixmap.isNull():
            self._btn_wb.setChecked(True)
            self._toggle_wb_mode(True)

    # ─────────────────────────── WB PICKER

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self._label and self._wb_mode:
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._on_wb_pick(event.pos())
                    return True
        return super().eventFilter(obj, event)

    def _toggle_wb_mode(self, checked: bool):
        self._wb_mode = checked
        if checked:
            self._label.setCursor(Qt.CursorShape.CrossCursor)
            self._wb_label.setText("Click neutral")
        else:
            self._cancel_wb()

    def _on_wb_pick(self, label_pos):
        """Próbkuje piksel w miejscu kliknięcia i uruchamia worker WB."""
        from ui.widgets.photo_preview_dialog import _WBWorker
        pix = (
            self._wb_pixmap
            if (self._wb_pixmap and not self._wb_pixmap.isNull())
            else self._pixmap
        )
        if pix.isNull():
            return
        if self._wb_worker and self._wb_worker.isRunning():
            return
        pos = self._label_to_pixmap_pos(label_pos, pix)
        if pos is None:
            return
        self._wb_label.setText("…")
        self._wb_worker = _WBWorker(pix, pos[0], pos[1])
        self._wb_worker.finished.connect(self._on_wb_computed)
        self._wb_worker.start()

    def _label_to_pixmap_pos(self, label_pos, pix: QPixmap):
        """Mapuje współrzędne w _label na piksel w pixmapie."""
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

    def _on_wb_computed(self, corrected_pixmap: QPixmap, kelvin: int):
        if not self._wb_mode:
            return  # WB mode anulowany podczas działania workera
        self._wb_pixmap = corrected_pixmap
        snapped = max(2500, min(10000, round(kelvin / 100) * 100))
        self._wb_kelvin = snapped
        self._wb_label.setText(f"{snapped} K")
        self._btn_wb_accept.setVisible(True)
        self._btn_wb_cancel.setVisible(True)
        self._update_preview()

    def _accept_wb(self):
        if self._wb_kelvin is not None:
            self.wb_applied.emit(self._wb_kelvin)
        self._cancel_wb()

    def _cancel_wb(self):
        self._wb_mode = False
        self._wb_pixmap = None
        self._wb_kelvin = None
        self._wb_worker = None
        if hasattr(self, '_btn_wb'):
            self._btn_wb.setChecked(False)
            self._btn_wb_accept.setVisible(False)
            self._btn_wb_cancel.setVisible(False)
            self._wb_label.setText("")
            self._label.unsetCursor()
        self._update_preview()

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

    def _get_display_pixmap(self) -> QPixmap:
        """Zwraca pixmapę do wyświetlenia: WB preview lub oryginał po rotacji."""
        if self._wb_pixmap and not self._wb_pixmap.isNull():
            return self._wb_pixmap
        return self._pixmap

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

    # ─────────────────────────── RENDER

    def _update_preview(self):
        pixmap = self._get_display_pixmap()
        if pixmap.isNull():
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

    # ─────────────────────────── EVENTS

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
        if event.button() == Qt.MouseButton.LeftButton and not self._wb_mode:
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
        else:
            super().keyPressEvent(event)
