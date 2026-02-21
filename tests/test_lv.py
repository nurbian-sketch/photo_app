import gphoto2 as gp
import cv2
import numpy as np
import sys

def run_standalone_test():
    print("--- START STANDALONE TEST (LV + BLINK) ---")
    
    context = gp.Context()
    camera = gp.Camera()
    
    try:
        # Inicjalizacja połączenia
        print("Łączenie z aparatem...")
        camera.init(context)
        print("Aparat podłączony. Otwieram okno podglądu...")
        print("Wciśnij ESC w oknie obrazu, aby zakończyć.")
        
        while True:
            # 1. PRZYGOTOWANIE OBIEKTU PLIKU (Wymagane przez gphoto2)
            camera_file = gp.CameraFile() 
            
            # 2. POBIERZ KLATKĘ (LIVEVIEW)
            # Metoda wymaga: (plik_docelowy, kontekst)
            camera.capture_preview(camera_file, context)
            
            # Wyciągamy surowe dane bajtowe
            file_data = camera_file.get_data_and_size()
            
            # Konwersja bajtów na tablicę NumPy, a potem na obraz OpenCV (BGR)
            data = np.frombuffer(file_data, dtype=np.uint8)
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR)

            # 3. SPRAWDŹ EVENTY (NASZE 1,3,0.0)
            # Timeout 1ms, żeby nie klatkowało obrazu
            typ, ev_data = camera.wait_for_event(1, context)
            
            status_text = "Status: OK"
            color = (0, 255, 0) # Zielony (BGR)

            if typ == gp.GP_EVENT_UNKNOWN:
                data_str = str(ev_data)
                # Sprawdzamy czy w surowym tekście eventu jest błąd ekspozycji
                if "1,3,0.0" in data_str:
                    status_text = "!!! MIGOCZE (EXPOSURE ERROR) !!!"
                    color = (0, 0, 255) # Czerwony (BGR)
                    print("\a") # Sygnał dźwiękowy w terminalu (opcjonalnie)

            # 4. WYŚWIETL OBRAZ Z NAKŁADKĄ
            if frame is not None:
                # Nakładamy tekst na ramkę obrazu
                cv2.putText(frame, status_text, (20, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
                
                cv2.imshow('TEST LIVEVIEW', frame)

            # Wyjście klawiszem ESC (kod 27)
            if cv2.waitKey(1) & 0xFF == 27:
                break

    except gp.GPhoto2Error as e:
        print(f"BŁĄD GPHOTO2: {e}")
    except Exception as e:
        print(f"BŁĄD KRYTYCZNY: {e}")
    finally:
        print("Zamykanie połączenia i okien...")
        cv2.destroyAllWindows()
        try:
            camera.exit(context)
        except:
            pass
        print("Koniec.")

if __name__ == "__main__":
    run_standalone_test()