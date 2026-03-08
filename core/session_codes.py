"""
core/session_codes.py

Rejestr kodów sesji — zapis, odczyt, czyszczenie wygasłych wpisów.
Format JSON: { "ABC123": { "path": "/...", "created_at": "2026-03-08T12:00:00" } }
"""
import os
import json
import random
import string
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Ścieżka do rejestru
_REGISTRY_PATH = os.path.expanduser("~/.local/share/photo_app/session_codes.json")

# Alfabet kodu: duże litery + cyfry, bez mylących znaków (0/O, 1/I)
_ALPHABET = (string.ascii_uppercase + string.digits).translate(
    str.maketrans("", "", "OI01")
)


def generate_code() -> str:
    """Generuje unikalny 6-znakowy kod sesji."""
    registry = _load()
    while True:
        code = "".join(random.choices(_ALPHABET, k=6))
        if code not in registry:
            return code


def register(code: str, session_path: str) -> None:
    """Zapisuje kod sesji i ścieżkę do folderu zdjęć."""
    registry = _load()
    registry[code] = {
        "path":       session_path,
        "created_at": datetime.now().isoformat(),
    }
    _save(registry)
    logger.info(f"Zarejestrowano kod sesji: {code} → {session_path}")


def resolve(code: str, expiry_days: int) -> str | None:
    """
    Zwraca ścieżkę do folderu sesji dla danego kodu.
    Zwraca None jeśli kod nie istnieje lub wygasł.
    """
    registry = _load()
    entry = registry.get(code.upper())
    if not entry:
        return None
    created = datetime.fromisoformat(entry["created_at"])
    if datetime.now() - created > timedelta(days=expiry_days):
        logger.info(f"Kod {code} wygasł ({expiry_days} dni)")
        return None
    return entry["path"]


def cleanup(expiry_days: int) -> int:
    """
    Usuwa wygasłe wpisy z rejestru.
    Zwraca liczbę usuniętych wpisów.
    """
    registry = _load()
    cutoff = datetime.now() - timedelta(days=expiry_days)
    before = len(registry)
    registry = {
        code: entry for code, entry in registry.items()
        if datetime.fromisoformat(entry["created_at"]) > cutoff
    }
    removed = before - len(registry)
    if removed:
        _save(registry)
        logger.info(f"Cleanup: usunięto {removed} wygasłych kodów")
    return removed


def _load() -> dict:
    """Wczytuje rejestr z dysku."""
    if not os.path.exists(_REGISTRY_PATH):
        return {}
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Błąd wczytywania rejestru: {e}")
        return {}


def _save(registry: dict) -> None:
    """Zapisuje rejestr na dysk."""
    os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)
    try:
        with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Błąd zapisu rejestru: {e}")
