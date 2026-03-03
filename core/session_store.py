"""
Warstwa persystencji sesji fotograficznych.
Odpowiada za: zapis/odczyt session.json, skanowanie historii,
czyszczenie starych folderów klientów (>365 dni).
Brak zależności od GUI.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional

from core.session_context import SessionContext, SessionMode, SessionSummary

logger = logging.getLogger(__name__)

SESSION_FILE = "session_summary.json"
CLIENT_RETENTION_DAYS = 365


class SessionStore:
    """Odczyt i zapis metadanych sesji na dysku."""

    def __init__(self, base_dir: str):
        """
        Args:
            base_dir: korzeń katalogu sesji (np. ~/Obrazy/sessions)
        """
        self.base_dir = os.path.expanduser(base_dir)

    # ─────────────────────────── ZAPIS

    def save(self, context: SessionContext) -> bool:
        """
        Zapisuje session.json w katalogu sesji.
        Tworzy katalog jeśli nie istnieje.
        Zwraca True przy sukcesie.
        """
        if not context.session_path:
            # PRIVATE — brak folderu, zapisujemy do base_dir/.private_log/
            target_dir = os.path.join(self.base_dir, ".private_log")
        else:
            target_dir = context.session_path

        try:
            os.makedirs(target_dir, exist_ok=True)
            path = os.path.join(target_dir, SESSION_FILE)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(context.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"SessionStore: zapisano {path}")
            return True
        except OSError as e:
            logger.error(f"SessionStore: błąd zapisu {target_dir}: {e}")
            return False

    def update_sync_status(self, context: SessionContext, status: str) -> bool:
        """Aktualizuje tylko pole sync_status w istniejącym session.json."""
        context.sync_status = status
        return self.save(context)

    # ─────────────────────────── ODCZYT

    def load(self, session_path: str) -> Optional[SessionContext]:
        """
        Wczytuje SessionContext z katalogu sesji.
        Zwraca None jeśli plik nie istnieje lub jest uszkodzony.
        """
        path = os.path.join(session_path, SESSION_FILE)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return SessionContext.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"SessionStore: błąd odczytu {path}: {e}")
            return None

    # ─────────────────────────── HISTORIA

    def list_sessions(self, include_private: bool = False) -> list[SessionContext]:
        """
        Skanuje base_dir i zwraca listę sesji posortowaną od najnowszej.
        Pomija ukryte foldery (kropka) oraz foldery bez session.json.
        """
        results = []

        if not os.path.isdir(self.base_dir):
            return results

        for entry in os.scandir(self.base_dir):
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                if not include_private:
                    continue
                # .private_log → wczytaj
            ctx = self.load(entry.path)
            if ctx is None:
                continue
            if ctx.mode == SessionMode.PRIVATE and not include_private:
                continue
            results.append(ctx)

        results.sort(key=lambda c: c.started_at, reverse=True)
        return results

    def last_session(self) -> Optional[SessionContext]:
        """Zwraca ostatnią sesję (CLIENT lub HOME) lub None."""
        sessions = self.list_sessions(include_private=False)
        return sessions[0] if sessions else None

    # ─────────────────────────── CZYSZCZENIE

    def cleanup_old_client_sessions(
        self,
        dry_run: bool = False,
        retention_days: int = CLIENT_RETENTION_DAYS,
    ) -> list[str]:
        """
        Usuwa lokalne foldery sesji CLIENT starsze niż retention_days.
        HOME i PRIVATE są pomijane.
        dry_run=True — tylko raportuje, nic nie usuwa.
        Zwraca listę usuniętych (lub przewidzianych do usunięcia) ścieżek.
        """
        cutoff = datetime.now() - timedelta(days=retention_days)
        removed = []

        for ctx in self.list_sessions(include_private=False):
            if ctx.mode != SessionMode.CLIENT:
                continue
            if ctx.started_at >= cutoff:
                continue

            path = ctx.session_path
            if not path or not os.path.isdir(path):
                continue

            removed.append(path)
            if dry_run:
                logger.info(f"SessionStore [dry_run]: usunąłbym {path}")
            else:
                try:
                    shutil.rmtree(path)
                    logger.info(f"SessionStore: usunięto stary folder {path}")
                except OSError as e:
                    logger.error(f"SessionStore: błąd usuwania {path}: {e}")
                    removed.pop()

        return removed

    # ─────────────────────────── POMOCNICZE

    def session_exists(self, session_id: str) -> bool:
        """Sprawdza czy folder sesji już istnieje."""
        path = os.path.join(self.base_dir, session_id)
        return os.path.isdir(path)

    def get_session_path(self, session_id: str) -> str:
        """Zwraca pełną ścieżkę folderu sesji."""
        return os.path.join(self.base_dir, session_id)

    def stats(self) -> dict:
        """
        Statystyki bazy sesji.
        Zwraca dict: total, by_mode, oldest, newest.
        """
        sessions = self.list_sessions(include_private=True)
        if not sessions:
            return {"total": 0, "by_mode": {}, "oldest": None, "newest": None}

        by_mode: dict[str, int] = {}
        for ctx in sessions:
            key = ctx.mode.value
            by_mode[key] = by_mode.get(key, 0) + 1

        return {
            "total":   len(sessions),
            "by_mode": by_mode,
            "oldest":  sessions[-1].started_at.isoformat(),
            "newest":  sessions[0].started_at.isoformat(),
        }
