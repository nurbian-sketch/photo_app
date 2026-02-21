import gphoto2 as gp
import time

def get_choices(config, name):
    try:
        widget = config.get_child_by_name(name)
        # Naprawiona linia:
        return [str(c) for c in widget.get_choices()]
    except:
        return []

def set_val(camera, context, name, value):
    try:
        config = camera.get_config(context)
        widget = config.get_child_by_name(name)
        widget.set_value(value)
        camera.set_config(config, context)
        print(f"  SET: {name} -> {value}")
        time.sleep(0.5) 
        return True
    except Exception as e:
        print(f"  ERR: Nie można ustawić {name} na {value}")
        return False

def main():
    context = gp.Context()
    camera = gp.Camera()
    camera.init(context)

    # Scenariusze testowe
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
                # Świeży odczyt po zmianie
                updated_config = camera.get_config(context)
                try:
                    f_widget = updated_config.get_child_by_name('focusmode')
                    current = f_widget.get_value()
                    choices = [str(c) for c in f_widget.get_choices()]
                    print(f"  >>> FOCUSMODE: Current={current}, Choices={choices}")
                except:
                    print("  >>> FOCUSMODE: Parametr niedostępny w tej konfiguracji")

    camera.exit(context)

if __name__ == "__main__":
    main()