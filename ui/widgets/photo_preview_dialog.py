"""
ui/widgets/photo_preview_dialog.py

Okno podglądu zdjęcia — cienka powłoka dialogu nad PreviewPanel.
Ładuje obraz asynchronicznie, przekazuje WB picker do PreviewPanel.

Sygnały:
    wb_applied(int kelvin) — użytkownik zaakceptował WB picker → temperatura w Kelwinach
"""
import os

from ui.styles import BTN_STYLE_RED
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap

from core.image_io import ImageLoader
from ui.widgets.preview_panel import PreviewPanel


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
        self._saved_geometry = None

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

        self._init_ui(image_path)

        # Ładuj obraz asynchronicznie
        self._loader = ImageLoader(image_path)
        self._loader.loaded.connect(self._on_image_loaded)
        self._loader.start()

    # ─────────────────────────────── UI

    def _init_ui(self, image_path: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Główny widget podglądu
        self._panel = PreviewPanel(self)
        self._panel.wb_applied.connect(self._on_wb_accepted)
        layout.addWidget(self._panel, 1)

        # Pasek dolny: ścieżka + przyciski
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 5, 10, 5)
        bar.setSpacing(8)

        path_label = QLabel(image_path)
        path_label.setStyleSheet("color: #555; font-size: 11px;")
        bar.addWidget(path_label)

        bar.addStretch()

        if self._close_all_callback:
            btn_close_all = QPushButton(self.tr("Close All"))
            btn_close_all.setFixedSize(90, 32)
            btn_close_all.setStyleSheet(BTN_STYLE_RED)
            btn_close_all.clicked.connect(self._close_all_callback)
            bar.addWidget(btn_close_all)

        btn_close = QPushButton(self.tr("Close"))
        btn_close.setFixedSize(80, 32)
        btn_close.clicked.connect(self.close)
        bar.addWidget(btn_close)

        from PyQt6.QtWidgets import QWidget
        bar_widget = QWidget()
        bar_widget.setStyleSheet("background: #3d3d3d;")
        bar_widget.setLayout(bar)
        layout.addWidget(bar_widget)

    # ─────────────────────────────── Ładowanie obrazu

    def _on_image_loaded(self, pixmap: QPixmap, exif: dict):
        """Callback z ImageLoader — przekazuje do PreviewPanel."""
        self._panel.set_pixmap(pixmap, exif.get('orientation', 0))
        self._panel.set_exif(exif)

    # ─────────────────────────────── WB

    def _on_wb_accepted(self, kelvin: int):
        """PreviewPanel zaakceptował WB — reemituj sygnał dialogu."""
        self.wb_applied.emit(kelvin)

    # ─────────────────────────────── Klawiatura / fullscreen

    def keyPressEvent(self, event):
        """F11 — fullscreen, Escape — zamknij / wyjdź z fullscreen."""
        if event.key() == Qt.Key.Key_F11:
            self._toggle_fullscreen()
        elif event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self._toggle_fullscreen()
            else:
                self.close()
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
        QTimer.singleShot(50, self._panel._zoom_fit)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self._panel._zoom_fit)
