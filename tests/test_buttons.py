#!/usr/bin/env python3
"""
Podgląd przycisków i wszystkich dialogów aplikacji.
Użycie:
  python3 tests/test_buttons.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QFrame, QDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette

from ui.styles import APP_STYLE, BTN_STYLE_RED

BTN_STYLE_AUTO = (
    "QPushButton:checked { background-color: #2e7d32; color: white; font-weight: bold; }"
    " QPushButton:disabled { background-color: #3a3a3a; color: #666; border: 1px solid #444; }"
    " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: palette(button); }"
    " QPushButton:checked:focus { background-color: #2e7d32; border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; }"
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _section(title):
    lbl = QLabel(title)
    lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #aaa; padding: 10px 0 2px 0;")
    return lbl


def _sep():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #444;")
    return line


def _row(label, *buttons):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 4, 0, 4)
    h.setSpacing(12)
    lbl = QLabel(label)
    lbl.setStyleSheet("color: #888; font-size: 11px; min-width: 320px;")
    h.addWidget(lbl)
    for b in buttons:
        h.addWidget(b)
    h.addStretch(1)
    return w


def _btn(factory, parent):
    """Przycisk Show → otwiera dialog (niemodalne, można otworzyć wiele naraz)."""
    b = QPushButton("Show")
    b.setFixedHeight(32)
    def _open():
        d = factory(parent)
        d.setModal(False)
        parent._open_dialogs.append(d)
        d.finished.connect(lambda: parent._open_dialogs.remove(d) if d in parent._open_dialogs else None)
        d.show()
    b.clicked.connect(_open)
    return b


def _make_closable(d):
    """Pozwala zamknąć dialog w trybie testowym (odblokowanie X i Escape)."""
    d.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
    d.reject = lambda: QDialog.reject(d)
    return d


# ── dane testowe ──────────────────────────────────────────────────────────────

def _ctx(mode="client", duration_min=30):
    from core.session_context import SessionContext, SessionMode
    m = {"client": SessionMode.CLIENT, "home": SessionMode.HOME, "private": SessionMode.PRIVATE}[mode]
    return SessionContext(
        session_id="2026-03-16_1500_demo",
        mode=m,
        email="jan@example.com" if mode == "client" else "",
        duration_min=duration_min,
        started_at=datetime.now(),
        session_path="/tmp/demo_session",
    )


def _summary(mode="client", end="timeout", shots=42):
    from core.session_context import SessionSummary, EndReason
    r = {"timeout": EndReason.TIMEOUT, "manual": EndReason.MANUAL}[end]
    return SessionSummary(context=_ctx(mode), shot_count=shots, end_reason=r)


# ── fabryki dialogów ──────────────────────────────────────────────────────────

def _no_camera(parent):
    from ui.dialogs.no_camera_dialog import NoCameraDialog
    return NoCameraDialog(parent)


def _no_sd(parent):
    from ui.dialogs.no_sd_card_dialog import NoSdCardDialog
    return NoSdCardDialog(parent)


def _usb_disconnect(parent):
    from ui.dialogs.usb_disconnect_dialog import UsbDisconnectDialog
    return UsbDisconnectDialog(parent)


# ── SESSION ACTIVE — każdy tryb ───────────────────────────────────────────────

def _active(mode, duration=30, countdown="28:45", pct=96):
    def _f(parent):
        from ui.dialogs.session_active_dialog import SessionActiveDialog
        d = SessionActiveDialog(_ctx(mode, duration), parent)
        d.countdown_label.setText(countdown)
        d.progress.setValue(pct)
        return _make_closable(d)
    return _f


# ── SESSION FINISHED / INTERRUPTED ───────────────────────────────────────────

def _finished(mode, end="timeout", shots=42):
    def _f(parent):
        from ui.dialogs.session_active_dialog import SessionActiveDialog
        d = SessionActiveDialog(_ctx(mode, 30), parent)
        d._on_session_finished(_summary(mode, end, shots))
        return _make_closable(d)
    return _f


# ── SESSION SUMMARY ───────────────────────────────────────────────────────────

def _sum(mode, end="timeout", shots=42):
    def _f(parent):
        from ui.dialogs.session_summary_dialog import SessionSummaryDialog
        return SessionSummaryDialog(_summary(mode, end, shots), parent)
    return _f


# ── SETTINGS ──────────────────────────────────────────────────────────────────

def _prefs(parent):
    from ui.dialogs.preferences_dialog import PreferencesDialog
    return PreferencesDialog(parent)


def _telegram(parent):
    from ui.dialogs.telegram_config_dialog import TelegramConfigDialog
    return TelegramConfigDialog(parent)


def _profiles(parent):
    from ui.dialogs.profile_browser_dialog import ProfileBrowserDialog
    return ProfileBrowserDialog("camera_profiles", parent)


# ── główne okno ───────────────────────────────────────────────────────────────

class ShowcaseWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dialog & Button Showcase")
        self.resize(720, 900)
        self._open_dialogs = []

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 24, 32, 32)
        lay.setSpacing(2)

        # ── BUTTON STYLES ─────────────────────────────────────────────────
        lay.addWidget(_section("BUTTON STYLES"))
        lay.addWidget(_sep())

        b1 = QPushButton("Continue →");      b1.setFixedHeight(42)
        b2 = QPushButton("New Session");     b2.setFixedHeight(42)
        b3 = QPushButton("Cancel");          b3.setFixedSize(90, 34); b3.setDefault(True)
        lay.addWidget(_row("default  (APP_STYLE)", b1, b2, b3))

        b4 = QPushButton("■  STOP SESSION"); b4.setFixedHeight(48); b4.setStyleSheet(BTN_STYLE_RED)
        b5 = QPushButton("Format Card");     b5.setMinimumHeight(28); b5.setStyleSheet(BTN_STYLE_RED)
        lay.addWidget(_row("red  (BTN_STYLE_RED)", b4, b5))

        b6 = QPushButton("AUTO"); b6.setFixedSize(65, 45); b6.setCheckable(True); b6.setStyleSheet(BTN_STYLE_AUTO)
        b7 = QPushButton("AUTO"); b7.setFixedSize(65, 45); b7.setCheckable(True); b7.setChecked(True); b7.setStyleSheet(BTN_STYLE_AUTO)
        lay.addWidget(_row("AUTO  (green :checked)", b6, b7))

        lay.addSpacing(8)

        # ── CAMERA / SD DIALOGS ───────────────────────────────────────────
        lay.addWidget(_section("DIALOGS — CAMERA / SD"))
        lay.addWidget(_sep())

        lay.addWidget(_row("NoCameraDialog",                        _btn(_no_camera,      self)))
        lay.addWidget(_row("NoSdCardDialog",                        _btn(_no_sd,          self)))
        lay.addWidget(_row("UsbDisconnectDialog  (Prepare Camera)", _btn(_usb_disconnect, self)))

        lay.addSpacing(8)

        # ── SESSION ACTIVE ────────────────────────────────────────────────
        lay.addWidget(_section("SESSION ACTIVE"))
        lay.addWidget(_sep())

        lay.addWidget(_row("SessionActiveDialog  [CLIENT,  active]",  _btn(_active("client",  30, "28:45", 96), self)))
        lay.addWidget(_row("SessionActiveDialog  [HOME,    active]",  _btn(_active("home",    20, "14:30", 72), self)))
        lay.addWidget(_row("SessionActiveDialog  [PRIVATE, active]",  _btn(_active("private", 15,  "5:10", 34), self)))

        lay.addSpacing(8)

        # ── SESSION FINISHED / INTERRUPTED ───────────────────────────────
        lay.addWidget(_section("SESSION FINISHED / INTERRUPTED"))
        lay.addWidget(_sep())

        lay.addWidget(_row("SessionActiveDialog  [CLIENT,  finished]",     _btn(_finished("client",  "timeout", 87), self)))
        lay.addWidget(_row("SessionActiveDialog  [CLIENT,  interrupted]",  _btn(_finished("client",  "manual",  23), self)))
        lay.addWidget(_row("SessionActiveDialog  [HOME,    finished]",     _btn(_finished("home",    "timeout", 55), self)))
        lay.addWidget(_row("SessionActiveDialog  [HOME,    interrupted]",  _btn(_finished("home",    "manual",  12), self)))
        lay.addWidget(_row("SessionActiveDialog  [PRIVATE, finished]",     _btn(_finished("private", "timeout",  0), self)))
        lay.addWidget(_row("SessionActiveDialog  [PRIVATE, interrupted]",  _btn(_finished("private", "manual",   0), self)))

        lay.addSpacing(8)

        # ── SESSION SUMMARY ───────────────────────────────────────────────
        lay.addWidget(_section("SESSION SUMMARY"))
        lay.addWidget(_sep())

        lay.addWidget(_row("SessionSummaryDialog  [CLIENT, timeout]",  _btn(_sum("client", "timeout", 87), self)))
        lay.addWidget(_row("SessionSummaryDialog  [HOME,   timeout]",  _btn(_sum("home",   "timeout", 55), self)))

        lay.addSpacing(8)

        # ── SETTINGS DIALOGS ──────────────────────────────────────────────
        lay.addWidget(_section("DIALOGS — SETTINGS"))
        lay.addWidget(_sep())

        lay.addWidget(_row("PreferencesDialog",     _btn(_prefs,    self)))
        lay.addWidget(_row("TelegramConfigDialog",  _btn(_telegram, self)))
        lay.addWidget(_row("ProfileBrowserDialog",  _btn(_profiles, self)))

        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    pal = app.palette()
    pal.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Highlight, QColor(160, 160, 160))
    pal.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.HighlightedText, QColor(10, 10, 10))
    app.setPalette(pal)
    w = ShowcaseWindow()
    w.show()
    sys.exit(app.exec())
