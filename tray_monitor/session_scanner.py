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


@dataclass
class SessionInfo:
    """Stan synchronizacji pojedynczego folderu sesji."""
    name:      str
    status:    str              # done | unknown
    date_str:  str              # sformatowana data sync lub ""


def scan_session_folders() -> list[SessionInfo]:
    """Zwraca listę folderów sesji z ich statusem sync (posortowane od najnowszego)."""
    cloud_dir = get_cloud_dir()
    if not os.path.isdir(cloud_dir):
        return []
    result = []
    for e in os.scandir(cloud_dir):
        if not e.is_dir():
            continue
        result.append(_read_session_info(e.name, e.path))
    result.sort(key=lambda x: x.name, reverse=True)
    return result[:15]


def _read_session_info(name: str, path: str) -> SessionInfo:
    """Czyta sync_status.json z folderu sesji."""
    status_path = os.path.join(path, STATUS_FILE)
    if not os.path.exists(status_path):
        return SessionInfo(name=name, status="unknown", date_str="")
    try:
        with open(status_path, encoding="utf-8") as f:
            data = json.load(f)
        raw_date = data.get("synced_at") or data.get("updated_at") or ""
        date_str = ""
        if raw_date:
            try:
                date_str = datetime.fromisoformat(raw_date).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
        return SessionInfo(
            name=name,
            status=data.get("status", "unknown"),
            date_str=date_str,
        )
    except Exception:
        return SessionInfo(name=name, status="unknown", date_str="")


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
