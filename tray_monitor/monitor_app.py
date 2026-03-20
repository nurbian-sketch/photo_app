"""
tray_monitor/monitor_app.py

QSystemTrayIcon z kolorowymi ikonami i popup z listą sesji.
Polluje sync_status.json co POLL_INTERVAL_MS.
"""
from __future__ import annotations

import os
import subprocess

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtWidgets import (
    QApplication, QMenu, QSystemTrayIcon,
    QDialog, QVBoxLayout, QLabel, QDialogButtonBox,
)

from tray_monitor.session_scanner import (
    overall_status, read_sync_status, scan_session_folders, get_cloud_dir,
)

# Polling ikony co 4 sekundy
POLL_INTERVAL_MS = 4000

_STATUS_LABELS: dict[str, str] = {
    "ok":      "All synced",
    "warning": "Sync problem — retrying",
    "running": "Syncing…",
}

_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "icons",
)


def _make_tray_icon(status: str) -> QIcon:
    """
    Ładuje ikonę tray z pliku PNG:
      running  → sync.png   (pełny kolor)
      ok       → gdrive.png (pełny kolor)
      warning  → gdrive.png (opacity 0.35)
    """
    if status == "running":
        fname, active = "sync.png", True
    elif status == "ok":
        fname, active = "gdrive.png", True
    else:
        fname, active = "gdrive.png", False

    pm = QPixmap(os.path.join(_ASSETS_DIR, fname)).scaled(
        22, 22,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if pm.isNull():
        pm = QPixmap(22, 22)
        pm.fill(Qt.GlobalColor.transparent)

    if active:
        return QIcon(pm)

    out = QPixmap(pm.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setOpacity(0.35)
    painter.drawPixmap(0, 0, pm)
    painter.end()
    return QIcon(out)


def _worker_alive(pid) -> bool:
    """Zwraca True jeśli proces o danym PID nadal działa."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True  # istnieje, ale inny użytkownik


class SyncMonitorApp:
    """Główna klasa tray monitora."""

    def __init__(self, app: QApplication):
        self._app    = app
        self._tray   = QSystemTrayIcon()
        self._status = None   # None → pierwsze poll zawsze ustawia ikonę

        # Flaga: tray uruchomiony przy zamknięciu app gdy sync był running → auto-quit po "ok"
        self._started_for_sync = True

        self._build_menu()
        self._tray.activated.connect(self._on_activated)

        # Polling ikony
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_INTERVAL_MS)

        # Pierwsze odświeżenie przed show()
        self._poll()
        self._tray.show()

    # ─────────────────────────── POLLING

    def _poll(self):
        """Czyta globalny status sync i aktualizuje ikonę."""
        new_status = overall_status()

        if new_status != self._status:
            self._status = new_status
            self._tray.setIcon(_make_tray_icon(new_status))
            label = _STATUS_LABELS.get(new_status, "Unknown")
            self._tray.setToolTip(f"Sessions Sync — {label}")

            # Auto-quit: sync się skończył — tray nie jest już potrzebny
            if new_status == "ok" and self._started_for_sync:
                QTimer.singleShot(3000, self._app.quit)

    # ─────────────────────────── MENU PPM

    def _build_menu(self):
        menu = QMenu()
        menu.addAction("Sessions Sync Monitor").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Open sessions folder", self._open_cloud_dir)
        menu.addSeparator()
        menu.addAction("Quit", self._app.quit)
        self._tray.setContextMenu(menu)

    # ─────────────────────────── KLIK LPM — POPUP

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_popup()

    def _show_popup(self):
        """Popup z globalnym statusem i listą folderów sesji."""
        sync  = read_sync_status()
        folders = scan_session_folders()

        dlg = QDialog()
        dlg.setWindowTitle("Sessions Sync")
        dlg.setMinimumWidth(420)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        # Globalny status
        st = self._status or "ok"
        color  = {"ok": "#2e7d32", "warning": "#f9a825", "running": "#1565c0"}.get(st, "#555")
        symbol = {"ok": "✓", "warning": "!", "running": "↻"}.get(st, "?")
        label  = _STATUS_LABELS.get(st, "Unknown")
        date_str = sync.updated_at.strftime("%Y-%m-%d %H:%M") if sync.updated_at else ""

        status_lbl = QLabel(
            f"<span style='color:{color};font-size:16px;font-weight:bold'>{symbol}</span>"
            f"&nbsp;&nbsp;<b>{label}</b>"
            + (f"&nbsp;&nbsp;<span style='color:#888;font-size:11px'>{date_str}</span>"
               if date_str else "")
        )
        status_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(status_lbl)

        if sync.error:
            err_lbl = QLabel(f"<span style='color:#c62828'>{sync.error}</span>")
            err_lbl.setTextFormat(Qt.TextFormat.RichText)
            err_lbl.setWordWrap(True)
            layout.addWidget(err_lbl)

        if folders:
            layout.addWidget(QLabel("─" * 40))
            for s in folders:
                icon = "✓" if s.status == "done" else "?"
                color = "#2e7d32" if s.status == "done" else "#f9a825"
                date = f"&nbsp;&nbsp;<span style='color:#888;font-size:11px'>{s.date_str}</span>" if s.date_str else ""
                row = QLabel(
                    f"<span style='color:{color}'>{icon}</span>&nbsp;&nbsp;{s.name}{date}"
                )
                row.setTextFormat(Qt.TextFormat.RichText)
                layout.addWidget(row)
        else:
            layout.addWidget(QLabel("No client sessions found."))

        layout.addSpacing(8)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(dlg.reject)
        layout.addWidget(btn)

        dlg.exec()

    # ─────────────────────────── AKCJE

    def _open_cloud_dir(self):
        """Otwiera katalog cloud/ w menedżerze plików."""
        try:
            subprocess.Popen(["xdg-open", get_cloud_dir()])
        except Exception:
            pass
