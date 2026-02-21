import gphoto2 as gp
import time

def try_various_workarounds():
    context = gp.Context()
    camera = gp.Camera()
    camera.init(context)
    
    config = camera.get_config(context)

    # METODA 1: Wyłączenie wszystkich wspomagaczy AF
    # W Twoim pliku Continuous AF i Movie Servo AF są ON 
    print("[1] Próba zdjęcia blokad AF (Continuous & Movie Servo)...")
    try:
        for param_name in ['continuousaf', 'movieservoaf']:
            node = config.get_child_by_name(param_name)
            node.set_value('Off')
        camera.set_config(config, context)
        print("    Blokady zdjęte.")
        time.sleep(1)
        config = camera.get_config(context)
    except:
        print("    Nie udało się zmienić parametrów pomocniczych.")

    # METODA 2: Zmiana trybu na Fv (Flexible Priority)
    # Masz go dostępnego jako opcja 40 
    print("[2] Próba przełączenia na tryb Fv (często odblokowuje opcje PTP)...")
    try:
        ae_mode = config.get_child_by_name('autoexposuremode')
        ae_mode.set_value('Fv')
        camera.set_config(config, context)
        time.sleep(1)
        config = camera.get_config(context)
    except:
        print("    Nie udało się zmienić trybu ekspozycji.")

    # METODA 3: Bezpośrednie wymuszenie One Shot
    print("[3] Próba wymuszenia 'One Shot'...")
    try:
        focus_mode = config.get_child_by_name('focusmode')
        # Sprawdzamy co aktualnie widzi gphoto2
        current_choices = [focus_mode.get_choice(i) for i in range(focus_mode.count_choices())]
        print(f"    Widoczne opcje: {current_choices}")
        
        focus_mode.set_value('One Shot')
        camera.set_config(config, context)
        print("    SUKCES: Wysłano komendę One Shot.")
    except Exception as e:
        print(f"    BŁĄD: Aparat nadal odrzuca zmianę. Treść: {e}")

    camera.exit(context)

if __name__ == "__main__":
    try_various_workarounds()
