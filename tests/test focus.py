import gphoto2 as gp
import time

def get_choices(config, name):
    try:
        widget = config.get_child_by_name(name)
        return [str(c) Choice for c in widget.get_choices()]
    except:
        return []

def set_val(camera, context, name, value):
    config = camera.get_config(context)
    try:
        widget = config.get_child_by_name(name)
        widget.set_value(value)
        camera.set_config(config, context)
        print(f"  SET: {name} -> {value}")
        time.sleep(1) # Czekamy na przetrawienie przez aparat
        return True
    except:
        print(f"  ERR: Nie można ustawić {name}")
        return False

def main():
    context = gp.Context()
    camera = gp.Camera()
    camera.init(context)

    # Scenariusze testowe do sprawdzenia zależności
    test_matrix = {
        "afmethod": ["LiveSpotAF", "Face Detection + Tracking", "Zone AF"],
        "continuousaf": ["Off", "On"],
        "autoexposuremode": ["P", "Manual", "Fv"]
    }

    print("🔍 ROZPOCZYNAMY TEST ZALEŻNOŚCI FOCUSMODE\n")

    for param, values in test_matrix.items():
        print(f"\n--- Testowanie parametru: {param} ---")
        for val in values:
            if set_val(camera, context, param, val):
                # Odczytujemy stan po zmianie
                updated_config = camera.get_config(context)
                choices = get_choices(updated_config, 'focusmode')
                current = updated_config.get_child_by_name('focusmode').get_value()
                
                print(f"  >>> FOCUSMODE: Current={current}, Choices={choices}")

    camera.exit(context)
    print("\n✅ Test zakończony. Sprawdź, przy której kombinacji pojawiło się AI Servo.")

if __name__ == "__main__":
    main()