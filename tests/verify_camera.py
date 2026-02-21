import gphoto2 as gp
import sys
import json
import os

# Parametry wyciągnięte z Twoich plików UI
OUR_LIMITS = {
    "iso": ['Auto', '100', '200', '400', '800', '1600'],
    "shutterspeed": ['1/4', '1/5', '1/6', '1/8', '1/10', '1/13', '1/15', '1/20', '1/25', '1/30', '1/40', '1/50', '1/60', '1/80', '1/100', '1/125', '1/160', '1/200', '1/250', '1/320', '1/400', '1/500', '1/640', '1/800', '1/1000'],
    "aperture": ['2.8', '3.2', '3.5', '4', '4.5', '5.0', '5.6', '6.3', '7.1', '8', '9', '10', '11', '13', '14', '16', '18', '20', '22'],
    "imageformat": ["Large Fine JPEG"],
    "exposuremode": ["Fv", "Manual"],
    "whitebalance": ["Auto", "Daylight", "Shadow", "Cloudy", "Tungsten", "Fluorescent", "Flash", "Manual", "Color Temperature"]
}

GP_PATHS = {
    "iso": "/main/imgsettings/iso",
    "shutterspeed": "/main/capturesettings/shutterspeed",
    "aperture": "/main/capturesettings/aperture",
    "imageformat": "/main/imgsettings/imageformat",
    "exposuremode": "/main/capturesettings/autoexposuremode",
    "whitebalance": "/main/imgsettings/whitebalance"
}

def get_node_by_path(config, path):
    parts = path.strip('/').split('/')
    node = config
    for part in parts:
        node = node.get_child_by_name(part)
    return node

def run_verify():
    print("--- ETAP 1: Połączenie ---")
    try:
        context = gp.Context()
        camera = gp.Camera()
        camera.init(context)
        print("✅ Aparat podłączony.")
    except gp.GPhoto2Error:
        print("❌ BŁĄD: Brak aparatu.")
        sys.exit(1)

    print("\n--- ETAP 2: Backup i Walidacja (FSM) ---")
    config = camera.get_config(context)
    backup = {}
    to_fix = {} # Tu zbieramy tylko to, co wymaga poprawki

    for key, path in GP_PATHS.items():
        try:
            node = get_node_by_path(config, path)
            val = node.get_value()
            backup[key] = val

            if key in OUR_LIMITS:
                if val not in OUR_LIMITS[key]:
                    # Specjalna obsługa dla formatu zdjęcia
                    if key == "imageformat":
                        # Sprawdźmy co aparat akceptuje (wyświetlamy dostępne opcje w razie błędu)
                        choices = [node.get_choice(i) for i in range(node.count_choices())]
                        new_val = "Large Fine JPEG" if "Large Fine JPEG" in choices else choices[0]
                    else:
                        # Tutaj zostaje logika find_closest (uproszczona dla testu)
                        new_val = OUR_LIMITS[key][-1] # Tymczasowo: najwyższy dopuszczalny
                    
                    print(f"⚠️  {key}: {val} -> DO NAPRAWY: {new_val}")
                    to_fix[path] = new_val
                else:
                    print(f"✅ {key}: {val} (OK)")
        except Exception as e:
            print(f"❌ Pominąłem {key}: {e}")

    # Zapis backupu
    os.makedirs('tests', exist_ok=True)
    with open('tests/camera_backup.json', 'w') as f:
        json.dump(backup, f, indent=4)
    print(f"\n💾 Backup zapisany.")

    if to_fix:
        print("\n--- ETAP 3: Synchronizacja punktowa ---")
        # Zamiast wysyłać całe config, pobieramy świeże i ustawiamy tylko to co trzeba
        clean_config = camera.get_config(context)
        for path, new_val in to_fix.items():
            try:
                target_node = get_node_by_path(clean_config, path)
                target_node.set_value(new_val)
                print(f"Ustawiam {path} na {new_val}...")
            except Exception as e:
                print(f"Błąd przy {path}: {e}")
        
        try:
            camera.set_config(clean_config, context)
            print("✅ Synchronizacja zakończona pomyślnie.")
        except gp.GPhoto2Error as e:
            print(f"❌ Aparat nadal odrzuca konfigurację: {e}")
            print("Wskazówka: Sprawdź czy aparat nie jest w trybie podglądu zdjęć lub czy menu nie jest otwarte.")
    else:
        print("✅ Wszystko było OK.")

    camera.exit(context)

if __name__ == "__main__":
    run_verify()