import gphoto2 as gp

def monitor_camera():
    context = gp.Context()
    camera = gp.Camera()
    
    camera.init(context)
    print("--- POWRÓT DO POCZĄTKU: WSZYSTKIE EVENTY ---")

    try:
        while True:
            # Dokładnie to, co wygenerowało Twoje pierwsze logi
            event_type, event_data = camera.wait_for_event(100, context)

            if event_type == gp.GP_EVENT_UNKNOWN:
                data_str = str(event_data)
                
                # Wywalamy surowy tekst na ekran
                print(f"[EVENT] {data_str}")
                
                # Proste sprawdzenie, które wcześniej wyłapałeś
                if "1,3,0.0" in data_str:
                    print("STAN: MIGOCZE")
                elif "1,1,0.0" in data_str:
                    print("STAN: NIE MIGOCZE")

    except KeyboardInterrupt:
        print("\nPrzerwano.")
    finally:
        camera.exit(context)

if __name__ == "__main__":
    monitor_camera()