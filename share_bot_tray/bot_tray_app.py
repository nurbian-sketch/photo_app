"""
share_bot_tray/bot_tray_app.py

QSystemTrayIcon dla share_bot.
Polluje share_bot_status.json co POLL_MS.
Ikona: aktywna = bot działa, wyszarzona = bot nie działa.
"""
from __future__ import annotations

import json
import os
import sys

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

STATUS_FILE  = os.path.expanduser("~/.local/share/photo_app/share_bot_status.json")
POLL_MS      = 4000
PARENT_MS    = 2000   # jak często sprawdzamy czy rodzic żyje

_STATUS_LABELS: dict[str, str] = {
    "idle":    "Waiting for messages",
    "active":  "Active",
    "sending": "Sending photos…",
}


def _make_tray_icon(active: bool) -> QIcon:
    """Tworzy ikonę tray: kolorową (aktywna) lub przyciemnioną (nieaktywna)."""
    icon = QIcon.fromTheme("telegram")
    pm = icon.pixmap(22, 22) if not icon.isNull() else QPixmap()
    if pm.isNull():
        return QIcon()

    if active:
        return QIcon(pm)

    out = QPixmap(pm.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setOpacity(0.35)
    painter.drawPixmap(0, 0, pm)
    painter.end()
    return QIcon(out)


def _bot_alive() -> bool:
    """Sprawdza czy proces bota żyje na podstawie PID z status JSON."""
    try:
        if not os.path.exists(STATUS_FILE):
            return False
        with open(STATUS_FILE) as f:
            data = json.load(f)
        pid = data.get("pid")
        if not pid:
            return False
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except Exception:
        return False


def _read_status() -> str:
    """Odczytuje status bota z pliku JSON."""
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE) as f:
                return json.load(f).get("status", "idle")
    except Exception:
        pass
    return "idle"


class BotTrayApp:
    """Główna klasa tray monitora share_bot."""

    def __init__(self, app: QApplication, parent_pid: int | None = None):
        self._app        = app
        self._tray       = QSystemTrayIcon()
        self._active     = None   # None → pierwsze poll zawsze ustawia ikonę
        self._parent_pid = parent_pid

        self._build_menu()
        self._tray.activated.connect(self._on_activated)

        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

        # Timer do obserwacji rodzica — tray ukryty dopóki główna app działa
        if parent_pid:
            self._parent_timer = QTimer()
            self._parent_timer.timeout.connect(self._check_parent)
            self._parent_timer.start(PARENT_MS)
        else:
            self._parent_timer = None

        self._poll()

        # Pokaż tray tylko gdy brak rodzica (uruchomiono poza główną aplikacją)
        if not parent_pid:
            self._tray.show()

    # ─────────────────────────── OBSERWACJA RODZICA

    def _check_parent(self):
        """Sprawdza czy główna aplikacja nadal działa. Pokazuje tray po jej zamknięciu."""
        try:
            os.kill(self._parent_pid, 0)
        except (ProcessLookupError, OSError):
            # Rodzic zniknął — pokaż tray i zatrzymaj sprawdzanie
            self._parent_timer.stop()
            self._parent_pid = None
            self._tray.show()

    # ─────────────────────────── POLLING

    def _poll(self):
        active = _bot_alive()
        status = _read_status() if active else "offline"

        if active != self._active:
            self._active = active
            self._tray.setIcon(_make_tray_icon(active))

        label = _STATUS_LABELS.get(status, status) if active else "Not running"
        self._tray.setToolTip(f"Pryzmat Share Bot — {label}")

    # ─────────────────────────── MENU PPM

    def _build_menu(self):
        menu = QMenu()
        menu.addAction("Pryzmat Share Bot").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)
        self._tray.setContextMenu(menu)

    def _quit(self):
        """Zatrzymuje bota i zamyka tray."""
        # Próba zatrzymania bota przez SIGTERM
        try:
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE) as f:
                    pid = json.load(f).get("pid")
                if pid:
                    import signal
                    os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
        self._app.quit()

    # ─────────────────────────── KLIK LPM

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        pass  # można dodać popup w przyszłości
