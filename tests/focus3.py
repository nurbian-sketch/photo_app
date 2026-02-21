import gphoto2 as gp
import time

def toggle_focus_mode_raw():
    context = gp.Context()
    camera = gp.Camera()
    camera.init(context)
    
    # Pobranie aktualnej konfiguracji
    config = camera.get_config(context)
    focus_node = config.get_child_by_name('focusmode')
    
    current_val = focus_node.get_value()
    print(f"Stan początkowy: {current_val}")

    # 1. Próba zmiany na One Shot (bez dotykania blokad)
    target = "One Shot" if current_val == "AI Servo" else "AI Servo"
    print(f"Próba bezpośredniego wymuszenia: {target}...")
    
    try:
        focus_node.set_value(target)
        camera.set_config(config, context)
        print(f"Sukces: Wysłano {target}")
    except Exception as e:
        print(f"Błąd przy zmianie na {target}: {e}")

    # Krótka pauza i weryfikacja
    time.sleep(1)
    new_config = camera.get_config(context)
    actual_val = new_config.get_child_by_name('focusmode').get_value()
    print(f"Stan po operacji: {actual_val}")

    camera.exit(context)

if __name__ == "__main__":
    toggle_focus_mode_raw()
