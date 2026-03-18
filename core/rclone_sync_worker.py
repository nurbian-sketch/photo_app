#!/usr/bin/env python3
"""
core/rclone_sync_worker.py

Standalone worker synchronizacji rclone.
Uruchamiany jako odłączony subprocess przez SessionRunner.
Argumenty: <session_path> <rclone_remote> <rclone_dest>

Sekwencja:
  1. Zapisuje sync_status.json → "running"
  2. rclone copy <session_path>/ <remote>:<dest>/<folder_name>/
     --exclude sync_status.json --exclude sync_complete
  3. Tworzy lokalny sync_complete (pusty plik)
  4. rclone copy sync_complete → remote (marker "wszystkie zdjęcia dotarły")
  5. Zapisuje sync_status.json → "done" / "failed"
"""
import json
import os
import subprocess
import sys
from datetime import datetime

STATUS_FILE  = "sync_status.json"
MARKER_FILE  = "sync_complete"


def _write_status(session_path: str, status: str, error: str = "") -> None:
    data = {
        "status":       status,          # running | done | failed
        "updated_at":   datetime.now().isoformat(),
        "session_path": session_path,
        "error":        error,
    }
    path = os.path.join(session_path, STATUS_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"[sync_worker] Błąd zapisu {STATUS_FILE}: {e}", file=sys.stderr)


def main():
    if len(sys.argv) != 4:
        print("Użycie: rclone_sync_worker.py <session_path> <remote> <dest>",
              file=sys.stderr)
        sys.exit(1)

    session_path   = sys.argv[1]
    rclone_remote  = sys.argv[2]
    rclone_dest    = sys.argv[3]

    folder_name = os.path.basename(session_path.rstrip("/"))
    dest        = f"{rclone_remote}:{rclone_dest}/{folder_name}"
    marker_path = os.path.join(session_path, MARKER_FILE)

    _write_status(session_path, "running")

    # Krok 1: kopiuj zdjęcia (bez plików statusowych i markera)
    cmd_photos = [
        "rclone", "copy",
        session_path + "/",
        dest + "/",
        "--exclude", STATUS_FILE,
        "--exclude", MARKER_FILE,
        "--progress",
    ]

    try:
        result = subprocess.run(cmd_photos, capture_output=True, text=True)
        if result.returncode != 0:
            err = result.stderr.strip() or f"kod {result.returncode}"
            _write_status(session_path, "failed", err)
            print(f"[sync_worker] rclone copy FAIL: {err}", file=sys.stderr)
            sys.exit(1)
    except FileNotFoundError:
        _write_status(session_path, "failed", "rclone nie znaleziony w PATH")
        sys.exit(1)

    # Krok 2: utwórz lokalny marker
    try:
        with open(marker_path, "w") as f:
            f.write(datetime.now().isoformat())
    except OSError as e:
        _write_status(session_path, "failed", f"marker write error: {e}")
        sys.exit(1)

    # Krok 3: wyślij marker na remote
    cmd_marker = [
        "rclone", "copyto",
        marker_path,
        f"{dest}/{MARKER_FILE}",
    ]
    try:
        result = subprocess.run(cmd_marker, capture_output=True, text=True)
        if result.returncode != 0:
            # Zdjęcia dotarły — marker to tylko bonus, nie przerywamy
            print(f"[sync_worker] marker upload WARN: {result.stderr.strip()}",
                  file=sys.stderr)
    except FileNotFoundError:
        pass

    _write_status(session_path, "done")
    print(f"[sync_worker] sync done: {session_path} → {dest}", flush=True)


if __name__ == "__main__":
    main()
