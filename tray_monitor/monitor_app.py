"""
tray_monitor/monitor_app.py

QSystemTrayIcon z kolorowymi ikonami i popup z listą sesji.
Polluje sync_status.json co POLL_INTERVAL_MS.
"""
from __future__ import annotations

import os
import subprocess

from PyQt6.QtCore import QTimer, QSize, Qt, QPointF
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QBrush, QPen, QPainterPath
from PyQt6.QtWidgets import (
    QApplication, QMenu, QSystemTrayIcon,
    QDialog, QVBoxLayout, QLabel, QDialogButtonBox,
)

from tray_monitor.session_scanner import (
    overall_status, read_sync_status, scan_session_folders, get_cloud_dir,
)

# Polling ikony co 4 sekundy
POLL_INTERVAL_MS = 4000

# Sync co 5 minut
SYNC_INTERVAL_MS = 5 * 60 * 1000

# Kolory i symbole ikon tray
_COLORS = {
    "ok":      "#2e7d32",   # ciemna zieleń
    "warning": "#f9a825",   # bursztynowy
    "running": "#1565c0",   # niebieski
}

_SYMBOLS = {
    "ok":      "✓",
    "warning": "!",
    "running": "↻",
}

_STATUS_LABELS: dict[str, str] = {
    "ok":      "All synced",
    "warning": "Sync problem — retrying",
    "running": "Syncing…",
}


def _make_tray_icon(status: str) -> QIcon:
    """Rysuje kółko z symbolem w odpowiednim kolorze (22×22 px)."""
    size = 22
    pm   = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Wypełnienie kółka — 3px margines (2px więcej niż poprzednio)
    p.setBrush(QBrush(QColor(_COLORS.get(status, "#555555"))))
    p.setPen(QPen(Qt.PenStyle.NoPen))
    p.drawEllipse(3, 3, size - 6, size - 6)

    # Symbol
    if status == "ok":
        # Check rysowany ręcznie — linia 2.0, okrągłe końcówki
        pen = QPen(QColor("white"))
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        path.moveTo(5, 11)    # lewa górna część
        path.lineTo(9, 15)    # wierzchołek (dół)
        path.lineTo(17, 8)    # prawa górna część
        p.drawPath(path)
    else:
        p.setPen(QPen(QColor("white")))
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, _SYMBOLS.get(status, "?"))

    p.end()
    return QIcon(pm)


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

        self._build_menu()
        self._tray.activated.connect(self._on_activated)

        # Polling ikony
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_INTERVAL_MS)

        # Periodyczny sync — tray sam pilnuje że local = remote
        self._sync_timer = QTimer()
        self._sync_timer.timeout.connect(self._trigger_sync)
        self._sync_timer.start(SYNC_INTERVAL_MS)

        # Pierwsze odświeżenie przed show() — ikona ustawiona zanim pojawi się w trayu
        self._poll()
        self._trigger_sync()   # sync od razu przy starcie
        self._tray.show()

    # ─────────────────────────── SYNC

    def _trigger_sync(self):
        """Odpala sync workera jeśli nie działa. Wywołuje co SYNC_INTERVAL_MS."""
        from PyQt6.QtCore import QSettings
        import json

        # Odczytaj konfigurację rclone
        settings = QSettings("Grzeza", "SessionsAssistant")
        remote = settings.value("rclone/remote", "").strip()
        dest   = settings.value("rclone/destination", "Sessions").strip()

        if not remote:
            return   # rclone nie skonfigurowany

        cloud_dir = get_cloud_dir()
        if not os.path.isdir(cloud_dir):
            return   # brak katalogu cloud/

        # Nie odpalam jeśli worker nadal żyje (sprawdzamy PID)
        status_path = os.path.join(cloud_dir, "sync_status.json")
        if os.path.exists(status_path):
            try:
                with open(status_path) as f:
                    st = json.load(f)
                if st.get("status") == "running" and _worker_alive(st.get("pid")):
                    return
            except Exception:
                pass

        # Uruchom workera jako odłączony subprocess
        worker_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "rclone_sync_worker.py",
        )
        import sys as _sys
        subprocess.Popen(
            [_sys.executable, worker_path, cloud_dir, remote, dest],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ─────────────────────────── POLLING

    def _poll(self):
        """Czyta globalny status sync i aktualizuje ikonę."""
        new_status = overall_status()

        if new_status != self._status:
            self._status = new_status
            self._tray.setIcon(_make_tray_icon(new_status))
            label = _STATUS_LABELS.get(new_status, "Unknown")
            self._tray.setToolTip(f"Sessions Sync — {label}")

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
        color  = _COLORS.get(self._status or "ok", "#555")
        symbol = _SYMBOLS.get(self._status or "ok", "?")
        label  = _STATUS_LABELS.get(self._status or "ok", "Unknown")
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
