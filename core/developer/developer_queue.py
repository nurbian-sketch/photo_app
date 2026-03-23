"""
developer_queue.py — persystentna kolejka zadań developera.

Plik JSON: ~/.config/SessionsAssistant/developer_queue.json
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Lokalizacja pliku kolejki
QUEUE_PATH = Path("~/.config/SessionsAssistant/developer_queue.json").expanduser()

# Dozwolone stany wpisu
STATUS_PENDING    = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE       = "done"
STATUS_ERROR      = "error"


class DeveloperQueue:
    """
    Zarządza persystentną kolejką zadań wywołania RAW.

    Struktura wpisu:
    {
        "session_path": str,
        "preset": str,           # nazwa presetu (bez .xmp)
        "kelvin": int | None,    # 0=EXIF, None=z presetu, N>0=konkretna wartość
        "status": str,           # pending | processing | done | error
        "total": int,
        "processed": int,
        "error_msg": str,
        "worker_pid": int | None
    }
    """

    def __init__(self):
        self._entries: list[dict] = []
        self.load()

    # ── PERSISTENCJA ─────────────────────────────────────────────────────────

    def load(self) -> None:
        """Wczytuje kolejkę z pliku JSON. Tworzy pusty plik jeśli nie istnieje."""
        if not QUEUE_PATH.exists():
            QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._entries = []
            return
        try:
            self._entries = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning(f"Nie można wczytać kolejki: {exc} — zaczynam od pustej")
            self._entries = []

    def save(self) -> None:
        """Zapisuje kolejkę do pliku JSON."""
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            QUEUE_PATH.write_text(
                json.dumps(self._entries, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as exc:
            log.error(f"Nie można zapisać kolejki: {exc}")

    # ── OPERACJE ──────────────────────────────────────────────────────────────

    def add(self, session_path: str, preset: str, kelvin: int | None) -> None:
        """Dodaje nowe zadanie do kolejki (status=pending)."""
        self.load()
        entry = {
            "session_path": str(session_path),
            "preset":       preset,
            "kelvin":       kelvin,
            "status":       STATUS_PENDING,
            "total":        0,
            "processed":    0,
            "error_msg":    "",
            "worker_pid":   None,
        }
        self._entries.append(entry)
        self.save()
        log.debug(f"Dodano do kolejki: {session_path} preset={preset} kelvin={kelvin}")

    def get_pending(self) -> list[dict]:
        """Zwraca listę wpisów ze statusem pending."""
        self.load()
        return [e for e in self._entries if e["status"] == STATUS_PENDING]

    def update(self, session_path: str, **kwargs) -> None:
        """
        Aktualizuje wpis o podanej session_path.
        Obsługuje: status, total, processed, error_msg, worker_pid.
        """
        self.load()
        for entry in self._entries:
            if entry["session_path"] == str(session_path):
                entry.update(kwargs)
                break
        else:
            log.warning(f"Nie znaleziono wpisu do aktualizacji: {session_path}")
        self.save()

    def get_pending_count(self) -> int:
        """Zwraca liczbę zadań pending lub processing."""
        self.load()
        return sum(
            1 for e in self._entries
            if e["status"] in (STATUS_PENDING, STATUS_PROCESSING)
        )

    def get_all(self) -> list[dict]:
        """Zwraca wszystkie wpisy (po odświeżeniu z dysku)."""
        self.load()
        return list(self._entries)

    def retry_errors(self) -> int:
        """Resetuje wszystkie wpisy error → pending. Zwraca liczbę zresetowanych."""
        self.load()
        count = 0
        for entry in self._entries:
            if entry["status"] == STATUS_ERROR:
                entry["status"]     = STATUS_PENDING
                entry["error_msg"]  = ""
                entry["processed"]  = 0
                entry["worker_pid"] = None
                count += 1
        if count:
            self.save()
        return count
