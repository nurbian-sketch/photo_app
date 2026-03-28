#!/usr/bin/env bash
# Benchmark: darktable-cli z OpenCL vs bez
# Uzycie: bash bench_opencl.sh

CR3="$HOME/Projekty/photo_app/assets/examples/IMG_0078.CR3"
STYLE="canon rp starting point"
RUNS=3
OUT="/tmp/bench_out.jpg"

echo "=== Benchmark darktable-cli ==="
echo "Plik     : $CR3"
echo "Styl     : $STYLE"
echo "Przebiegi: $RUNS"
echo ""

_run() {
    local label=$1
    local opencl=$2
    local total=0

    for i in $(seq 1 $RUNS); do
        printf "  [%d/%d] %s ... " "$i" "$RUNS" "$label"
        rm -rf ~/.cache/darktable/ 2>/dev/null
        local t0 t1 elapsed
        t0=$(date +%s%3N)
        darktable-cli "$CR3" "$OUT" \
            --style "$STYLE" \
            --core \
            --conf "plugins/imageio/format/jpeg/quality=95" \
            --conf "opencl=$opencl" \
            > /dev/null 2>&1
        t1=$(date +%s%3N)
        elapsed=$(( t1 - t0 ))
        total=$(( total + elapsed ))
        printf "%dms (%.1fs)\n" "$elapsed" "$(echo "scale=1; $elapsed/1000" | bc)"
    done

    local avg=$(( total / RUNS ))
    printf "  -> srednia: %dms (%.1fs)\n" "$avg" "$(echo "scale=1; $avg/1000" | bc)"
    echo ""
    echo "$avg" > "/tmp/bench_${opencl}.txt"
}

_run "CPU (opencl=false)" "false"
_run "GPU (opencl=true) " "true"

CPU=$(cat /tmp/bench_false.txt)
GPU=$(cat /tmp/bench_true.txt)

echo "=== Wynik ==="
printf "CPU : %dms (%.1fs)\n" "$CPU" "$(echo "scale=1; $CPU/1000" | bc)"
printf "GPU : %dms (%.1fs)\n" "$GPU" "$(echo "scale=1; $GPU/1000" | bc)"

if [[ $GPU -lt $CPU ]]; then
    DIFF=$(( CPU - GPU ))
    printf "GPU szybszy o %dms (%d%%)\n" "$DIFF" "$(( DIFF * 100 / CPU ))"
elif [[ $CPU -lt $GPU ]]; then
    DIFF=$(( GPU - CPU ))
    printf "CPU szybszy o %dms (%d%%) — OpenCL nie pomaga\n" "$DIFF" "$(( DIFF * 100 / GPU ))"
else
    echo "Brak roznicy"
fi

rm -f "$OUT" /tmp/bench_false.txt /tmp/bench_true.txt