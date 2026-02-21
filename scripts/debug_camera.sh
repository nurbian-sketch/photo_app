#!/bin/bash
export LC_ALL=C

# 1. Zabijamy procesy blokujące aparat (częsty problem na Linuxie)
gio mount -s gphoto2 2>/dev/null || true

# 2. Odświeżenie listy plików (to budzi dostęp do karty w Canonach)
gphoto2 --num-files > /dev/null 2>&1

echo "============================================================"
echo " DIAGNOSTYKA CANON EOS RP - SESSIONS ASSISTANT"
echo "============================================================"

SN=$(gphoto2 --summary | grep "Serial Number" | awk '{print $3}')
LENS=$(gphoto2 --get-config /main/status/lensname | grep "Current:" | cut -d' ' -f2-)
BATT=$(gphoto2 --get-config /main/status/batterylevel | grep "Current:" | awk '{print $2}')
MODE=$(gphoto2 --get-config /main/capturesettings/autoexposuremode | grep "Current:" | awk '{print $2}')
SHOTS=$(gphoto2 --get-config /main/status/availableshots | grep "Current:" | awk '{print $2}')

# Sprawdzenie karty SD przez system plików gphoto
FILE_COUNT=$(gphoto2 --num-files | awk '{print $4}')

echo "[+] APARAT: Canon EOS RP"
echo "[+] S/N:    $SN"
echo "[+] SZKŁO:  $LENS"
echo "[+] BATERIA: $BATT"
echo "[+] TRYB:   $MODE"

if [ "$SHOTS" -eq 0 ] 2>/dev/null; then
    echo "[!] KARTA:  BŁĄD! Nie widzę karty lub jest zablokowana."
else
    echo "[+] KARTA:  Wykryta i aktywna."
    echo "[+] PLIKI:  Na karcie jest obecnie $FILE_COUNT zdjęć."
    echo "[+] MIEJSCE: Pozostało miejsca na ok. $SHOTS zdjęć."
fi

echo "[!] FLASH:  Sprawdź synchronizator na stopce!"
echo "============================================================"
