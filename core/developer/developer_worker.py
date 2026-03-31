#!/usr/bin/env python3
"""
core/developer/developer_worker.py

Standalone worker wywołania RAW. Uruchamiany jako odłączony subprocess
przez DeveloperManager. Przeżywa zamknięcie aplikacji (start_new_session=True).

Brak argumentów — odczytuje zadania z developer_queue.json.
"""

import os
import subprocess
import sys
import time
import json
from pathlib import Path
from datetime import datetime

# ── ŚCIEŻKI ──────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = Path(__file__).parent
CLI_DEV_PATH = _SCRIPT_DIR / "cli_developer.py"

CONFIG_DIR   = Path("~/.config/SessionsAssistant").expanduser()
QUEUE_PATH   = CONFIG_DIR / "developer_queue.json"
PID_PATH     = CONFIG_DIR / "developer_worker.pid"
LV_LOCK_PATH = CONFIG_DIR / "liveview.lock"

# Rozszerzenia RAW
RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".dng"}

# Preset automatyczny — darktable bez XMP
_AUTO_PRESET = "__auto__"

# Pauza gdy LiveView aktywny (sekundy)
LV_POLL_INTERVAL = 5


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _load_queue() -> list[dict]:
    """Wczytuje kolejkę z JSON. Zwraca pustą listę przy błędzie."""
    try:
        return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_queue(entries: list[dict]) -> None:
    """Zapisuje kolejkę do JSON."""
    try:
        QUEUE_PATH.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as exc:
        print(f"[dev_worker] Błąd zapisu kolejki: {exc}", file=sys.stderr, flush=True)


def _update_entry(session_path: str, **kwargs) -> None:
    """Aktualizuje wpis o podanej session_path w pliku kolejki."""
    entries = _load_queue()
    for e in entries:
        if e["session_path"] == session_path:
            e.update(kwargs)
            break
    _save_queue(entries)


def _wait_if_liveview() -> None:
    """Blokuje wykonanie gdy liveview.lock istnieje."""
    while LV_LOCK_PATH.exists():
        print("[dev_worker] LiveView aktywny — pauza...", flush=True)
        time.sleep(LV_POLL_INTERVAL)


def _wait_if_darktable_gui(poll: int = 10) -> None:
    """Blokuje wykonanie gdy darktable GUI jest uruchomione (trzyma lock na data.db)."""
    while True:
        result = subprocess.run(["pgrep", "-x", "darktable"], capture_output=True)
        if result.returncode != 0:
            break
        print(f"[dev_worker] darktable GUI aktywny — pauza {poll}s...", flush=True)
        time.sleep(poll)


def _update_summary(session_dir: Path, preset: str, raw_files: list[Path],
                    errors: list[str], time_sec: float) -> None:
    """Aktualizuje session_summary.json po zakończeniu developmentu."""
    path = session_dir / "session_summary.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    style = None if preset == _AUTO_PRESET else preset
    n = len(raw_files)
    developed_count = n - len(errors)
    data["develop_style"]         = style
    data["developed_count"]       = developed_count
    data["total_raw"]             = n
    data["develop_errors"]        = errors if errors else []
    data["develop_time_sec"]      = round(time_sec, 1)
    data["develop_sec_per_photo"] = round(time_sec / n, 1) if n else 0

    try:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as exc:
        print(f"[dev_worker] Błąd zapisu summary: {exc}", file=sys.stderr, flush=True)


def _reorganize_session(session_dir: Path) -> list[Path]:
    """
    Reorganizuje pliki sesji:
      - tylko JPG  → bez zmian, zwraca []
      - tylko RAW  → RAW → raw/, wywołane JPG będą w root
      - RAW + JPG  → RAW → raw/, istniejące JPG → jpg/, wywołane JPG w root
    """
    raw_dir = session_dir / "raw"
    jpg_dir = session_dir / "jpg"

    raw_files = sorted(
        f for f in session_dir.iterdir()
        if f.is_file() and f.suffix.lower() in RAW_EXT
    )
    jpg_files = sorted(
        f for f in session_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg")
    )

    if not raw_files:
        # Retry: RAW-y mogły być przeniesione przez poprzednią próbę
        if raw_dir.is_dir():
            already_moved = sorted(
                f for f in raw_dir.iterdir()
                if f.is_file() and f.suffix.lower() in RAW_EXT
            )
            if already_moved:
                print(f"[dev_worker] Retry: znaleziono {len(already_moved)} RAW w raw/", flush=True)
                return already_moved
        return []

    # Przenieś RAW do raw/
    raw_dir.mkdir(exist_ok=True)
    moved_raws = []
    for raw in raw_files:
        dest = raw_dir / raw.name
        raw.rename(dest)
        moved_raws.append(dest)
        print(f"[dev_worker] RAW → raw/{raw.name}", flush=True)

    # Przenieś istniejące JPG do jpg/ (tylko gdy są razem z RAW)
    if jpg_files:
        jpg_dir.mkdir(exist_ok=True)
        for jpg in jpg_files:
            dest = jpg_dir / jpg.name
            jpg.rename(dest)
            print(f"[dev_worker] JPG → jpg/{jpg.name}", flush=True)

    return moved_raws


