#!/usr/bin/env python3
"""
Skrypt testowy dialogów sesji fotograficznej.
Pozwala przeglądać wszystkie stany dialogów bez aparatu.

Użycie:
  python3 tests/test_session_dialogs.py

Nawigacja:
  - Każdy dialog otwierany jest kolejno po zamknięciu poprzedniego.
  - Dialogi z przyciskiem STOP/Continue działają w trybie statycznym.
  - MockRunner symuluje odliczanie i zakończenie sesji.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

# Dodaj katalog projektu do ścieżki
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QWidget,
)

from core.session_context import (
    CameraSettings, EndReason, SessionContext, SessionMode, SessionSummary,
)
from ui.dialogs.session_active_dialog import SessionActiveDialog
from ui.dialogs.session_summary_dialog import (
    SessionSummaryDialog, ACTION_DARKROOM, ACTION_NEW_SESSION,
)
from ui.dialogs.no_camera_dialog import NoCameraDialog
from ui.dialogs.no_sd_card_dialog import NoSdCardDialog


# ─────────────────────────── Mock danych ──────────────────────────────────────

def _make_ctx(mode: SessionMode, email: str = "", duration: int = 1) -> SessionContext:
    ctx = SessionContext(
        session_id=f"2026-03-10_1430_{email or mode.value}",
        mode=mode,
        email=email,
        duration_min=duration,
        started_at=datetime(2026, 3, 10, 14, 30),
        ended_at=datetime(2026, 3, 10, 15, 0),
    )
    if mode != SessionMode.PRIVATE:
        ctx.session_path = "/tmp/photo_app_test/2026-03-10_1430_test"
        ctx.share_code   = "ABC123"
    return ctx


def _make_summary(
    mode: SessionMode,
    end_reason: EndReason,
    email: str = "",
    shot_count: int = 42,
) -> SessionSummary:
    ctx = _make_ctx(mode, email)
    ctx.sync_status = "done" if mode == SessionMode.CLIENT else "skipped"
    return SessionSummary(
        context=ctx,
        shot_count=shot_count,
        end_reason=end_reason,
        warnings=["Example warning"] if end_reason != EndReason.TIMEOUT else [],
    )


# ─────────────────────────── MockRunner ───────────────────────────────────────

class MockRunner(QObject):
    """Fałszywy runner — symuluje sygnały SessionRunner bez aparatu."""

    timer_tick      = pyqtSignal(int, int)   # remaining, total
    countdown_tick  = pyqtSignal(int)
    import_progress = pyqtSignal(int, int, str)
    state_changed   = pyqtSignal(object)     # SessionState
    session_finished = pyqtSignal(object)    # SessionSummary
    warning          = pyqtSignal(str)
    error            = pyqtSignal(str)

    def __init__(self, summary: SessionSummary, total_sec: int = None):
        super().__init__()
        self._summary   = summary
        self._total     = total_sec if total_sec is not None else summary.context.duration_min * 60
        self._remaining = self._total
        self._stopped   = False
        self._timer     = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start(self):
        from core.session_context import SessionState
        self.state_changed.emit(SessionState.ACTIVE)
        self._timer.start(1000)

    def request_stop(self):
        self._stopped = True
        self._timer.stop()
        from core.session_context import SessionState, EndReason
        self._summary.end_reason = EndReason.MANUAL
        self.state_changed.emit(SessionState.INTERRUPTED)
        self.session_finished.emit(self._summary)

    def isRunning(self):
        return self._timer.isActive()

    def _tick(self):
        from core.session_context import SessionState
        self._remaining -= 1
        self.timer_tick.emit(self._remaining, self._total)
        if self._remaining <= 0:
            self._timer.stop()
            self.state_changed.emit(SessionState.FINISHED)
            self.session_finished.emit(self._summary)


# ─────────────────────────── Menu główne ──────────────────────────────────────

class MenuDialog(QDialog):
    """Prosty wybór scenariusza do przetestowania."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test dialogów sesji")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("<b>Wybierz scenariusz do przetestowania:</b>"))
        layout.addSpacing(8)

        scenarios = [
            ("─── Sekwencja ───", None),
            ("▶  CLOUD → HOME → PRIVATE  (5s każda)", self._test_sequence),
            ("─── Dialogi systemowe ───", None),
            ("No camera (brak aparatu)", self._test_no_camera),
            ("No SD card (brak karty SD)", self._test_no_sd),
            ("─── Sesja aktywna ───", None),
            ("Active session (symulacja 10s)", self._test_active),
            ("─── Podsumowania ───", None),
            ("CLOUD — zakończona normalnie (z QR)", lambda: self._test_summary(
                _make_summary(SessionMode.CLIENT, EndReason.TIMEOUT, "jan@gmail.com")
            )),
            ("HOME — zakończona normalnie (z QR)", lambda: self._test_summary(
                _make_summary(SessionMode.HOME, EndReason.TIMEOUT)
            )),
            ("PRIVATE — zakończona normalnie", lambda: self._test_summary(
                _make_summary(SessionMode.PRIVATE, EndReason.TIMEOUT)
            )),
            ("─── Przerwane ───", None),
            ("CLOUD — przerwana (wybór import/usuń)", lambda: self._test_summary(
                _make_summary(SessionMode.CLIENT, EndReason.MANUAL, "jan@gmail.com")
            )),
            ("HOME — przerwana (wybór import/usuń)", lambda: self._test_summary(
                _make_summary(SessionMode.HOME, EndReason.MANUAL)
            )),
            ("PRIVATE — przerwana", lambda: self._test_summary(
                _make_summary(SessionMode.PRIVATE, EndReason.MANUAL)
            )),
            ("─── Inne ───", None),
            ("USB detected — CLOUD (aparat podłączony)", lambda: self._test_summary(
                _make_summary(SessionMode.CLIENT, EndReason.USB_DETECTED, "jan@gmail.com")
            )),
            ("Bez zdjęć (0 shots)", lambda: self._test_summary(
                _make_summary(SessionMode.HOME, EndReason.TIMEOUT, shot_count=0)
            )),
        ]

        for label, handler in scenarios:
            if handler is None:
                sep = QLabel(label)
                sep.setStyleSheet("color: #888; font-size: 11px; margin-top: 6px;")
                layout.addWidget(sep)
            else:
                btn = QPushButton(label)
                btn.setFixedHeight(38)
                btn.clicked.connect(handler)
                layout.addWidget(btn)

        layout.addSpacing(16)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        btn_close = QPushButton("Zamknij")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

    def _test_sequence(self):
        """Sekwencja: CLOUD → HOME → PRIVATE, każda 5s, zakończona normalnie."""
        for mode, email in [
            (SessionMode.CLIENT, "jan@gmail.com"),
            (SessionMode.HOME,   ""),
            (SessionMode.PRIVATE, ""),
        ]:
            ctx     = _make_ctx(mode, email, duration=1)
            summary = _make_summary(mode, EndReason.TIMEOUT, email)
            runner  = MockRunner(summary, total_sec=5)

            active_dlg = SessionActiveDialog(ctx, parent=self)
            active_dlg.connect_runner(runner)
            active_dlg.btn_stop.clicked.connect(runner.request_stop)
            runner.start()
            active_dlg.exec()

            summary_dlg = SessionSummaryDialog(summary, runner=None, parent=self)
            result = summary_dlg.exec()
            if result == ACTION_NEW_SESSION:
                continue
            break

    def _test_no_camera(self):
        """NoCameraDialog — bez timera USB (statyczny podgląd)."""
        dlg = NoCameraDialog(parent=self)
        dlg._timer.stop()   # zatrzymaj polling lsusb — brak aparatu w teście
        result = dlg.exec()
        QTimer.singleShot(0, lambda: self._show_info(
            f"NoCameraDialog: {'accept' if result else 'reject'}"
        ))

    def _test_no_sd(self):
        """NoSdCardDialog — podgląd statyczny."""
        dlg = NoSdCardDialog(parent=self)
        result = dlg.exec()
        QTimer.singleShot(0, lambda: self._show_info(
            f"NoSdCardDialog: {'OK' if result else 'Cancel'}"
        ))

    def _test_active(self):
        """Otwiera dialog aktywnej sesji z MockRunner (10s odliczanie + krótka sesja)."""
        ctx = _make_ctx(SessionMode.CLIENT, "jan@gmail.com", duration=1)
        summary = _make_summary(SessionMode.CLIENT, EndReason.TIMEOUT, "jan@gmail.com")
        runner = MockRunner(summary, total_sec=10)

        dlg = SessionActiveDialog(ctx, parent=self)
        dlg.connect_runner(runner)
        dlg.btn_stop.clicked.connect(runner.request_stop)
        runner.start()
        result = dlg.exec()
        got = dlg.get_summary()
        info = f"Zamknięto. result={result}, summary={got is not None}"
        QTimer.singleShot(0, lambda: self._show_info(info))

    def _test_summary(self, summary: SessionSummary):
        """Otwiera dialog podsumowania dla danego podsumowania."""
        dlg = SessionSummaryDialog(summary, runner=None, parent=self)
        result = dlg.exec()
        label = {
            ACTION_NEW_SESSION: "New Session",
            ACTION_DARKROOM:    "Darkroom",
        }.get(result, f"code={result}")
        info = f"Zamknięto: {label}"
        QTimer.singleShot(0, lambda: self._show_info(info))

    def _show_info(self, text: str):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Wynik", text)


# ─────────────────────────── main ─────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Ustaw katalog roboczy na katalog projektu (potrzebne dla ścieżek assets/)
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_dir)

    menu = MenuDialog()
    menu.exec()
    sys.exit(0)
