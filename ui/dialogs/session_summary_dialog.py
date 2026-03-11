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
    QWidget, QMessageBox,
)

from core.session_context import (
    EndReason, SessionMode, SessionSummary,
)


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
    Dla przerwanych sesji CLIENT/HOME obsługuje wybór import/usuń wewnętrznie.
    Zamknięcie przez "New Session" → done(ACTION_NEW_SESSION),
    przez "Darkroom" → done(ACTION_DARKROOM).
    """

    def __init__(
        self,
        summary: SessionSummary,
        runner=None,
        parent=None,
    ):
        super().__init__(parent)
        self._summary = summary
        self._runner = runner
        self._final_summary: Optional[SessionSummary] = summary
        self._focus_btn = None
        self._build_ui()
        self.setWindowTitle(self.tr("Session summary"))
        self.setMinimumSize(500, 480)
        self.resize(620, 580)
        self.setModal(True)
        self._populate(summary)

    def showEvent(self, event):
        super().showEvent(event)
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
        self.details.setStyleSheet("color: #aaa; font-size: 13px;")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)

        layout.addSpacing(8)

        self.warnings_label = QLabel("")
        self.warnings_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warnings_label.setStyleSheet("color: #e65100; font-size: 12px;")
        self.warnings_label.setWordWrap(True)
        layout.addWidget(self.warnings_label)

        layout.addSpacing(8)

        # Postęp importu (widoczny podczas importu)
        self.import_progress_label = QLabel("")
        self.import_progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_progress_label.setStyleSheet("color: #aaa; font-size: 13px;")
        self.import_progress_label.hide()
        layout.addWidget(self.import_progress_label)

        layout.addStretch(1)

        # Przyciski wyboru dla przerwanej sesji CLIENT/HOME
        self._choice_widget = QWidget()
        choice_layout = QHBoxLayout(self._choice_widget)
        choice_layout.setContentsMargins(0, 0, 0, 0)
        choice_layout.setSpacing(12)
        choice_layout.addStretch(1)

        self.btn_import_card = QPushButton(self.tr("⬇  Import photos"))
        self.btn_import_card.setFixedHeight(42)
        self.btn_import_card.clicked.connect(self._on_import)
        choice_layout.addWidget(self.btn_import_card)

        self.btn_delete_card = QPushButton(self.tr("🗑  Delete photos"))
        self.btn_delete_card.setFixedHeight(42)
        self.btn_delete_card.clicked.connect(self._on_delete)
        choice_layout.addWidget(self.btn_delete_card)

        choice_layout.addStretch(1)
        self._choice_widget.hide()
        layout.addWidget(self._choice_widget)

        layout.addSpacing(8)

        # Przyciski nawigacyjne
        nav_row = QHBoxLayout()
        nav_row.addStretch(1)

        self.btn_darkroom = QPushButton(self.tr("→ Darkroom"))
        self.btn_darkroom.setFixedHeight(42)
        self.btn_darkroom.clicked.connect(lambda: self.done(ACTION_DARKROOM))
        nav_row.addWidget(self.btn_darkroom)

        nav_row.addSpacing(12)

        self.btn_new = QPushButton(self.tr("New Session"))
        self.btn_new.setFixedHeight(42)
        self.btn_new.clicked.connect(lambda: self.done(ACTION_NEW_SESSION))
        nav_row.addWidget(self.btn_new)

        nav_row.addStretch(1)
        layout.addLayout(nav_row)

    # ─── Wypełnianie danych

    def _populate(self, summary: SessionSummary):
        ctx = summary.context
        interrupted = summary.end_reason not in (EndReason.TIMEOUT, EndReason.USB_DETECTED)
        needs_import = ctx.mode in (SessionMode.CLIENT, SessionMode.HOME)

        # Tytuł
        if summary.end_reason == EndReason.TIMEOUT:
            self.title.setText(self.tr("Session finished"))
        elif summary.end_reason == EndReason.USB_DETECTED:
            self.title.setText(self.tr("Session stopped — camera connected"))
        else:
            self.title.setText(self.tr("Session interrupted"))

        # Warianty
        if ctx.mode == SessionMode.PRIVATE:
            self.sd_card_image.show()
            self.btn_darkroom.hide()
            self._choice_widget.hide()
            self.details.setText("\n".join([
                self.tr("Private session"),
                self.tr("Photos stay on SD card only."),
                self.tr("Duration: %1").replace("%1", summary.duration_str),
                self.tr("Don't forget to remove the SD card from the camera."),
            ]))
            self.btn_new.setDefault(True)
            self._focus_btn = self.btn_new

        elif interrupted and needs_import:
            # Przerwana CLOUD/HOME: pokaż wybór import/usuń
            line1 = (
                self.tr("Cloud session — %1").replace("%1", ctx.email)
                if ctx.mode == SessionMode.CLIENT
                else self.tr("Home session")
            )
            line2 = (
                self.tr("Photos uploaded to remote server.")
                if ctx.mode == SessionMode.CLIENT
                else self.tr("Photos saved locally.")
            )
            self.details.setText("\n".join([
                line1,
                line2,
                self.tr("Session interrupted · Duration: %1").replace("%1", summary.duration_str),
                self.tr("Photos are on the camera's SD card."),
            ]))
            self._choice_widget.show()
            self.btn_darkroom.hide()
            self.btn_new.hide()
            self.btn_import_card.setDefault(True)
            self._focus_btn = self.btn_import_card

        else:
            # Normalne zakończenie CLOUD/HOME
            shots_str = str(summary.shot_count)
            sync_str = {
                "done":    self.tr("✓ Synced to Google Drive"),
                "pending": self.tr("Sync pending..."),
                "failed":  self.tr("⚠ Sync failed"),
                "skipped": "",
            }.get(ctx.sync_status, "")
            line1 = (
                self.tr("Cloud session — %1").replace("%1", ctx.email)
                if ctx.mode == SessionMode.CLIENT
                else self.tr("Home session")
            )
            line2 = (
                self.tr("Photos uploaded to remote server.")
                if ctx.mode == SessionMode.CLIENT
                else self.tr("Photos saved locally.")
            )
            line3 = (
                self.tr("Duration: %1 · %2 shots imported")
                .replace("%1", summary.duration_str)
                .replace("%2", shots_str)
            )
            line4 = sync_str or (ctx.session_path or "")
            self.details.setText("\n".join([line1, line2, line3, line4]))
            if ctx.share_code:
                self._show_qr(ctx.share_code)
            self.btn_darkroom.setDefault(True)
            self._focus_btn = self.btn_darkroom

        if summary.warnings:
            self.warnings_label.setText(
                self.tr("Warnings: %1").replace("%1", " · ".join(summary.warnings[:3]))
            )

    # ─── Import i usuń dla przerwanej sesji

    def _on_import(self):
        if not self._runner:
            return
        self._choice_widget.hide()
        self.import_progress_label.show()
        self.import_progress_label.setText(self.tr("Starting import..."))
        self._runner.import_progress.connect(self._on_import_progress)
        self._runner.session_finished.connect(self._on_import_done)
        self._runner.start_import_only()

    def _on_import_progress(self, current: int, total: int, filename: str):
        self.import_progress_label.setText(
            self.tr("Importing %1/%2: %3")
            .replace("%1", str(current))
            .replace("%2", str(total))
            .replace("%3", filename)
        )

    def _on_import_done(self, summary: SessionSummary):
        self._final_summary = summary
        self.import_progress_label.hide()
        ctx = summary.context
        shots_str = str(summary.shot_count)
        line1 = (
            self.tr("Cloud session — %1").replace("%1", ctx.email)
            if ctx.mode == SessionMode.CLIENT
            else self.tr("Home session")
        )
        line2 = (
            self.tr("Photos uploaded to remote server.")
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
        self.btn_darkroom.show()
        self.btn_new.show()
        self.btn_darkroom.setDefault(True)
        self.btn_darkroom.setFocus()
        self._focus_btn = self.btn_darkroom
        self._ask_delete()

    def _on_delete(self):
        if not self._runner:
            self._finish_without_qr()
            return
        ans = QMessageBox.question(
            self,
            self.tr("Delete photos?"),
            self.tr(
                "Delete all photos from this session from the camera's SD card?\n"
                "This cannot be undone."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._choice_widget.hide()
        self.import_progress_label.show()
        self.import_progress_label.setText(self.tr("Deleting photos from card..."))
        self.btn_delete_card.setEnabled(False)
        self._runner.session_finished.connect(self._on_delete_done)
        self._runner.start_delete_from_card()

    def _on_delete_done(self, summary: SessionSummary):
        self._final_summary = summary
        self.import_progress_label.hide()
        # Wyniki bez QR
        self._finish_without_qr()

    def _finish_without_qr(self):
        ctx = self._summary.context
        line1 = (
            self.tr("Cloud session — %1").replace("%1", ctx.email)
            if ctx.mode == SessionMode.CLIENT
            else self.tr("Home session")
        )
        line2 = (
            self.tr("Photos uploaded to remote server.")
            if ctx.mode == SessionMode.CLIENT
            else self.tr("Photos saved locally.")
        )
        line3 = (
            self.tr("Session interrupted · Duration: %1")
            .replace("%1", self._summary.duration_str)
        )
        line4 = self.tr("Photos deleted from SD card.")
        self.details.setText("\n".join([line1, line2, line3, line4]))
        self.btn_new.show()
        self.btn_new.setDefault(True)
        self.btn_new.setFocus()
        self._focus_btn = self.btn_new

    def _ask_delete(self):
        """Po imporcie — pytanie o usunięcie z karty SD."""
        if not self._runner:
            return
        ans = QMessageBox.question(
            self,
            self.tr("Delete from SD card?"),
            self.tr(
                "Photos imported successfully.\n"
                "Delete imported photos from the camera's SD card?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._runner.session_finished.connect(self._on_delete_after_import)
            self._runner.start_delete_from_card()

    def _on_delete_after_import(self, _summary):
        pass  # Usunięto — nic do zrobienia w UI

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
        """Zwraca ostateczne podsumowanie (po imporcie, jeśli był)."""
        return self._final_summary