def _develop_file(raw: Path, preset: str, out_jpeg: Path,
                  kelvin: int | None) -> bool:
    """
    Wywołuje cli_developer.py dla jednego pliku RAW przez nice +10.
    Czeka jeśli LiveView lub darktable GUI aktywne.
    Zwraca True gdy JPEG powstał.
    """
    _wait_if_liveview()
    _wait_if_darktable_gui()

    cmd = [
        "nice", "-n", "10",
        sys.executable, str(CLI_DEV_PATH),
        str(raw), preset, str(out_jpeg),
    ]
    if kelvin is not None:
        cmd += ["--kelvin", str(kelvin)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(
            f"[dev_worker] Błąd {raw.name}: {result.stderr.strip()[:200]}",
            file=sys.stderr, flush=True
        )
    return out_jpeg.exists()


# ── PRZETWARZANIE SESJI ───────────────────────────────────────────────────────

def _trigger_sync_if_cloud(session_dir: Path) -> None:
    """Uruchamia rclone_sync_worker jeśli sesja leży w katalogu cloud/."""
    if "cloud" not in session_dir.parts:
        return
    try:
        from PyQt6.QtCore import QSettings
        s = QSettings("Grzeza", "SessionsAssistant")
        remote = s.value("rclone/remote", "").strip()
        dest   = s.value("rclone/dest",   "Sessions").strip()
        base   = s.value(
            "session/directory",
            str(Path.home() / "Obrazy" / "sessions")
        )
        if not remote:
            print("[dev_worker] rclone nie skonfigurowany — pomijam sync", flush=True)
            return
        cloud_dir   = str(Path(base) / "cloud")
        worker_path = str(_SCRIPT_DIR.parent / "rclone_sync_worker.py")
        subprocess.Popen(
            [sys.executable, worker_path, cloud_dir, remote, dest],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"[dev_worker] Uruchomiono sync: {cloud_dir} → {remote}:{dest}", flush=True)
    except Exception as exc:
        print(f"[dev_worker] Błąd triggera sync: {exc}", file=sys.stderr, flush=True)


def _process_session(entry: dict) -> None:
    """
    Przetwarza jedną sesję z kolejki:
      1. Reorganizuje pliki (raw/ + jpg/)
      2. Ustawia flagę .developing
      3. Wywołuje cli_developer.py per plik
      4. Aktualizuje kolejkę (processed, total)
      5. Usuwa flagę .developing
    """
    session_path = entry["session_path"]
    preset       = entry["preset"]
    kelvin       = entry["kelvin"]   # int lub None

    session_dir  = Path(session_path)
    developing   = session_dir / ".developing"

    print(f"[dev_worker] Sesja: {session_path}  preset={preset}  kelvin={kelvin}", flush=True)

    # preset jest przekazywany bezpośrednio do cli_developer
    # ("__auto__" | "nazwa stylu" | "/ścieżka/plik.dtstyle")

    # Oznacz jako processing
    _update_entry(session_path, status="processing", worker_pid=os.getpid())

    # Flaga .developing
    try:
        developing.touch()
    except OSError as exc:
        print(f"[dev_worker] Nie można ustawić .developing: {exc}", file=sys.stderr, flush=True)

    try:
        # Reorganizacja plików
        raw_files = _reorganize_session(session_dir)
        if not raw_files:
            print(f"[dev_worker] Brak plików RAW w sesji: {session_path}", flush=True)
            _update_entry(session_path, status="done", total=0, processed=0)
            return

        total = len(raw_files)
        processed = 0
        _update_entry(session_path, total=total, processed=0)

        developed_dir = session_dir / "developed"
        developed_dir.mkdir(exist_ok=True)

        errors = []
        t_start = time.time()
        for raw in raw_files:
            out_jpeg = developed_dir / (raw.stem + ".jpg")
            ok = _develop_file(raw, preset, out_jpeg, kelvin)
            if ok:
                processed += 1
                print(f"[dev_worker] [{processed}/{total}] ✔ {raw.name}", flush=True)
            else:
                errors.append(raw.name)
                print(f"[dev_worker] [{processed}/{total}] ✘ {raw.name}", file=sys.stderr, flush=True)
            _update_entry(session_path, processed=processed)
        t_elapsed = time.time() - t_start

        # Zapisz wyniki do session_summary.json
        _update_summary(session_dir, preset, raw_files, errors, t_elapsed)

        if errors:
            # Flaga blokująca sync — rclone pominie tę sesję
            try:
                (session_dir / ".develop_error").touch()
            except OSError:
                pass
            _update_entry(
                session_path, status="error",
                error_msg=f"Błędy ({len(errors)}): {', '.join(errors[:3])}"
            )
        else:
            # Usuń flagę błędu jeśli poprzedni retry był nieudany
            try:
                (session_dir / ".develop_error").unlink(missing_ok=True)
            except OSError:
                pass
            _update_entry(session_path, status="done")
            # Trigger sync jeśli sesja jest w katalogu cloud/
            _trigger_sync_if_cloud(session_dir)

        print(f"[dev_worker] Sesja zakończona: {processed}/{total} OK", flush=True)

    finally:
        # Zawsze usuń flagę .developing
        try:
            if developing.exists():
                developing.unlink()
        except OSError:
            pass


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Zapisz PID workera
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))

    print(f"[dev_worker] Start PID={os.getpid()}", flush=True)

    try:
        entries = _load_queue()
        pending = [e for e in entries if e["status"] == "pending"]

        if not pending:
            print("[dev_worker] Brak zadań pending — koniec.", flush=True)
            return

        for entry in pending:
            _process_session(entry)

    finally:
        # Usuń plik PID po zakończeniu
        try:
            PID_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        print("[dev_worker] Worker zakończony.", flush=True)


if __name__ == "__main__":
    main()
