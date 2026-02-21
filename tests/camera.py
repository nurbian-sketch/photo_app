import gphoto2 as gp
import json
import time

def get_camera_state(camera, context):
    config = camera.get_config(context)
    # Wyciągamy tylko to, co nas interesuje do analizy nadrzędności
    params = ['autoexposuremode', 'autoexposuremodedial', 'aperture', 'shutterspeed', 'iso']
    state = {}
    for p in params:
        try:
            widget = config.get_child_by_name(p)
            state[p] = widget.get_value()
        except:
            state[p] = "N/A"
    return state

def set_mode(camera, context, mode_name):
    try:
        config = camera.get_config(context)
        widget = config.get_child_by_name('autoexposuremode')
        widget.set_value(mode_name)
        camera.set_config(config, context)
        return True
    except Exception as e:
        print(f"  ❌ Nie można wymusić {mode_name}: {e}")
        return False

def main():
    context = gp.Context()
    camera = gp.Camera()
    camera.init(context)
    
    modes_to_test = ['Manual', 'Av', 'Tv', 'Program']
    results = {}

    for mode in modes_to_test:
        print(f"\n--- TEST DLA TRYBU: {mode} ---")
        print(f"Ustaw FIZYCZNIE pokrętło na {mode} i naciśnij Enter...")
        input()
        
        # 1. Odczyt po ręcznym ustawieniu
        base_state = get_camera_state(camera, context)
        results[f"PHYSICAL_{mode}"] = base_state
        print(f"  Odczytano: {base_state}")

        # 2. Próba wymuszenia Fv z tego poziomu
        print(f"  Próbuję wymusić programowo Fv...")
        if set_mode(camera, context, 'Fv'):
            time.sleep(1)
            fv_state = get_camera_state(camera, context)
            results[f"FORCED_FV_FROM_{mode}"] = fv_state
            print(f"  Sukces! Stan po wymuszeniu: {fv_state}")
        else:
            results[f"FORCED_FV_FROM_{mode}"] = "FAILED"

    with open("dial_modes_test.json", 'w') as f:
        json.dump(results, f, indent=4)
    
    camera.exit(context)
    print("\n✅ Test zakończony. Analizujemy dial_modes_test.json")

if __name__ == "__main__":
    main()