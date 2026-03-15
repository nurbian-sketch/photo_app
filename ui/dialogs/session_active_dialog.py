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
from ui.dialogs.session_summary_dialog import ACTION_NEW_SESSION
from ui.styles import (
    BTN_STYLE_RED, center_on_parent, set_panel_bg,
    SESSION_COUNTDOWN_STYLE, SESSION_PROGRESS_STYLE,
    SESSION_INFO_STYLE, SESSION_IMPORT_STYLE,
    SESSION_BTN_H, SESSION_BTN_STOP_H,
)

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
        self._runner = None
        self._build_ui()
        self.setWindowTitle(self.tr("Session"))
        self.setMinimumSize(540, 550)
        self.setMaximumSize(640, 770)
        self.resize(640, 770)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self._set_info(ctx)

    def showEvent(self, event):
        super().showEvent(event)
        center_on_parent(self)
        self.btn_stop.setFocus()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Górny pasek: countdown + progress
        top = QWidget()
        set_panel_bg(top)
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(40, 20, 40, 12)
        top_layout.setSpacing(12)

        self.countdown_label = QLabel("--:--")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(40)
        font.setBold(True)
        self.countdown_label.setFont(font)
        self.countdown_label.setStyleSheet(SESSION_COUNTDOWN_STYLE)
        top_layout.addWidget(self.countdown_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFixedHeight(12)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(SESSION_PROGRESS_STYLE)
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

        # Dolny panel: info + przyciski
        bottom = QWidget()
        set_panel_bg(bottom)
        bot_layout = QVBoxLayout(bottom)
        bot_layout.setContentsMargins(40, 12, 40, 20)
        bot_layout.setSpacing(8)

        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet(SESSION_INFO_STYLE)
        bot_layout.addWidget(self.info_label)

        self.import_label = QLabel("")
        self.import_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.import_label.setStyleSheet(SESSION_IMPORT_STYLE)
        self.import_label.hide()
        bot_layout.addWidget(self.import_label)

        # Widget przycisków przerwanej sesji — tylko CLIENT/HOME
        self._interrupted_widget = QWidget()
        int_layout = QHBoxLayout(self._interrupted_widget)
        int_layout.setContentsMargins(0, 0, 0, 0)
        int_layout.setSpacing(12)
        int_layout.addStretch(1)

        btn_import = QPushButton(self.tr("⬇  Import photos"))
        btn_import.setFixedHeight(SESSION_BTN_H)
        btn_import.clicked.connect(self._on_interrupted_import)
        int_layout.addWidget(btn_import)

        btn_del_int = QPushButton(self.tr("🗑  Delete photos"))
        btn_del_int.setFixedHeight(SESSION_BTN_H)
        btn_del_int.clicked.connect(self._on_interrupted_delete)
        int_layout.addWidget(btn_del_int)

        int_layout.addStretch(1)
        self._interrupted_widget.hide()
        bot_layout.addWidget(self._interrupted_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.btn_stop = QPushButton(self.tr("■  STOP SESSION"))
        self.btn_stop.setFixedHeight(SESSION_BTN_STOP_H)
        self.btn_stop.setStyleSheet(BTN_STYLE_RED)
        self.btn_stop.setDefault(True)
        btn_row.addWidget(self.btn_stop)

        self.btn_continue = QPushButton(self.tr("Continue →"))
        self.btn_continue.setFixedHeight(SESSION_BTN_H)
        self.btn_continue.clicked.connect(self.accept)
        self.btn_continue.hide()
        btn_row.addWidget(self.btn_continue)

        self.btn_new_session = QPushButton(self.tr("New Session"))
        self.btn_new_session.setFixedHeight(SESSION_BTN_H)
        self.btn_new_session.clicked.connect(lambda: self.done(ACTION_NEW_SESSION))
        self.btn_new_session.hide()
        btn_row.addWidget(self.btn_new_session)

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
        """Łączy sygnały SessionRunner z dialogiem i zachowuje referencję."""
        self._runner = runner
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
        self.progress.setValue(0)
        self.import_label.hide()
        self.btn_stop.hide()

        if self._ctx.mode == SessionMode.PRIVATE:
            # Prywatna — niezależnie od powodu: zdjęcia na karcie, brak akcji
            bg = BG_FINISHED if summary.end_reason == EndReason.TIMEOUT else BG_INTERRUPTED
            self._bg.set_background(bg)
            self.countdown_label.setText(self.tr("Session ended"))
            self.info_label.setText(self.tr("Take your SD card."))
            self.btn_continue.show()
            self.btn_continue.setDefault(True)
            QTimer.singleShot(50, self.btn_continue.setFocus)
        elif summary.end_reason == EndReason.TIMEOUT:
            self._bg.set_background(BG_FINISHED)
            self.countdown_label.setText(self.tr("Session finished"))
            self.btn_continue.show()
            self.btn_continue.setDefault(True)
            QTimer.singleShot(50, self.btn_continue.setFocus)
        else:
            self._bg.set_background(BG_INTERRUPTED)
            self.countdown_label.setText(self.tr("Session interrupted"))
            elapsed_min = summary.context.elapsed_sec // 60
            self.info_label.setText(
                self.tr(
                    "Your session was interrupted after %1 min.\n"
                    "Your photos are on the SD card."
                ).replace("%1", str(elapsed_min))
            )
            self._interrupted_widget.show()

    # ─── Handlery przerwanej sesji

    def _on_interrupted_import(self):
        """Import zdjęć po przerwaniu sesji (CLIENT/HOME)."""
        self._interrupted_widget.hide()
        self.import_label.show()
        self.import_label.setText(self.tr("Starting import..."))
        self._runner.session_finished.disconnect(self._on_session_finished)
        self._runner.session_finished.connect(self._on_import_finished)
        self._runner.start_import_only()

    def _on_import_finished(self, summary: SessionSummary):
        self._summary = summary
        self.import_label.hide()
        self.accept()

    def _on_interrupted_delete(self):
        """Usuń zdjęcia z karty SD bez importu."""
        self._interrupted_widget.hide()
        self.import_label.show()
        self.import_label.setText(self.tr("Deleting photos from card..."))
        self._runner.session_finished.disconnect(self._on_session_finished)
        self._runner.session_finished.connect(self._on_delete_finished)
        self._runner.start_delete_from_card()

    def _on_delete_finished(self, summary: SessionSummary):
        self._summary = summary
        self.import_label.hide()
        self.info_label.setText(self.tr("Your photos have been deleted."))
        self.btn_new_session.show()
        self.btn_new_session.setDefault(True)
        QTimer.singleShot(50, self.btn_new_session.setFocus)

    # ─── Publiczne API

    def get_summary(self) -> Optional[SessionSummary]:
        return self._summary

    def reject(self):
        """Blokuje Escape — zamknięcie tylko przez Continue."""
        if self._summary is None:
            return  # sesja trwa — zignoruj
        super().reject()
