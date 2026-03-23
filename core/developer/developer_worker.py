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

# ── ŚCIEŻKI ──────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = Path(__file__).parent
PRESETS_DIR  = _SCRIPT_DIR.parent.parent / "presets"
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


def _find_preset_xmp(preset_name: str) -> Path | None:
    """
    Szuka pliku presetu: najpierw presets/user/, potem presets/.
    Zwraca Path lub None.
    """
    user_xmp = PRESETS_DIR / "user" / f"{preset_name}.xmp"
    if user_xmp.exists():
        return user_xmp
    base_xmp = PRESETS_DIR / f"{preset_name}.xmp"
    if base_xmp.exists():
        return base_xmp
    return None


def _wait_if_liveview() -> None:
    """Blokuje wykonanie gdy liveview.lock istnieje."""
    while LV_LOCK_PATH.exists():
        print("[dev_worker] LiveView aktywny — pauza...", flush=True)
        time.sleep(LV_POLL_INTERVAL)


def _reorganize_session(session_dir: Path) -> list[Path]:
    """
    Przenosi pliki RAW do raw/ i sparowane JPEG do jpg/.
    Zwraca listę plików RAW w katalogu raw/.
    """
    raw_files = [
        f for f in session_dir.iterdir()
        if f.is_file() and f.suffix.lower() in RAW_EXT
    ]

    raw_dir = session_dir / "raw"
    jpg_dir = session_dir / "jpg"

    if not raw_files:
        # RAW-y mogły zostać przeniesione przez poprzednią (nieudaną) próbę
        if raw_dir.is_dir():
            already_moved = sorted(
                f for f in raw_dir.iterdir()
                if f.is_file() and f.suffix.lower() in RAW_EXT
            )
            if already_moved:
                print(f"[dev_worker] Retry: znaleziono {len(already_moved)} RAW w raw/", flush=True)
                return already_moved
        return []

    raw_dir.mkdir(exist_ok=True)
    # jpg_dir tworzymy tylko gdy faktycznie są sparowane JPEG

    moved_raws = []
    for raw in sorted(raw_files):
        # Szukaj sparowanego JPEG (ta sama bazowa nazwa)
        paired_jpg = session_dir / (raw.stem + ".jpg")
        if paired_jpg.exists():
            jpg_dir.mkdir(exist_ok=True)          # lazy create
            dest_jpg = jpg_dir / paired_jpg.name
            paired_jpg.rename(dest_jpg)
            print(f"[dev_worker] JPEG → jpg/{paired_jpg.name}", flush=True)

        dest_raw = raw_dir / raw.name
        raw.rename(dest_raw)
        moved_raws.append(dest_raw)
        print(f"[dev_worker] RAW → raw/{raw.name}", flush=True)

    return moved_raws


def _develop_file_auto(raw: Path, out_jpeg: Path, kelvin: int | None) -> bool:
    """Wywołanie bez presetu XMP — darktable auto (ignoruje kelvin)."""
    _wait_if_liveview()
    from core.developer.cli_developer import export_raw_fallback
    return export_raw_fallback(raw, out_jpeg)


def _develop_file(raw: Path, preset_xmp: Path, out_jpeg: Path,
                  kelvin: int | None) -> bool:
    """
    Wywołuje cli_developer.py dla jednego pliku RAW przez nice +10.
    Zwraca True gdy JPEG powstał.
    """
    _wait_if_liveview()

    cmd = [
        "nice", "-n", "10",
        sys.executable, str(CLI_DEV_PATH),
        str(raw), str(preset_xmp), str(out_jpeg),
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

    # Znajdź preset XMP (lub ustaw None dla trybu auto)
    if preset == _AUTO_PRESET:
        preset_xmp = None
    else:
        preset_xmp = _find_preset_xmp(preset)
        if preset_xmp is None:
            print(f"[dev_worker] Nie znaleziono presetu: {preset}", file=sys.stderr, flush=True)
            _update_entry(session_path, status="error",
                          error_msg=f"Preset nie znaleziony: {preset}")
            return

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

        errors = []
        for raw in raw_files:
            out_jpeg = session_dir / (raw.stem + ".jpg")
            if preset_xmp is None:
                ok = _develop_file_auto(raw, out_jpeg, kelvin)
            else:
                ok = _develop_file(raw, preset_xmp, out_jpeg, kelvin)
            if ok:
                processed += 1
                print(f"[dev_worker] [{processed}/{total}] ✔ {raw.name}", flush=True)
            else:
                errors.append(raw.name)
                print(f"[dev_worker] [{processed}/{total}] ✘ {raw.name}", file=sys.stderr, flush=True)
            _update_entry(session_path, processed=processed)

        if errors:
            _update_entry(
                session_path, status="error",
                error_msg=f"Błędy ({len(errors)}): {', '.join(errors[:3])}"
            )
        else:
            _update_entry(session_path, status="done")

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
