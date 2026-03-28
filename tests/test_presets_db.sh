#!/usr/bin/env bash
# Skrypt testowy: przepuszcza pliki CR3 przez style odczytane z data.db darktable
# Użycie: ./test_presets_db.sh [--gpu] [--cpu]
# Domyślnie: GPU (opencl=true)

set -euo pipefail

# --- Ścieżki ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CR3_DIR="$PROJECT_DIR/assets/examples"
OUTPUT_DIR="$CR3_DIR/output_db"
DARKTABLE_DB="$HOME/.config/darktable/data.db"

# --- Parametry ---
JPEG_QUALITY=95
JPEG_BPP=8
COLOR_PROFILE="sRGB"
OPENCL="true"

# --- Kolory terminala ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

# --- Sprawdź zależności ---
if [[ ! -f "$DARKTABLE_DB" ]]; then
    echo -e "${RED}Brak bazy darktable: $DARKTABLE_DB${NC}"
    exit 1
fi

if ! command -v sqlite3 &>/dev/null; then
    echo -e "${RED}Brak sqlite3${NC}"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# --- Odczytaj style z bazy ---
mapfile -t STYLES < <(sqlite3 "$DARKTABLE_DB" "SELECT name FROM styles ORDER BY name;")

if [[ ${#STYLES[@]} -eq 0 ]]; then
    echo -e "${RED}Brak styli w bazie: $DARKTABLE_DB${NC}"
    exit 1
fi

# --- Znajdź pliki CR3 ---
mapfile -t CR3_FILES < <(find "$CR3_DIR" -maxdepth 1 \( -iname "*.CR3" -o -iname "*.cr3" \) | sort)

CR3_COUNT=${#CR3_FILES[@]}
STYLE_COUNT=${#STYLES[@]}
TOTAL=$(( CR3_COUNT * STYLE_COUNT ))

if [[ $CR3_COUNT -eq 0 ]]; then
    echo -e "${RED}Brak plików CR3 w: $CR3_DIR${NC}"
    exit 1
fi

echo -e "${CYAN}${BOLD}=== Test presetów darktable (z bazy) ===${NC}"
echo "Pliki CR3  : $CR3_COUNT  (w: $CR3_DIR)"
echo "Style      : $STYLE_COUNT  (z: $DARKTABLE_DB)"
echo "OpenCL     : $OPENCL"
echo "Output     : $OUTPUT_DIR"
echo "Łącznie    : $TOTAL konwersji"
echo ""

OK=0
FAIL=0
COUNTER=0
T_SCRIPT_START=$SECONDS

for CR3 in "${CR3_FILES[@]}"; do
    CR3_BASENAME=$(basename "$CR3")
    CR3_STEM="${CR3_BASENAME%.*}"

    echo -e "${CYAN}── $CR3_BASENAME ──${NC}"

    for STYLE_NAME in "${STYLES[@]}"; do
        COUNTER=$(( COUNTER + 1 ))
        SAFE_NAME="${STYLE_NAME//\//_}"   # zamień / na _ (bezpieczna nazwa pliku)
        OUTPUT_FILE="$OUTPUT_DIR/${CR3_STEM}+${SAFE_NAME}.jpg"

        printf "  ${YELLOW}[%d/%d]${NC} %-45s " "$COUNTER" "$TOTAL" "$STYLE_NAME"

        T_START=$SECONDS
        if darktable-cli \
                "$CR3" \
                "$OUTPUT_FILE" \
                --style "$STYLE_NAME" \
                --core \
                --conf "plugins/imageio/format/jpeg/quality=$JPEG_QUALITY" \
                --conf "plugins/imageio/format/jpeg/bpp=$JPEG_BPP" \
                --conf "plugins/colorout/iccprofile=$COLOR_PROFILE" \
                --conf "opencl=$OPENCL" \
                > /dev/null 2>&1; then
            T_ELAPSED=$(( SECONDS - T_START ))
            # ETA na podstawie średniej kroczącej
            T_TOTAL=$(( SECONDS - T_SCRIPT_START ))
            AVG=$(( T_TOTAL / COUNTER ))
            REMAINING=$(( (TOTAL - COUNTER) * AVG ))
            REM_MIN=$(( REMAINING / 60 ))
            REM_SEC=$(( REMAINING % 60 ))
            echo -e "${GREEN}OK${NC}  ${T_ELAPSED}s  (pozostało ~${REM_MIN}m ${REM_SEC}s)"
            OK=$(( OK + 1 ))
        else
            T_ELAPSED=$(( SECONDS - T_START ))
            echo -e "${RED}BŁĄD${NC}  ${T_ELAPSED}s"
            FAIL=$(( FAIL + 1 ))
        fi
    done
    echo ""
done

T_TOTAL_ELAPSED=$(( SECONDS - T_SCRIPT_START ))
T_MIN=$(( T_TOTAL_ELAPSED / 60 ))
T_SEC=$(( T_TOTAL_ELAPSED % 60 ))
AVG_FINAL=$(( T_TOTAL_ELAPSED / (OK + FAIL) ))

echo -e "${CYAN}${BOLD}=== Raport ===${NC}"
echo -e "OK        : ${GREEN}$OK${NC}"
echo -e "Błędy     : ${RED}$FAIL${NC}"
echo -e "Łącznie   : $TOTAL"
echo -e "Czas total: ${BOLD}${T_MIN}m ${T_SEC}s${NC}"
echo -e "Średnia   : ${BOLD}${AVG_FINAL}s / styl${NC}"
echo -e "OpenCL    : $OPENCL"

exit $(( FAIL > 0 ? 1 : 0 ))
