import gphoto2 as gp
import json
import time

def get_full_state(camera, context):
    config = camera.get_config(context)
    state = {}
    def walk(node):
        for i in range(node.count_children()):
            child = node.get_child(i)
            if child.get_type() != gp.GP_WIDGET_SECTION:
                try: state[child.get_name()] = child.get_value()
                except: pass
            walk(child)
    walk(config)
    return state

def apply_bulk(camera, context, updates):
    config = camera.get_config(context)
    for name, val in updates.items():
        try:
            widget = config.get_child_by_name(name)
            widget.set_value(str(val))
        except: pass
    camera.set_config(config, context)

def main():
    context = gp.Context()
    camera = gp.Camera()
    camera.init(context)
    test_log = {}

    # 1. ZRZUT PEŁNY - Dowolny tryb startowy
    print("📸 Krok 1: Snapshot początkowy...")
    initial_state = get_full_state(camera, context)
    test_log["1_INITIAL_SNAPSHOT"] = initial_state

    # 2. PRZEŁĄCZENIE NA FV I ZMIANA PARAMETRÓW
    print("🚀 Krok 2: Przejście na Fv i zmiana parametrów aplikacji...")
    apply_bulk(camera, context, {"autoexposuremode": "Fv"})
    time.sleep(1)
    
    app_logic_changes = {
        "iso": "400",
        "aperture": "4",
        "shutterspeed": "1/125",
        "whitebalance": "Daylight",
        "imageformat": "S1"
    }
    apply_bulk(camera, context, app_logic_changes)
    time.sleep(1)
    
    # Odczyt czy przyjęte
    test_log["2_AFTER_APP_CHANGES"] = get_full_state(camera, context)

    # 3. POWRÓT DO STANU Fv SPRZED ZMIAN APLIKACJI
    print("🔄 Krok 3: Przywracanie wartości wewnątrz Fv...")
    # Wybieramy wartości, które były w Fv zaraz po jego włączeniu (lub z initial, jeśli tam były)
    restore_fv = {k: initial_state[k] for k in app_logic_changes.keys() if k in initial_state}
    apply_bulk(camera, context, restore_fv)
    time.sleep(1)
    test_log["3_AFTER_INTERNAL_RESTORE"] = get_full_state(camera, context)

    # 4. POWRÓT DO POCZĄTKOWEGO TRYBU I PORÓWNANIE
    print("🔙 Krok 4: Powrót do trybu startowego...")
    apply_bulk(camera, context, {"autoexposuremode": initial_state["autoexposuremode"]})
    time.sleep(1)
    
    # Finalny zrzut do porównania
    final_state = get_full_state(camera, context)
    test_log["4_FINAL_STATE"] = final_state

    # 5. PORÓWNANIE
    diffs = {k: {"old": initial_state[k], "new": final_state[k]} 
             for k in initial_state if k in final_state and initial_state[k] != final_state[k]}
    
    test_log["COMPARISON_DIFFS"] = diffs

    with open("full_cycle_test.json", 'w') as f:
        json.dump(test_log, f, indent=4)
    
    camera.exit(context)
    print(f"\n✅ Test zakończony. Znaleziono {len(diffs)} różnic po powrocie.")

if __name__ == "__main__":
    main()