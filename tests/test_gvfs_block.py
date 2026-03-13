#!/usr/bin/env python3
"""
Diagnozuje czy gvfs blokuje gphoto2 po podłączeniu kamery.
Uruchom: python3 test_gvfs_block.py
"""
import os, subprocess, time
os.environ['LANGUAGE'] = 'C'
import gphoto2 as gp
from datetime import datetime

def hr(t): print(f"\n{'─'*60}\n  {t}\n{'─'*60}")

hr("1. PROCESY gvfs PRZED TESTEM")
r = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
gvfs_procs = [l for l in r.stdout.splitlines() if 'gvfs' in l.lower() and 'grep' not in l]
if gvfs_procs:
    for p in gvfs_procs:
        print(f"  {p.split()[1]:6s} {' '.join(p.split()[10:])}")
else:
    print("  Brak procesów gvfs")

hr("2. PRÓBA POŁĄCZENIA — BEZ kill gvfs")
t0 = time.time()
try:
    ctx = gp.Context()
    pil = gp.PortInfoList(); pil.load()
    al = gp.CameraAbilitiesList(); al.load(ctx)
    cams = al.detect(pil, ctx)
    if not cams:
        print(f"  Brak aparatu po {time.time()-t0:.1f}s")
    else:
        model, port = cams[0]
        cam = gp.Camera()
        cam.set_abilities(al[al.lookup_model(model)])
        cam.set_port_info(pil[pil.lookup_path(port)])
        cam.init(ctx)
        print(f"  ✓ POŁĄCZONO: {model}  ({time.time()-t0:.1f}s)")
        cam.exit(ctx)
except gp.GPhoto2Error as e:
    print(f"  ❌ GPhoto2Error code={e.code}: {e}")
    print(f"     {'← GVFS BLOKUJE!' if e.code in (-52, -53, -110) else '← inny błąd'}")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {e}")

hr("3. KILL gvfs-gphoto2 (nie restaruje automatycznie)")
r = subprocess.run(
    ['pkill', '-f', 'gvfsd-gphoto2'],
    capture_output=True, text=True
)
print(f"  pkill gvfsd-gphoto2 → returncode={r.returncode}")
time.sleep(0.5)

hr("4. PRÓBA POŁĄCZENIA — PO kill gvfs")
t0 = time.time()
try:
    ctx2 = gp.Context()
    pil2 = gp.PortInfoList(); pil2.load()
    al2 = gp.CameraAbilitiesList(); al2.load(ctx2)
    cams2 = al2.detect(pil2, ctx2)
    if not cams2:
        print(f"  Brak aparatu po {time.time()-t0:.1f}s")
    else:
        model2, port2 = cams2[0]
        cam2 = gp.Camera()
        cam2.set_abilities(al2[al2.lookup_model(model2)])
        cam2.set_port_info(pil2[pil2.lookup_path(port2)])
        cam2.init(ctx2)
        print(f"  ✓ POŁĄCZONO: {model2}  ({time.time()-t0:.1f}s)")
        cam2.exit(ctx2)
except gp.GPhoto2Error as e:
    print(f"  ❌ GPhoto2Error code={e.code}: {e}")
except Exception as e:
    print(f"  ❌ {type(e).__name__}: {e}")

hr("WNIOSKI")
print("""
  Jeśli sekcja 2 dała błąd code=-52, a sekcja 4 działa →
  PRZYCZYNA: gvfsd-gphoto2 blokuje port USB po podłączeniu kamery.
  FIX: pkill gvfsd-gphoto2 przed _connect_camera() w session_runner.

  Jeśli obie działają →
  Uruchom aplikację, zrób sesję, sprawdź linie [IMPORT] w terminalu.
""")
