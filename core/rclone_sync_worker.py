#!/usr/bin/env python3
"""
core/rclone_sync_worker.py

Standalone worker synchronizacji rclone.
Uruchamiany jako odłączony subprocess przez SessionRunner.
Argumenty: <cloud_dir> <rclone_remote> <rclone_dest>

Synchronizuje cały katalog cloud/ do remote — local jest źródłem prawdy:
  rclone sync <cloud_dir>/ <remote>:<dest>/
  --exclude sync_status.json

Usunięcie folderu lokalnie → znika z remote przy następnym sync.
Retry z backoffem do skutku.
Opóźnienia: 30s, 60s, 2min, 5min, 10min (potem stale co 10min).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

STATUS_FILE  = "sync_status.json"   # lokalny — NIE wysyłany na remote
MARKER_FILE  = "sync_complete"       # wysyłany na remote — sygnał dla skryptów
RETRY_DELAYS = [30, 60, 120, 300, 600]


def _check_space(remote: str, dest: str, warn_mb: int) -> tuple[bool, int]:
    """
    Sprawdza wolne miejsce na remote przez `rclone about`.
    Zwraca (warning, free_mb). free_mb=-1 gdy nie można sprawdzić.
    """
    try:
        result = subprocess.run(
            ["rclone", "about", f"{remote}:", "--json"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            return False, -1
        data    = json.loads(result.stdout)
        free_b  = data.get("free", -1)
        if free_b < 0:
            return False, -1
        free_mb = free_b // (1024 * 1024)
        return free_mb < warn_mb, free_mb
    except Exception:
        return False, -1


def _write_status(cloud_dir: str, status: str, error: str = "",
                  free_mb: int = -1) -> None:
    data = {
        "status":     status,   # running | done | warning
        "updated_at": datetime.now().isoformat(),
        "pid":        os.getpid(),
        "free_mb":    free_mb,
        "error":      error,
    }
    path = os.path.join(cloud_dir, STATUS_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"[sync_worker] Błąd zapisu {STATUS_FILE}: {e}", file=sys.stderr)


def _has_jpeg_files(session_path: str) -> bool:
    """Sprawdza czy w katalogu sesji lub podkatalogu jpg/ są pliki JPEG."""
    jpg_extensions = (".jpg", ".jpeg")
    try:
        for f in os.scandir(session_path):
            if f.is_file() and f.name.lower().endswith(jpg_extensions):
                return True
        jpg_subdir = os.path.join(session_path, "jpg")
        if os.path.isdir(jpg_subdir):
            for f in os.scandir(jpg_subdir):
                if f.is_file() and f.name.lower().endswith(jpg_extensions):
                    return True
        developed_subdir = os.path.join(session_path, "developed")
        if os.path.isdir(developed_subdir):
            for f in os.scandir(developed_subdir):
                if f.is_file() and f.name.lower().endswith(jpg_extensions):
                    return True
    except OSError:
        pass
    return False


def _write_markers(cloud_dir: str) -> None:
    """
    Po udanym sync zapisuje w każdym podfolderze sesji:
      - sync_status + synced_at w session_summary.json
      - sync_complete (zostanie wgrany na remote w drugim przebiegu rclone)
    Pomija sesje z flagą .developing lub .develop_error.
    """
    now = datetime.now().isoformat()
    now_fmt = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        for entry in os.scandir(cloud_dir):
            if not entry.is_dir():
                continue
            # Pomiń gdy developer jeszcze pracuje
            if os.path.exists(os.path.join(entry.path, ".developing")):
                continue
            # Pomiń gdy development zakończył się błędami
            if os.path.exists(os.path.join(entry.path, ".develop_error")):
                print(
                    f"[sync_worker] Błędy developmentu w {entry.name} — pomijam sync_complete",
                    flush=True,
                )
                continue
            # Sprawdź czy w sesji są pliki JPG
            if not _has_jpeg_files(entry.path):
                print(
                    f"[sync_worker] Brak JPG w {entry.name} — pomijam sync_complete",
                    flush=True,
                )
                continue

            try:
                # Zaktualizuj session_summary.json
                summary_path = os.path.join(entry.path, "session_summary.json")
                if os.path.exists(summary_path):
                    try:
                        with open(summary_path, encoding="utf-8") as f:
                            data = json.load(f)
                        data["sync_status"] = "done"
                        data["synced_at"]   = now_fmt
                        with open(summary_path, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2, ensure_ascii=False)
                    except Exception as exc:
                        print(f"[sync_worker] Błąd zapisu summary {entry.name}: {exc}",
                              file=sys.stderr, flush=True)
                # Zapisz sync_complete
                with open(os.path.join(entry.path, MARKER_FILE), "w", encoding="utf-8") as f:
                    f.write(now)
            except OSError:
                pass
    except OSError:
        pass


def _run_sync(cloud_dir: str, remote: str, dest: str) -> tuple[bool, str]:
    """Wykonuje rclone sync. Zwraca (sukces, komunikat_błędu)."""
    cmd = [
        "rclone", "sync",
        cloud_dir + "/",
        f"{remote}:{dest}/",
        "--max-depth", "2",
        "--include", "*.jpg",
        "--include", "*.JPG",
        "--include", "sync_complete",
        "--delete-excluded",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            err = result.stderr.strip() or f"rclone exit code {result.returncode}"
            return False, err
        return True, ""
    except FileNotFoundError:
        return False, "rclone not found in PATH"


def main():
    if len(sys.argv) != 4:
        print("Użycie: rclone_sync_worker.py <cloud_dir> <remote> <dest>",
              file=sys.stderr)
        sys.exit(1)

    cloud_dir = sys.argv[1]
    remote    = sys.argv[2]
    dest      = sys.argv[3]

    settings = __import__('PyQt6.QtCore', fromlist=['QSettings']).QSettings(
        "Grzeza", "SessionsAssistant"
    )
    warn_mb = settings.value("rclone/warn_free_mb", 500, type=int)

    # Space check przed pierwszą próbą
    space_warn, free_mb = _check_space(remote, dest, warn_mb)
    if space_warn:
        print(
            f"[sync_worker] OSTRZEŻENIE: mało miejsca na GDrive — {free_mb} MB wolne",
            file=sys.stderr, flush=True,
        )

    attempt = 0

    while True:
        _write_status(cloud_dir, "running", free_mb=free_mb)

        # Krok 1: synchronizuj zdjęcia
        ok, err = _run_sync(cloud_dir, remote, dest)

        if ok:
            # Krok 2: zapisz markery lokalnie (sync_status.json + sync_complete)
            _write_markers(cloud_dir)
            # Krok 3: drugi sync — wgrywa sync_complete na remote
            _run_sync(cloud_dir, remote, dest)
            _write_status(cloud_dir, "done", free_mb=free_mb)
            print(f"[sync_worker] sync done: {cloud_dir} → {remote}:{dest}", flush=True)
            break

        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        _write_status(cloud_dir, "warning", err, free_mb=free_mb)
        print(
            f"[sync_worker] próba {attempt + 1} nieudana: {err} — retry za {delay}s",
            file=sys.stderr, flush=True,
        )
        attempt += 1
        time.sleep(delay)


if __name__ == "__main__":
    main()
