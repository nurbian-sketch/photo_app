"""
core/rclone_about_worker.py

QThread sprawdzający wolne miejsce na remote przez `rclone about`.
Uruchamiany przez MainWindow przy starcie, po zakończeniu sesji i co 15 minut.
NIE nadpisuje pola `status` w sync_status.json gdy sync jest w toku (status=running).
"""
import json
import os
import subprocess
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal


class RcloneAboutWorker(QThread):
    """
    Sygnały:
      finished(int) — free_mb (-1 gdy błąd lub brak rclone)
    """

    finished = pyqtSignal(int)

    def __init__(self, remote: str, cloud_dir: str, warn_mb: int, parent=None):
        super().__init__(parent)
        self._remote    = remote
        self._cloud_dir = cloud_dir
        self._warn_mb   = warn_mb

    # ─────────────────────────── QThread

    def run(self):
        free_mb = self._check_space()
        self._update_status_file(free_mb)
        self.finished.emit(free_mb)

    # ─────────────────────────── Prywatne

    def _check_space(self) -> int:
        """Odpytuje rclone about. Zwraca free_mb lub -1 przy błędzie."""
        try:
            result = subprocess.run(
                ["rclone", "about", f"{self._remote}:", "--json"],
                capture_output=True, text=True, timeout=25,
            )
            if result.returncode != 0:
                return -1
            data   = json.loads(result.stdout)
            free_b = data.get("free", -1)
            if free_b < 0:
                return -1
            return free_b // (1024 * 1024)
        except Exception:
            return -1

    def _update_status_file(self, free_mb: int) -> None:
        """
        Aktualizuje free_mb i space_checked_at w sync_status.json.
        Nie nadpisuje pola `status` gdy wynosi 'running'.
        """
        os.makedirs(self._cloud_dir, exist_ok=True)
        path = os.path.join(self._cloud_dir, "sync_status.json")

        # Odczytaj istniejący plik — ostrożnie
        data: dict = {}
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:
            pass

        # Nie resetuj statusu running (sync może właśnie pracować)
        if "status" not in data:
            data["status"] = "ok"

        data["free_mb"]          = free_mb
        data["space_checked_at"] = datetime.now().isoformat()

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass
