"""
Dialog podsumowania sesji fotograficznej.
Wyświetlany po zakończeniu sesji. Obsługuje trzy warianty:
  - normalne zakończenie (TIMEOUT) CLIENT/HOME: wyniki + QR
  - przerwana sesja CLIENT/HOME: wybór import/usuń → wyniki ± QR
  - sesja PRIVATE: obraz SD + przypomnienie
"""
from __future__ import annotations

import io
import os
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget,
)

from core.session_context import (
    EndReason, SessionMode, SessionSummary,
)
from ui.styles import center_on_parent, DIALOG_DETAILS_STYLE, DIALOG_WARNING_STYLE, DIALOG_BTN_W


# ─── stałe dialogu

ACTION_NEW_SESSION = 0
ACTION_DARKROOM    = 1


class _ScalableLabel(QLabel):
    """QLabel który skaluje czcionkę do dostępnej szerokości, bold."""

    _MIN_PT = 14

    def __init__(self, text: str, max_pt: int = 24, parent=None):
        super().__init__(text, parent)
        self._max_pt = max_pt
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_font(max_pt)

    def setText(self, text: str):
        super().setText(text)
        self._fit_font()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_font()

    def _fit_font(self):
        avail = self.width()
        if avail <= 0:
            return
        pt = self._max_pt
        fm = self.fontMetrics()
        while pt > self._MIN_PT and fm.horizontalAdvance(self.text()) > avail - 8:
            pt -= 1
            self._apply_font(pt)
            fm = self.fontMetrics()

    def _apply_font(self, pt: int):
        f = QFont()
        f.setPointSize(pt)
        f.setBold(True)
        self.setFont(f)


