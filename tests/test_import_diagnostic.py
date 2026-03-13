#!/usr/bin/env python3
"""
Standalone diagnostic — symuluje _list_new_files z session_runner.
Uruchomienie: python3 test_import_diagnostic.py
"""
import os
os.environ['LANGUAGE'] = 'C'
import time
from datetime import datetime, timedelta
import gphoto2 as gp

SIMULATED_SESSION_START = None  # None = teraz minus 2h

def hr(t): print(f"\n{'─'*60}\n  {t}\n{'─'*60}")

hr("1. POŁĄCZENIE Z APARATEM")
context = gp.Context()
pil = gp.PortInfoList(); pil.load()
al = gp.CameraAbilitiesList(); al.load(context)
cameras = al.detect(pil, context)
if not cameras:
    print("❌ Brak aparatu"); exit(1)
model, port = cameras[0]
print(f"✓ {model}  port={port}")
camera = gp.Camera()
camera.set_abilities(al[al.lookup_model(model)])
camera.set_port_info(pil[pil.lookup_path(port)])
camera.init(context)
print("✓ Połączono")

hr("2. CZAS APARATU vs SYSTEM")
try:
    cfg = camera.get_config(context)
    cam_ts = int(cfg.get_child_by_name("datetime").get_value())
    sys_ts = int(datetime.now().timestamp())
    offset = cam_ts - sys_ts
    print(f"  Aparat : {datetime.fromtimestamp(cam_ts)}  ({cam_ts})")
    print(f"  System : {datetime.fromtimestamp(sys_ts)}  ({sys_ts})")
    print(f"  Offset : {offset}s")
except Exception as e:
    offset = 0; print(f"⚠ błąd: {e}, offset=0")

hr("3. PRÓG FILTROWANIA")
session_start = SIMULATED_SESSION_START or (datetime.now() - timedelta(hours=2))
if SIMULATED_SESSION_START is None:
    print(f"  ⚠ SIMULATED_SESSION_START nie ustawiony — używam teraz-2h")
print(f"  Start sesji    : {session_start}")
session_start_ts = int(session_start.timestamp())
threshold_ts = session_start_ts + offset - 30
print(f"  session_start_ts : {session_start_ts}")
print(f"  + offset {offset:+d}s - bufor 30s = threshold = {threshold_ts}")
print(f"  Próg jako czas : {datetime.fromtimestamp(threshold_ts)}")

hr("4. LISTING KARTY SD")
DCIM = "/store_00020001/DCIM"
try:
    folders = camera.folder_list_folders(DCIM, context)
    print(f"  ✓ {DCIM}  folderów: {folders.count()}")
except gp.GPhoto2Error as e:
    print(f"  ❌ {DCIM} błąd {e.code}")
    DCIM = "/store_00010001/DCIM"
    try:
        folders = camera.folder_list_folders(DCIM, context)
        print(f"  ✓ alt {DCIM}  folderów: {folders.count()}")
    except Exception as e2:
        print(f"  ❌ też błąd: {e2}"); camera.exit(context); exit(1)

if folders.count() == 0:
    print("❌ Brak folderów DCIM"); camera.exit(context); exit(1)

hr("5. PLIKI — ANALIZA MTIME")
include_list = []; all_files = []
for i in range(folders.count()):
    fname = folders.get_name(i)
    fpath = f"{DCIM}/{fname}"
    print(f"\n  📁 {fpath}")
    try:
        files = camera.folder_list_files(fpath, context)
        for j in range(files.count()):
            name = files.get_name(j)
            try:
                info = camera.file_get_info(fpath, name, context)
                mtime = info.file.mtime
                size  = info.file.size
                if mtime == 0:
                    inc = True; flag = "✓ INCLUDE (mtime=0)"
                elif mtime >= threshold_ts:
                    inc = True; flag = f"✓ INCLUDE (mtime={mtime} >= {threshold_ts})"
                else:
                    inc = False; d = threshold_ts - mtime
                    flag = f"✗ EXCLUDE (za stary o {d}s = {d//60}min)"
                mt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S") if mtime else "brak"
                print(f"     {name:30s}  {size//1024:6d}KB  {mt}  {flag}")
                all_files.append((fpath, name, mtime, size, inc))
                if inc: include_list.append((fpath, name))
            except Exception as e:
                print(f"     {name}  ⚠ file_get_info błąd: {e} → INCLUDE fallback")
                all_files.append((fpath, name, -1, -1, True))
                include_list.append((fpath, name))
    except gp.GPhoto2Error as e:
        print(f"     ❌ folder_list_files błąd {e.code}")

hr("6. PODSUMOWANIE")
print(f"  Pliki ogółem          : {len(all_files)}")
print(f"  Do importu (include)  : {len(include_list)}")
print(f"  Wykluczone            : {len(all_files) - len(include_list)}")
if not include_list and all_files:
    newest = max(all_files, key=lambda x: x[2])
    print(f"\n  ❌ PROBLEM: 0 plików przeszło próg!")
    print(f"     Próg:            {datetime.fromtimestamp(threshold_ts)}")
    print(f"     Najnowszy plik:  {newest[1]}  {datetime.fromtimestamp(newest[2]) if newest[2]>0 else 'mtime=0'}")
elif include_list:
    print(f"\n  ✓ Import powinien działać")

camera.exit(context)
print("\n✓ Rozłączono")
