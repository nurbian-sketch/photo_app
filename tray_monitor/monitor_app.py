"""
tray_monitor/monitor_app.py

QSystemTrayIcon z ikonami freedesktop i popup z listą sesji.
Polluje sync_status.json co POLL_INTERVAL_MS.
"""
from __future__ import annotations

import os
import subprocess

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QMenu, QSystemTrayIcon,
    QDialog, QVBoxLayout, QLabel, QDialogButtonBox,
)

from tray_monitor.session_scanner import (
    SessionSyncInfo, scan_sessions, overall_status, get_base_dir,
)

# Polling co 4 sekundy
POLL_INTERVAL_MS = 4000

# Mapowanie statusu → ikona freedesktop
_ICONS: dict[str, str] = {
    "idle":    "network-offline",
    "running": "emblem-synchronizing",
    "done":    "emblem-default",
    "failed":  "dialog-warning",
}

_STATUS_LABELS: dict[str, str] = {
    "idle":    "No sync activity",
    "running": "Syncing…",
    "done":    "All synced",
    "failed":  "Sync error",
}


class SyncMonitorApp:
    """Główna klasa tray monitora."""

    def __init__(self, app: QApplication):
        self._app       = app
        self._tray      = QSystemTrayIcon()
        self._sessions:  list[SessionSyncInfo] = []
        self._status     = None   # None → pierwsze poll zawsze ustawia ikonę

        self._build_menu()
        self._tray.activated.connect(self._on_activated)

        # Polling
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_INTERVAL_MS)

        # Pierwsze odświeżenie przed show() — żeby ikona była ustawiona od razu
        self._poll()
        self._tray.show()

    # ─────────────────────────── POLLING

    def _poll(self):
        """Skanuje sesje i aktualizuje ikonę."""
        self._sessions = scan_sessions(limit=15)
        new_status     = overall_status(self._sessions)

        if new_status != self._status:
            self._status = new_status
            self._update_icon()
            self._update_tooltip()

    # ─────────────────────────── IKONA

    def _update_icon(self):
        icon_name = _ICONS.get(self._status, "network-offline")
        icon      = QIcon.fromTheme(icon_name)
        self._tray.setIcon(icon)

    def _update_tooltip(self):
        label = _STATUS_LABELS.get(self._status, "Unknown")
        self._tray.setToolTip(f"Sessions Sync — {label}")

    # ─────────────────────────── MENU PPM

    def _build_menu(self):
        menu = QMenu()
        menu.addAction("Sessions Sync Monitor").setEnabled(False)
        menu.addSeparator()
        self._sessions_menu = menu.addMenu("Sessions")
        menu.addSeparator()
        menu.addAction("Open sessions folder", self._open_base_dir)
        menu.addSeparator()
        menu.addAction("Quit", self._app.quit)
        self._tray.setContextMenu(menu)

    # ─────────────────────────── KLIK LPM — POPUP

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_popup()

    def _show_popup(self):
        """Popup z listą sesji i ich statusami."""
        dlg = QDialog()
        dlg.setWindowTitle("Sessions Sync")
        dlg.setMinimumWidth(420)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(6)

        if not self._sessions:
            layout.addWidget(QLabel("No client sessions found."))
        else:
            for s in self._sessions[:10]:
                icon_char = {
                    "running": "⟳",
                    "done":    "✓",
                    "failed":  "✗",
                    "unknown": "?",
                }.get(s.status, "·")

                date_str = ""
                if s.updated_at:
                    date_str = s.updated_at.strftime("%Y-%m-%d %H:%M")

                row = QLabel(
                    f"{icon_char}  {s.folder_name}"
                    + (f"  <span style='color:#888;font-size:11px'>{date_str}</span>"
                       if date_str else "")
                )
                row.setTextFormat(__import__(
                    'PyQt6.QtCore', fromlist=['Qt']
                ).Qt.TextFormat.RichText)

                if s.status == "failed" and s.error:
                    row.setToolTip(s.error)
                layout.addWidget(row)

        layout.addSpacing(8)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(dlg.reject)
        layout.addWidget(btn)

        dlg.exec()

    # ─────────────────────────── AKCJE

    def _open_base_dir(self):
        """Otwiera folder sesji w menedżerze plików."""
        base = get_base_dir()
        try:
            subprocess.Popen(["xdg-open", base])
        except Exception:
            pass
