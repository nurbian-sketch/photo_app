#!/usr/bin/env python3
"""
Diagnostyka rclone sync — uruchom bez aplikacji.
Wyświetla: konfigurację, zawartość local, zawartość remote, wynik sync.
"""
import json, os, subprocess, sys
from PyQt6.QtCore import QSettings

s       = QSettings("Grzeza", "SessionsAssistant")
remote  = s.value("rclone/remote", "").strip()
dest    = s.value("rclone/destination", "Sessions").strip()
base    = s.value("session/directory", os.path.expanduser("~/Obrazy/sessions"))
cloud   = os.path.join(base, "cloud")
status  = os.path.join(cloud, "sync_status.json")

print("=== KONFIGURACJA ===")
print(f"  remote:    {remote!r}")
print(f"  dest:      {dest!r}")
print(f"  base_dir:  {base}")
print(f"  cloud_dir: {cloud}")
print(f"  cloud istnieje: {os.path.isdir(cloud)}")
print()

print("=== sync_status.json ===")
if os.path.exists(status):
    print(open(status).read())
else:
    print("  (brak pliku)")
print()

print("=== ZAWARTOŚĆ LOCAL (cloud/) ===")
if os.path.isdir(cloud):
    for root, dirs, files in os.walk(cloud):
        level = root.replace(cloud, "").count(os.sep)
        indent = "  " * level
        print(f"{indent}{os.path.basename(root)}/")
        for f in files:
            size = os.path.getsize(os.path.join(root, f))
            print(f"{indent}  {f}  ({size} B)")
else:
    print("  katalog nie istnieje!")
print()

if not remote:
    print("BŁĄD: brak remote w QSettings — rclone nie skonfigurowany")
    sys.exit(1)

print("=== rclone about (remote) ===")
r = subprocess.run(["rclone", "about", f"{remote}:", "--json"],
                   capture_output=True, text=True)
print(f"  exit code: {r.returncode}")
print(f"  stdout: {r.stdout[:300]}")
print(f"  stderr: {r.stderr[:300]}")
print()

print(f"=== ZAWARTOŚĆ REMOTE ({remote}:{dest}/) ===")
r2 = subprocess.run(["rclone", "ls", f"{remote}:{dest}/"],
                    capture_output=True, text=True)
print(f"  exit code: {r2.returncode}")
print(r2.stdout[:2000] or "  (puste)")
if r2.stderr:
    print(f"  STDERR: {r2.stderr[:500]}")
print()

print("=== TEST SYNC (--dry-run) ===")
cmd = [
    "rclone", "sync",
    cloud + "/",
    f"{remote}:{dest}/",
    "--dry-run", "--verbose",
    "--rmdirs",
    "--exclude", "sync_status.json",
    "--exclude", "*.cr3", "--exclude", "*.CR3",
    "--exclude", "*.cr2", "--exclude", "*.CR2",
    "--exclude", "*.nef", "--exclude", "*.NEF",
    "--exclude", "*.arw", "--exclude", "*.ARW",
    "--exclude", "*.dng", "--exclude", "*.DNG",
]
print("  CMD:", " ".join(cmd))
r3 = subprocess.run(cmd, capture_output=True, text=True)
print(f"  exit code: {r3.returncode}")
print("  STDOUT:", r3.stdout[:3000] or "(brak)")
print("  STDERR:", r3.stderr[:3000] or "(brak)")
