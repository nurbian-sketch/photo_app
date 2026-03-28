#!/usr/bin/env bash
# Skrypt benchmarkowy: 1 plik CR3 × 28 styli, dwa przebiegi CPU vs GPU
# Użycie: ./test_presets_benchmark.sh

set -euo pipefail

# --- Ścieżki ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CR3_DIR="$PROJECT_DIR/assets/examples"
PRESETS_DIR="$PROJECT_DIR/darktable_presets"
OUTPUT_DIR="$CR3_DIR/output_benchmark"

# --- Parametry ---
JPEG_QUALITY=95
JPEG_BPP=8
COLOR_PROFILE="sRGB"

# --- Kolory terminala ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

mkdir -p "$OUTPUT_DIR"

DARKTABLE_DB="$HOME/.config/darktable/data.db"
mapfile -t STYLES < <(sqlite3 "$DARKTABLE_DB" "SELECT name FROM styles ORDER BY name;")

# --- Wybierz pierwsze znalezione zdjęcie CR3 ---
CR3=$(find "$CR3_DIR" -maxdepth 1 \( -iname "*.CR3" -o -iname "*.cr3" \) | sort | head -1)

if [[ -z "$CR3" ]]; then
    echo -e "${RED}Brak plików CR3 w: $CR3_DIR${NC}"
    exit 1
fi

CR3_BASENAME=$(basename "$CR3")
STYLE_COUNT=${#STYLES[@]}

echo -e "${CYAN}${BOLD}=== Benchmark darktable: CPU vs GPU ===${NC}"
echo "Plik      : $CR3_BASENAME"
echo "Style     : $STYLE_COUNT"
echo "Output    : $OUTPUT_DIR"
echo ""

# --- Tablice wyników ---
declare -a CPU_TIMES=()
declare -a GPU_TIMES=()

# -------------------------------------------------------------------
# Funkcja: jeden przebieg przez wszystkie style
# $1 = "CPU" | "GPU"
# $2 = "false" | "true"  (opencl)
# -------------------------------------------------------------------
run_pass() {
    local PASS_LABEL="$1"
    local OPENCL="$2"
    local TIMES_REF="$3"   # nazwa tablicy do zapisu wyników

    local OK=0 FAIL=0 COUNTER=0
    local T_PASS_START=$SECONDS

    if [[ "$PASS_LABEL" == "GPU" ]]; then
        echo -e "${MAGENTA}${BOLD}--- Przebieg GPU (opencl=true) ---${NC}"
    else
        echo -e "${YELLOW}${BOLD}--- Przebieg CPU (opencl=false) ---${NC}"
    fi

    for STYLE_NAME in "${STYLES[@]}"; do
        COUNTER=$(( COUNTER + 1 ))
        local SAFE_NAME="${STYLE_NAME//\*/_}"
        local OUTPUT_FILE="$OUTPUT_DIR/${CR3_BASENAME%.*}+${SAFE_NAME}_${PASS_LABEL}.jpg"

        printf "  [%2d/%d] %-45s " "$COUNTER" "$STYLE_COUNT" "$STYLE_NAME"

        local T_START=$SECONDS
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
            local T_ELAPSED=$(( SECONDS - T_START ))
            printf "${GREEN}OK${NC}  %3ds\n" "$T_ELAPSED"
            eval "${TIMES_REF}+=($T_ELAPSED)"
            OK=$(( OK + 1 ))
        else
            local T_ELAPSED=$(( SECONDS - T_START ))
            printf "${RED}BŁĄD${NC}  %3ds\n" "$T_ELAPSED"
            eval "${TIMES_REF}+=(0)"
            FAIL=$(( FAIL + 1 ))
        fi
    done

    local T_PASS_TOTAL=$(( SECONDS - T_PASS_START ))
    echo ""
    echo -e "  Total ${PASS_LABEL}: ${BOLD}${T_PASS_TOTAL}s${NC}  |  OK: ${GREEN}${OK}${NC}  Błędy: ${RED}${FAIL}${NC}"
    echo ""
}

# --- Przebieg CPU ---
run_pass "CPU" "false" "CPU_TIMES"

# --- Przebieg GPU ---
run_pass "GPU" "true" "GPU_TIMES"

# -------------------------------------------------------------------
# Raport porównawczy
# -------------------------------------------------------------------
echo -e "${CYAN}${BOLD}=== Raport porównawczy ===${NC}"
echo ""
printf "  %-45s %8s %8s %8s\n" "Styl" "CPU [s]" "GPU [s]" "Δ [s]"
printf "  %s\n" "$(printf '%.0s-' {1..75})"

CPU_SUM=0
GPU_SUM=0

for i in "${!STYLES[@]}"; do
    STYLE="${STYLES[$i]}"
    C="${CPU_TIMES[$i]:-0}"
    G="${GPU_TIMES[$i]:-0}"
    DELTA=$(( C - G ))

    if (( DELTA > 0 )); then
        DELTA_STR="${GREEN}+${DELTA}${NC}"   # GPU szybsze
    elif (( DELTA < 0 )); then
        DELTA_STR="${RED}${DELTA}${NC}"      # CPU szybsze
    else
        DELTA_STR="0"
    fi

    printf "  %-45s %8d %8d " "$STYLE" "$C" "$G"
    echo -e "$DELTA_STR"

    CPU_SUM=$(( CPU_SUM + C ))
    GPU_SUM=$(( GPU_SUM + G ))
done

printf "  %s\n" "$(printf '%.0s-' {1..75})"

# Średnia
CPU_AVG=$(( CPU_SUM / STYLE_COUNT ))
GPU_AVG=$(( GPU_SUM / STYLE_COUNT ))
TOTAL_DELTA=$(( CPU_SUM - GPU_SUM ))

echo ""
printf "  %-45s %8d %8d\n" "SUMA [s]" "$CPU_SUM" "$GPU_SUM"
printf "  %-45s %8d %8d\n" "ŚREDNIA na styl [s]" "$CPU_AVG" "$GPU_AVG"
echo ""

if (( TOTAL_DELTA > 0 )); then
    echo -e "  GPU szybsze o: ${GREEN}${BOLD}${TOTAL_DELTA}s${NC} łącznie"
    PCT=$(( TOTAL_DELTA * 100 / CPU_SUM ))
    echo -e "  Przyspieszenie: ${GREEN}${BOLD}${PCT}%${NC}"
elif (( TOTAL_DELTA < 0 )); then
    ABS=$(( -TOTAL_DELTA ))
    echo -e "  CPU szybsze o: ${YELLOW}${BOLD}${ABS}s${NC} łącznie"
else
    echo -e "  Brak różnicy CPU vs GPU"
fi

echo ""
exit 0
