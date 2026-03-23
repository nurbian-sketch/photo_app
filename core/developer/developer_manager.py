"""
core/developer/developer_manager.py

Interfejs UI → developer pipeline.
Dodaje zadania do kolejki i uruchamia developer_worker jako odłączony subprocess.
"""

import os
import sys
import subprocess
from pathlib import Path

from core.developer.developer_queue import DeveloperQueue

# Ścieżka do workera
_WORKER_PATH = Path(__file__).parent / "developer_worker.py"
_PID_PATH    = Path("~/.config/SessionsAssistant/developer_worker.pid").expanduser()


def _worker_alive(pid: int | None) -> bool:
    """Sprawdza czy proces o danym PID nadal działa."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _read_worker_pid() -> int | None:
    """Odczytuje PID workera z pliku PID. Zwraca None gdy brak lub błąd."""
    try:
        return int(_PID_PATH.read_text().strip())
    except Exception:
        return None


class DeveloperManager:
    """
    Interfejs dla UI do zarządzania pipeline wywołania RAW.

    Użycie:
        manager = DeveloperManager()
        manager.start(session_path, preset="white_bg", kelvin=0)
        state, processed, total = manager.get_status()
    """

    def __init__(self):
        self._queue = DeveloperQueue()

    def start(self, session_path: str, preset: str, kelvin: int | None) -> None:
        """
        Dodaje sesję do kolejki i uruchamia workera jeśli nie działa.

        kelvin=0    → WB z EXIF
        kelvin=None → WB z presetu XMP
        kelvin>0    → konkretna wartość Kelvin
        """
        self._queue.add(session_path, preset, kelvin)

        if not self.is_worker_alive():
            self._launch_worker()

    def is_worker_alive(self) -> bool:
        """Sprawdza czy developer_worker aktualnie działa."""
        pid = _read_worker_pid()
        return _worker_alive(pid)

    def get_pending_count(self) -> int:
        """Zwraca liczbę zadań oczekujących lub przetwarzanych."""
        return self._queue.get_pending_count()

    def get_status(self) -> tuple[str, int, int]:
        """
        Zwraca (state, processed, total):
          state: 'inactive' | 'active' | 'error'
          processed: suma przetworzonych plików
          total: suma wszystkich plików
        """
        entries = self._queue.get_all()
        active_entries = [
            e for e in entries
            if e["status"] in ("pending", "processing")
        ]
        error_entries = [
            e for e in entries
            if e["status"] == "error"
        ]

        if active_entries and self.is_worker_alive():
            processed = sum(e.get("processed", 0) for e in active_entries)
            total     = sum(e.get("total", 0)     for e in active_entries)
            return "active", processed, total

        if error_entries and not active_entries:
            # Ostatni błąd — zwróć komunikat przez total jako 0
            return "error", 0, 0

        return "inactive", 0, 0

    def get_last_error(self) -> str:
        """Zwraca komunikat ostatniego błędu (jeśli istnieje)."""
        entries = self._queue.get_all()
        for e in reversed(entries):
            if e["status"] == "error" and e.get("error_msg"):
                return e["error_msg"]
        return ""

    def retry_errors(self) -> int:
        """Resetuje błędne sesje do pending i uruchamia workera. Zwraca liczbę zresetowanych."""
        count = self._queue.retry_errors()
        if count > 0 and not self.is_worker_alive():
            self._launch_worker()
        return count

    def _launch_worker(self) -> None:
        """Uruchamia developer_worker jako odłączony subprocess."""
        try:
            subprocess.Popen(
                [sys.executable, str(_WORKER_PATH)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,   # odłączony — przeżywa zamknięcie app
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(f"Nie można uruchomić developer_worker: {exc}")
