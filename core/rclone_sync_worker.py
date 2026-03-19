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

STATUS_FILE  = "sync_status.json"
RETRY_DELAYS = [30, 60, 120, 300, 600]


def _write_status(cloud_dir: str, status: str, error: str = "") -> None:
    data = {
        "status":     status,   # running | done | warning
        "updated_at": datetime.now().isoformat(),
        "pid":        os.getpid(),
        "error":      error,
    }
    path = os.path.join(cloud_dir, STATUS_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"[sync_worker] Błąd zapisu {STATUS_FILE}: {e}", file=sys.stderr)


def _mark_sessions_synced(cloud_dir: str) -> None:
    """Zapisuje sync_status.json w każdym podfolderze sesji po udanym sync."""
    now = datetime.now().isoformat()
    try:
        for entry in os.scandir(cloud_dir):
            if not entry.is_dir():
                continue
            path = os.path.join(entry.path, STATUS_FILE)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"status": "done", "synced_at": now}, f)
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
        "--exclude", STATUS_FILE,
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

    attempt = 0

    while True:
        _write_status(cloud_dir, "running")

        ok, err = _run_sync(cloud_dir, remote, dest)

        if ok:
            _write_status(cloud_dir, "done")
            _mark_sessions_synced(cloud_dir)
            print(f"[sync_worker] sync done: {cloud_dir} → {remote}:{dest}", flush=True)
            break

        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        _write_status(cloud_dir, "warning", err)
        print(
            f"[sync_worker] próba {attempt + 1} nieudana: {err} — retry za {delay}s",
            file=sys.stderr, flush=True,
        )
        attempt += 1
        time.sleep(delay)


if __name__ == "__main__":
    main()
