"""
Dialog aktywnej sesji fotograficznej.
Wyświetlany podczas trwania sesji bezprzewodowej — odliczanie,
pasek postępu, przycisk STOP. Łączy się z SessionRunner przez connect_runner().
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QSizePolicy, QWidget,
)

from core.session_context import SessionContext, SessionSummary, SessionState, SessionMode, EndReason
from ui.styles import BTN_STYLE_RED

BG_ACTIVE      = os.path.join("assets", "pictures", "session-active.jpg")
BG_FINISHED    = os.path.join("assets", "pictures", "session-finished-3.jpg")
BG_INTERRUPTED = os.path.join("assets", "pictures", "session-interrupted-2.jpg")


class _BackgroundWidget(QWidget):
    """Widget tła z obrazem skalowanym z zachowaniem proporcji."""

    def __init__(self, fill_color: str = "#000000", parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._fill = QColor(fill_color)

    def set_background(self, path: str):
        self._pixmap = QPixmap(path) if path and os.path.exists(path) else None
        self.update()

    def sizeHint(self):
        return QSize(0, 0)

    def minimumSizeHint(self):
        return QSize(0, 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._fill)
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width()  - scaled.width())  // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)


class SessionActiveDialog(QDialog):
    """
    Modal dialog wyświetlany podczas aktywnej sesji bezprzewodowej.
    Łączy się z SessionRunner przez connect_runner().
    Zamknięcie następuje gdy użytkownik kliknie "Continue" po zakończeniu sesji.
    """

    def __init__(self, ctx: SessionContext, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        self._summary: Optional[SessionSummary] = None
        self._build_ui()
        self.setWindowTitle(self.tr("Session"))
        self.setMinimumSize(540, 550)
        self.setMaximumSize(640, 770)
        self.resize(640, 770)
        self.setModal(True)
        # Blokuj zamknięcie przez X podczas aktywnej sesji
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self._set_info(ctx)
        self._resize_print_timer = QTimer(self)
        self._resize_print_timer.setSingleShot(True)
        self._resize_print_timer.timeout.connect(
            lambda: print(f"SessionActiveDialog: {self.width()} x {self.height()}")
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.btn_stop.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_print_timer.start(300)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Górny pasek: countdown + progress
        top = QWidget()
        top.setStyleSheet("background-color: #3d3d3d;")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(40, 20, 40, 12)
        top_layout.setSpacing(12)

        self.countdown_label = QLabel("--:--")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(40)
        font.setBold(True)
        self.countdown_label.setFont(font)
        self.countdown_label.setStyleSheet("color: #e0e0e0; background: transparent;")
        top_layout.addWidget(self.countdown_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFixedHeight(12)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                background-color: rgba(0,0,0,120);
                border-radius: 0px;
                border: 1px solid rgba(255,255,255,40);
            }
            QProgressBar::chunk {
                background-color: rgba(255,255,255,200);
                border-radius: 0px;
            }
        """)
        # Progress bar węższy o 20% — stretch 1:8:1
        pb_row = QHBoxLayout()
        pb_row.setContentsMargins(0, 0, 0, 0)
        pb_row.addStretch(1)
        pb_row.addWidget(self.progress, 8)
        pb_row.addStretch(1)
        top_layout.addLayout(pb_row)
        layout.addWidget(top)

        # Środek: obraz tła
        self._bg = _BackgroundWidget(fill_color="#3d3d3d")
        self._bg.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._bg.set_background(BG_ACTIVE)
        layout.addWidget(self._bg, 1)

        # Dolny panel: info + import + przyciski
        bottom = QWidget()
        bottom.setStyleSheet("background-color: #3d3d3d;")
        bot_layout = QVBoxLayout(bottom)
        bot_layout.setContentsMargins(40, 12, 40, 20)
        bot_layout.setSpacing(8)

        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet(
            "color: rgba(255,255,255,180); font-size: 14px; background: transparent;"
        )
        bot_layout.addWidget(self.info_label)

        self.import_label = QLabel("")
        self.import_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_label.setStyleSheet(
            "color: rgba(255,255,255,180); font-size: 13px; background: transparent;"
        )
        self.import_label.hide()
        bot_layout.addWidget(self.import_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_stop = QPushButton(self.tr("■  STOP SESSION"))
        self.btn_stop.setFixedHeight(48)
        self.btn_stop.setStyleSheet(BTN_STYLE_RED)
        self.btn_stop.setDefault(True)
        btn_row.addWidget(self.btn_stop)

        self.btn_continue = QPushButton(self.tr("Continue →"))
        self.btn_continue.setFixedHeight(42)
        self.btn_continue.clicked.connect(self.accept)
        self.btn_continue.hide()
        btn_row.addWidget(self.btn_continue)

        btn_row.addStretch(1)
        bot_layout.addLayout(btn_row)

        layout.addWidget(bottom)

    def _set_info(self, ctx: SessionContext):
        if ctx.mode == SessionMode.CLIENT:
            desc = self.tr("Cloud session — photos will be sent to: %1.").replace("%1", ctx.email)
        elif ctx.mode == SessionMode.HOME:
            desc = self.tr("Home session — photos saved locally.")
        else:
            desc = self.tr("Private session — photos stay on SD card only.")
        self.info_label.setText(f"{desc}  ·  {ctx.duration_min} min")

    # ─── Podłączenie do SessionRunner

    def connect_runner(self, runner):
        """Łączy sygnały SessionRunner z dialogiem."""
        runner.timer_tick.connect(self._on_timer_tick)
        runner.countdown_tick.connect(self._on_countdown_tick)
        runner.import_progress.connect(self._on_import_progress)
        runner.state_changed.connect(self._on_state_changed)
        runner.session_finished.connect(self._on_session_finished)

    # ─── Handlery sygnałów

    def _on_timer_tick(self, remaining: int, total: int):
        m, s = divmod(remaining, 60)
        self.countdown_label.setText(f"{m:02d}:{s:02d}")
        pct = int(remaining / total * 100) if total > 0 else 0
        self.progress.setValue(pct)

    def _on_countdown_tick(self, remaining: int):
        self.countdown_label.setText(
            self.tr("Starting in %1...").replace("%1", str(remaining))
        )
        self.progress.setValue(100)

    def _on_import_progress(self, current: int, total: int, filename: str):
        self.import_label.show()
        self.import_label.setText(
            self.tr("Importing %1/%2: %3")
            .replace("%1", str(current))
            .replace("%2", str(total))
            .replace("%3", filename)
        )
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText(self.tr("Importing..."))

    def _on_state_changed(self, state: SessionState):
        if state == SessionState.IMPORTING:
            self.import_label.show()

    def _on_session_finished(self, summary: SessionSummary):
        self._summary = summary
        if summary.end_reason == EndReason.TIMEOUT:
            self._bg.set_background(BG_FINISHED)
            self.countdown_label.setText(self.tr("Finished"))
        else:
            self._bg.set_background(BG_INTERRUPTED)
            self.countdown_label.setText(self.tr("Interrupted"))
        self.progress.setValue(0)
        self.import_label.hide()
        self.btn_stop.hide()
        self.btn_continue.show()
        self.btn_continue.setDefault(True)
        QTimer.singleShot(50, self.btn_continue.setFocus)

    # ─── Publiczne API

    def get_summary(self) -> Optional[SessionSummary]:
        return self._summary

    def reject(self):
        """Blokuje Escape — zamknięcie tylko przez Continue."""
        if self._summary is None:
            return  # sesja trwa — zignoruj
        super().reject()
