import gphoto2 as gp
import time

def force_ai_servo():
    context = gp.Context()
    camera = gp.Camera()
    camera.init(context)
    
    config = camera.get_config(context)

    # 1. Upewnienie się, że blokady są zdjęte (opcjonalnie, dla pewności)
    print("[1] Sprawdzanie ustawień pomocniczych...")
    try:
        cont_af = config.get_child_by_name('continuousaf')
        # W Twoim pliku domyślnie było 'On' 
        cont_af.set_value('On') 
        camera.set_config(config, context)
        print("    Continuous AF przywrócony na 'On'.")
    except:
        print("    Nie udało się zmienić Continuous AF.")

    # 2. Wymuszenie AI Servo
    print("[2] Próba wymuszenia 'AI Servo'...")
    try:
        focus_mode = config.get_child_by_name('focusmode')
        
        # Wartość z Twojego pliku to 'AI Servo' 
        focus_mode.set_value('AI Servo')
        camera.set_config(config, context)
        
        # Weryfikacja natychmiastowa
        updated_config = camera.get_config(context)
        current_val = updated_config.get_child_by_name('focusmode').get_value()
        print(f"    SUKCES: Wysłano komendę. Aktualny stan raportowany: {current_val}")
        
    except Exception as e:
        print(f"    BŁĄD: Nie udało się przywrócić AI Servo. Treść: {e}")

    camera.exit(context)

if __name__ == "__main__":
    force_ai_servo()
