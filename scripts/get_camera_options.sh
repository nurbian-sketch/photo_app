#!/bin/bash

# Nazwa pliku wyjściowego
OUTPUT_FILE="eos_rp_options_full.txt"

echo "--------------------------------------------------------"
echo "  Canon EOS RP - GPhoto2 Options Collector"
echo "--------------------------------------------------------"

# 1. Sprawdzenie czy aparat jest podłączony
echo "[1/4] Wykrywanie aparatu..."
if ! gphoto2 --auto-detect | grep -q "Canon EOS RP"; then
    echo "❌ BŁĄD: Nie wykryto Canona EOS RP."
    echo "Sprawdź kabel USB i czy aparat jest włączony."
    exit 1
fi
echo "✅ Aparat wykryty."

# 2. Zabicie procesów blokujących (gvfs), które Mint często uruchamia
echo "[2/4] Zwalnianie portów USB (gvfs-mount)..."
gio mount -s gphoto2 2>/dev/null || true
echo "✅ Porty zwolnione."

# 3. Pobieranie podsumowania (Firmware, Bateria, Status)
echo "[3/4] Pobieranie podsumowania aparatu..."
echo "=== PODSUMOWANIE APARATU ===" > $OUTPUT_FILE
gphoto2 --summary >> $OUTPUT_FILE
echo -e "\n\n=== LISTA WSZYSTKICH KONFIGURACJI ===" >> $OUTPUT_FILE

# 4. Pobieranie wszystkich opcji (To potrwa kilkanaście sekund)
echo "[4/4] Pobieranie wszystkich dostępnych opcji (list-config)..."
echo "To może chwilę potrwać, aparat musi przesłać setki parametrów..."

# Pobieramy listę ścieżek
CONFIG_LIST=$(gphoto2 --list-config)

# Dla każdej ścieżki pobieramy szczegóły (wartość i choices)
for cfg in $CONFIG_LIST; do
    echo "  Pobieranie: $cfg"
    echo "------------------------------------------------" >> $OUTPUT_FILE
    gphoto2 --get-config "$cfg" >> $OUTPUT_FILE
done

echo "--------------------------------------------------------"
echo "✅ ZAKOŃCZONO!"
echo "Pełna lista opcji została zapisana w pliku: $OUTPUT_FILE"
echo "Możesz go przejrzeć wpisując: less $OUTPUT_FILE"
