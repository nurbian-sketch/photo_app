"""
tray_monitor/session_scanner.py

Skanuje base_dir w poszukiwaniu sesji CLIENT i ich statusu sync.
Czyta sync_status.json z każdego folderu cloud/.
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
class SessionSyncInfo:
    """Stan synchronizacji pojedynczej sesji."""
    folder_name:  str
    session_path: str
    status:       str        # running | done | failed | unknown
    updated_at:   Optional[datetime]
    error:        str


def get_base_dir() -> str:
    """Czyta base_dir z QSettings aplikacji."""
    s = QSettings("Grzeza", "SessionsAssistant")
    return s.value(
        "session/directory",
        os.path.expanduser("~/Obrazy/sessions"),
    )


def scan_sessions(limit: int = 20) -> list[SessionSyncInfo]:
    """
    Skanuje base_dir/cloud/ i zwraca listę sesji z ich stanem sync.
    Sortuje od najnowszej. Limit = max liczba wyników.
    """
    base_dir   = get_base_dir()
    cloud_dir  = os.path.join(base_dir, CLOUD_DIR)
    results: list[SessionSyncInfo] = []

    if not os.path.isdir(cloud_dir):
        return results

    for entry in os.scandir(cloud_dir):
        if not entry.is_dir():
            continue
        status_path = os.path.join(entry.path, STATUS_FILE)
        info = _read_status(entry.path, entry.name, status_path)
        results.append(info)

    results.sort(key=lambda x: x.updated_at or datetime.min, reverse=True)
    return results[:limit]


def overall_status(sessions: list[SessionSyncInfo]) -> str:
    """
    Zwraca zagregowany status dla ikony tray:
      running → 'running'
      any failed (bez running) → 'failed'
      all done / empty → 'done'
      brak sesji → 'idle'
    """
    if not sessions:
        return "idle"
    statuses = {s.status for s in sessions}
    if "running" in statuses:
        return "running"
    if "failed" in statuses:
        return "failed"
    if all(s.status == "done" for s in sessions):
        return "done"
    return "idle"


def _read_status(
    session_path: str, folder_name: str, status_path: str
) -> SessionSyncInfo:
    """Wczytuje sync_status.json lub zwraca unknown."""
    if not os.path.exists(status_path):
        return SessionSyncInfo(
            folder_name=folder_name,
            session_path=session_path,
            status="unknown",
            updated_at=None,
            error="",
        )
    try:
        with open(status_path, encoding="utf-8") as f:
            data = json.load(f)
        updated = None
        if data.get("updated_at"):
            try:
                updated = datetime.fromisoformat(data["updated_at"])
            except ValueError:
                pass
        return SessionSyncInfo(
            folder_name=folder_name,
            session_path=session_path,
            status=data.get("status", "unknown"),
            updated_at=updated,
            error=data.get("error", ""),
        )
    except Exception:
        return SessionSyncInfo(
            folder_name=folder_name,
            session_path=session_path,
            status="unknown",
            updated_at=None,
            error="",
        )
