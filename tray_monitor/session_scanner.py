"""
tray_monitor/session_scanner.py

Czyta globalny sync_status.json z katalogu cloud/.
Skanuje foldery sesji do wyświetlenia w popup.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QSettings

STATUS_FILE = "sync_status.json"
CLOUD_DIR   = "cloud"


@dataclass
class SyncStatus:
    """Globalny stan synchronizacji cloud/."""
    status:     str              # running | done | warning | unknown
    updated_at: Optional[datetime]
    error:      str


def get_base_dir() -> str:
    """Czyta base_dir z QSettings aplikacji."""
    s = QSettings("Grzeza", "SessionsAssistant")
    return s.value(
        "session/directory",
        os.path.expanduser("~/Obrazy/sessions"),
    )


def get_cloud_dir() -> str:
    return os.path.join(get_base_dir(), CLOUD_DIR)


def read_sync_status() -> SyncStatus:
    """Czyta sync_status.json z cloud_dir. Zwraca unknown jeśli brak pliku."""
    cloud_dir   = get_cloud_dir()
    status_path = os.path.join(cloud_dir, STATUS_FILE)

    if not os.path.exists(status_path):
        return SyncStatus(status="unknown", updated_at=None, error="")

    try:
        with open(status_path, encoding="utf-8") as f:
            data = json.load(f)
        updated = None
        if data.get("updated_at"):
            try:
                updated = datetime.fromisoformat(data["updated_at"])
            except ValueError:
                pass
        return SyncStatus(
            status=data.get("status", "unknown"),
            updated_at=updated,
            error=data.get("error", ""),
        )
    except Exception:
        return SyncStatus(status="unknown", updated_at=None, error="")


def scan_session_folders() -> list[str]:
    """Zwraca listę nazw folderów sesji w cloud_dir (posortowane od najnowszego)."""
    cloud_dir = get_cloud_dir()
    if not os.path.isdir(cloud_dir):
        return []
    folders = [
        e.name for e in os.scandir(cloud_dir)
        if e.is_dir()
    ]
    folders.sort(reverse=True)
    return folders[:15]


def overall_status() -> str:
    """
    Zwraca zagregowany status dla ikony tray:
      running → 'running'
      warning → 'warning'
      done / unknown (brak pliku) → 'ok'
    """
    s = read_sync_status()
    if s.status == "running":
        return "running"
    if s.status == "warning":
        return "warning"
    return "ok"
