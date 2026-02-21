import gphoto2 as gp

def run_simple_diagnostics():
    context = gp.Context()
    camera = gp.Camera()
    
    try:
        camera.init(context)
        config = camera.get_config(context)
        
        # Interesujące nas parametry
        params = ['shutterspeed', 'aperture', 'iso', 'exposurecompensation', 'imageformat']
        
        print("\n--- RAPORT PARAMETRÓW CANON RP ---")
        
        for name in params:
            try:
                widget = config.get_child_by_name(name)
                current = widget.get_value()
                choices = list(widget.get_choices())
                
                print(f"\nPARAMETR: {name}")
                print(f"  Aktualna wartość: '{current}'")
                print(f"  Wszystkie dostępne kody/opcje:")
                # Wyświetlamy surowe wartości, żeby namierzyć 00ff i inne kody PTP
                print(f"  {choices}")
                
            except gp.GPhoto2Error:
                print(f"\nPARAMETR: {name} - Nie odnaleziono (może być ukryty w tym trybie pokrętła)")

        camera.exit(context)
        
    except Exception as e:
        print(f"Błąd: {e}")

if __name__ == "__main__":
    run_simple_diagnostics()