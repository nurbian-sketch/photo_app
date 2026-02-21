#!/usr/bin/env python3
"""
Test: czy Canon EOS RP akceptuje zmianę exposurecompensation
i w jakim formacie.
Uruchom z co najmniej jednym parametrem na Auto!
"""
import gphoto2 as gp
import time

ctx = gp.Context()
pil = gp.PortInfoList(); pil.load()
al = gp.CameraAbilitiesList(); al.load(ctx)
cams = al.detect(pil, ctx)
m, p = cams[0]
cam = gp.Camera()
cam.set_abilities(al[al.lookup_model(m)])
cam.set_port_info(pil[pil.lookup_path(p)])
cam.init(ctx)
print(f"Aparat: {m}\n")

# Uruchom live view
cf = gp.CameraFile()
cam.capture_preview(cf, ctx)
time.sleep(0.5)

# Sprawdź aktualny stan
config = cam.get_config(ctx)
w = config.get_child_by_name('exposurecompensation')
print(f"Typ widgetu: {w.get_type()}")
print(f"Aktualna wartość: '{w.get_value()}'")
print(f"Choices: {list(w.get_choices())}")

# Sprawdź stan shutter/aperture/iso
for name in ['shutterspeed', 'aperture', 'iso']:
    ww = config.get_child_by_name(name)
    v = ww.get_value()
    is_auto = '00ff' in v.lower() if v else False
    print(f"  {name}: '{v}' {'(AUTO)' if is_auto else '(MANUAL)'}")

print("\n--- PRÓBY USTAWIENIA EXP COMP ---")

# Formaty do przetestowania
test_values = ['0.3', '+0.3', '0,3', '1/3', '1', '-0.3', '0']

for val in test_values:
    try:
        config = cam.get_config(ctx)
        w = config.get_child_by_name('exposurecompensation')
        w.set_value(val)
        cam.set_config(config, ctx)
        
        # Odczytaj z powrotem
        time.sleep(0.2)
        config2 = cam.get_config(ctx)
        w2 = config2.get_child_by_name('exposurecompensation')
        readback = w2.get_value()
        print(f"  '{val}' → OK (readback: '{readback}')")
        
        # Utrzymaj live view
        cf = gp.CameraFile(); cam.capture_preview(cf, ctx)
        
    except gp.GPhoto2Error as e:
        print(f"  '{val}' → BŁĄD gphoto2: {e.code}")
        # Sprawdź czy live view jeszcze żyje
        try:
            cf = gp.CameraFile(); cam.capture_preview(cf, ctx)
            print(f"         live view: OK")
        except gp.GPhoto2Error as e2:
            print(f"         live view: MARTWY ({e2.code})")
            # Próba odzyskania
            try:
                cam.exit(ctx)
                time.sleep(1)
                cam.init(ctx)
                cf = gp.CameraFile(); cam.capture_preview(cf, ctx)
                print(f"         reconnect: OK")
            except:
                print(f"         reconnect: FAILED — kończę test")
                cam.exit(ctx)
                exit(1)
    except Exception as e:
        print(f"  '{val}' → WYJĄTEK: {e}")

# Reset do 0
try:
    config = cam.get_config(ctx)
    w = config.get_child_by_name('exposurecompensation')
    w.set_value('0')
    cam.set_config(config, ctx)
    print("\nReset do '0': OK")
except:
    print("\nReset do '0': BŁĄD")

cam.exit(ctx)
print("\nGOTOWE.")