def _center_crop(pixmap: QPixmap, w: int, h: int) -> QPixmap:
    """Przycina pixmapę do rozmiaru w×h z centrum (crop-to-fill)."""
    scaled = pixmap.scaled(
        w, h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (scaled.width()  - w) // 2
    y = (scaled.height() - h) // 2
    return scaled.copy(x, y, w, h)


class SessionSummaryDialog(QDialog):
    """
    Dialog podsumowania sesji.
    Zamknięcie przez "New Session" → done(ACTION_NEW_SESSION),
    przez "Darkroom" → done(ACTION_DARKROOM).
    """

    def __init__(
        self,
        summary: SessionSummary,
        parent=None,
    ):
        super().__init__(parent)
        self._summary = summary
        self._focus_btn = None
        self._build_ui()
        self.setWindowTitle(self.tr("Session summary"))
        self.setMinimumSize(500, 480)
        self.resize(620, 580)
        self.setModal(True)
        self._populate(summary)

    def showEvent(self, event):
        super().showEvent(event)
        center_on_parent(self)
        if self._focus_btn:
            self._focus_btn.setFocus()

    # ─── Budowa UI

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(0)

        # Tytuł
        self.title = _ScalableLabel(self.tr("Session complete"), max_pt=24)
        layout.addWidget(self.title)

        layout.addSpacing(16)

        # Obraz — SD card (PRIVATE) lub QR (CLOUD/HOME) — ten sam slot
        self.sd_card_image = QLabel()
        self.sd_card_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _sd_path = os.path.join("assets", "pictures", "remove-sdcard.jpg")
        if os.path.exists(_sd_path):
            self.sd_card_image.setPixmap(
                _center_crop(QPixmap(_sd_path), 280, 280)
            )
        self.sd_card_image.hide()
        layout.addWidget(self.sd_card_image)

        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.hide()
        layout.addWidget(self.qr_label)

        font_code = QFont()
        font_code.setPointSize(16)
        font_code.setBold(True)
        font_code.setFamily("monospace")
        self.code_label = QLabel()
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setFont(font_code)
        self.code_label.hide()
        layout.addWidget(self.code_label)

        layout.addSpacing(12)

        # Blok info — 4 linie, spójny dla wszystkich trybów
        self.details = QLabel("")
        self.details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.details.setStyleSheet(DIALOG_DETAILS_STYLE)
        self.details.setWordWrap(True)
        layout.addWidget(self.details)

        layout.addSpacing(8)

        self.warnings_label = QLabel("")
        self.warnings_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warnings_label.setStyleSheet(DIALOG_WARNING_STYLE)
        self.warnings_label.setWordWrap(True)
        layout.addWidget(self.warnings_label)

        layout.addStretch(1)

        layout.addSpacing(8)

        # Przyciski nawigacyjne
        nav_row = QHBoxLayout()
        nav_row.addStretch(1)

        self.btn_darkroom = QPushButton(self.tr("→ Darkroom"))
        self.btn_darkroom.setFixedHeight(42)
        self.btn_darkroom.setMinimumWidth(DIALOG_BTN_W)
        self.btn_darkroom.clicked.connect(lambda: self.done(ACTION_DARKROOM))
        nav_row.addWidget(self.btn_darkroom)

        nav_row.addSpacing(12)

        self.btn_new = QPushButton(self.tr("New Session"))
        self.btn_new.setFixedHeight(42)
        self.btn_new.setMinimumWidth(DIALOG_BTN_W)
        self.btn_new.setDefault(True)
        self._focus_btn = self.btn_new
        self.btn_new.clicked.connect(lambda: self.done(ACTION_NEW_SESSION))
        nav_row.addWidget(self.btn_new)

        nav_row.addStretch(1)
        layout.addLayout(nav_row)

    # ─── Wypełnianie danych

    def _populate(self, summary: SessionSummary):
        ctx = summary.context

        # Tytuł
        if ctx.share_code:
            self.title.setText(self.tr("Code generated"))
        elif ctx.mode == SessionMode.PRIVATE:
            self.title.setText(self.tr("Session summary"))
        else:
            self.title.setText(self.tr("Session finished"))

        # Warianty
        if ctx.mode == SessionMode.PRIVATE:
            self.sd_card_image.show()
            self.btn_darkroom.hide()
            shots_str = str(summary.shot_count) if summary.shot_count else "—"
            self.details.setText("\n".join([
                self.tr("Private session"),
                self.tr("Duration: %1  ·  %2 shots")
                    .replace("%1", summary.duration_str)
                    .replace("%2", shots_str),
                self.tr("Don't forget to remove the SD card from the camera."),
            ]))
            self.btn_new.setDefault(True)
            self._focus_btn = self.btn_new

        else:
            # Normalne zakończenie CLIENT/HOME (po finalize — zawsze mamy kod i import)
            shots_str = str(summary.shot_count)
            line1 = (
                self.tr("Cloud session — %1").replace("%1", ctx.email)
                if ctx.mode == SessionMode.CLIENT
                else self.tr("Home session")
            )
            line2 = (
                self.tr("Your photos will be uploaded to the remote server.")
                if ctx.mode == SessionMode.CLIENT
                else self.tr("Photos saved locally.")
            )
            line3 = (
                self.tr("Duration: %1 · %2 shots imported")
                .replace("%1", summary.duration_str)
                .replace("%2", shots_str)
            )
            line4 = ctx.session_path or ""
            self.details.setText("\n".join([line1, line2, line3, line4]))
            if ctx.share_code:
                self._show_qr(ctx.share_code)
            self.btn_darkroom.hide()
            self.btn_new.setText(self.tr("OK"))
            self.btn_new.setDefault(True)
            self._focus_btn = self.btn_new

        if summary.warnings:
            self.warnings_label.setText(
                self.tr("Warnings: %1").replace("%1", " · ".join(summary.warnings[:3]))
            )

    # ─── QR kod

    def _show_qr(self, code: str) -> None:
        """Generuje i wyświetla QR kod z deep linkiem do bota."""
        try:
            import qrcode
            from PIL import Image as _PilImage
        except ImportError:
            self.code_label.setText(self.tr("Session code: %1").replace("%1", code))
            self.code_label.show()
            return

        bot_username = "pryzmat_studio_bot"
        url = f"https://t.me/{bot_username}?start={code}"

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")

        # Logo w centrum (maks. 20% szerokości)
        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "assets", "icons", "pryzmat-ico.png",
        )
        if os.path.exists(logo_path):
            logo = _PilImage.open(logo_path).convert("RGBA")
            max_logo = int(qr_img.width * 0.20)
            logo.thumbnail((max_logo, max_logo), _PilImage.LANCZOS)
            pad = 12
            bg = _PilImage.new(
                "RGBA", (logo.width + pad * 2, logo.height + pad * 2),
                (255, 255, 255, 255),
            )
            bg.paste(logo, (pad, pad), logo)
            pos = (
                (qr_img.width  - bg.width)  // 2,
                (qr_img.height - bg.height) // 2,
            )
            qr_img.paste(bg, pos)

        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        pixmap_raw = QPixmap()
        pixmap_raw.loadFromData(buf.getvalue())
        pixmap_scaled = pixmap_raw.scaled(
            300, 300,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Zaokrąglone rogi
        radius = 16
        pixmap = QPixmap(pixmap_scaled.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(pixmap.rect().toRectF(), radius, radius)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap_scaled)
        painter.end()

        self.qr_label.setPixmap(pixmap)
        self.qr_label.show()
        self.code_label.setText(self.tr("Session code: %1").replace("%1", code))
        self.code_label.show()

    # ─── Publiczne API

    def get_final_summary(self) -> Optional[SessionSummary]:
        """Zwraca podsumowanie sesji."""
        return self._summary
