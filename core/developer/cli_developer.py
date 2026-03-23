#!/usr/bin/env python3
"""
cli_developer.py — wywołanie pojedynczego pliku RAW przez darktable-cli.

Użycie:
    python3 cli_developer.py <raw> <preset_xmp> <out_jpeg> [--kelvin <int>]

Tryby WB:
    --kelvin N   (N > 0)  — użyj podanej wartości Kelvin
    --kelvin 0            — odczytaj z EXIF aparatu
    brak --kelvin         — użyj presetu XMP bez zmian (kelvin=None)
"""

import argparse
import re
import struct
import subprocess
import sys
import logging
from pathlib import Path

# ── KONFIGURACJA ─────────────────────────────────────────────────────────────
JPEG_QUALITY  = 95
RAW_EXT       = {".cr2", ".cr3", ".nef", ".arw", ".dng"}
DARKTABLE_VER = "4.6"

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(levelname)-7s] %(message)s"
)
log = logging.getLogger("cli_developer")


# ── EXIF ─────────────────────────────────────────────────────────────────────
def read_exif_tag(path: Path, tag: str) -> str:
    result = subprocess.run(
        ["exiftool", f"-{tag}", "-s3", str(path)],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def get_wb_kelvin(path: Path) -> int:
    try:
        return int(read_exif_tag(path, "ColorTemperature"))
    except ValueError:
        return 0


# ── KELVIN → MULTIPLIKATORY RGB ──────────────────────────────────────────────
def kelvin_to_multipliers(kelvin: int) -> tuple[float, float, float]:
    """
    Interpolacja liniowa na podstawie 2 punktów referencyjnych
    z darktable 4.6.1 / Canon EOS RP (zdekodowane z rzeczywistych XMP).
    Ref: 5200K → R=2.22893 B=1.46019
    Ref: 8081K → R=2.42795 B=1.33276
    """
    K1, R1, B1 = 5200, 2.22893, 1.46019
    K2, R2, B2 = 8081, 2.42795, 1.33276
    t = (kelvin - K1) / (K2 - K1)
    r = R1 + t * (R2 - R1)
    b = B1 + t * (B2 - B1)
    log.debug(f"Kelvin {kelvin}K → R={r:.5f}  G=1.00000  B={b:.5f}")
    return r, 1.0, b


def encode_temperature_params(r: float, g: float, b: float) -> str:
    """float32 LE × 4: R, G, B, G2=+Inf (sentinel Canon EOS RP / darktable 4.6)."""
    raw = struct.pack("<ffff", r, g, b, float('inf'))
    log.debug(f"temperature params ({len(raw)} B): {raw.hex()}")
    return raw.hex()


# ── PODMIANA TEMPERATURY W PRESECIE XMP ──────────────────────────────────────
def patch_temperature_in_xmp(xmp_content: str, kelvin: int) -> str:
    """
    Podmienia darktable:params operacji temperature na wartość wynikającą z kelvin.
    Szuka wzorca operation="temperature" i wymienia pierwszy atrybut params.
    """
    r, g, b = kelvin_to_multipliers(kelvin)
    temp_hex = encode_temperature_params(r, g, b)

    # Wzorzec: blok rdf:li zawierający operation="temperature" — podmień params
    pattern = (
        r'(darktable:operation="temperature"[^/]*?'
        r'darktable:params=")[^"]*(")'
    )
    patched, count = re.subn(pattern, rf'\g<1>{temp_hex}\g<2>', xmp_content, flags=re.DOTALL)
    if count == 0:
        log.warning("Nie znaleziono operacji temperature w presecie — WB bez zmian")
    else:
        log.debug(f"Podmieniono temperature params: {temp_hex}")
    return patched


# ── SPRAWDZENIE ŚRODOWISKA ────────────────────────────────────────────────────
def check_env() -> None:
    import shutil
    if not shutil.which("darktable-cli"):
        log.error("darktable-cli nie znaleziony w PATH")
        sys.exit(1)
    ver = subprocess.run(
        ["darktable-cli", "--version"],
        capture_output=True, text=True
    )
    version_text = (ver.stdout or ver.stderr).split("\n")[0].strip()
    log.debug(f"darktable-cli: {version_text}")
    if DARKTABLE_VER not in version_text:
        log.warning(f"Pipeline testowany na darktable {DARKTABLE_VER}.x — sprawdź kompatybilność!")


# ── EKSPORT ───────────────────────────────────────────────────────────────────
def export_raw(raw: Path, xmp: Path, jpeg: Path) -> bool:
    cmd = [
        "darktable-cli", str(raw), str(xmp), str(jpeg),
        "--core", "--conf", f"plugins/imageio/format/jpeg/quality={JPEG_QUALITY}",
    ]
    log.debug("CMD: " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        log.debug(f"stdout:\n{result.stdout.strip()}")
    if result.stderr.strip():
        log.debug(f"stderr:\n{result.stderr.strip()}")
    return jpeg.exists()


def export_raw_fallback(raw: Path, jpeg: Path) -> bool:
    """Wywołanie bez XMP — ostatnia deska ratunku."""
    cmd = [
        "darktable-cli", str(raw), str(jpeg),
        "--core", "--conf", f"plugins/imageio/format/jpeg/quality={JPEG_QUALITY}",
    ]
    log.debug("FALLBACK CMD: " + " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        log.debug(f"stdout:\n{result.stdout.strip()}")
    if result.stderr.strip():
        log.debug(f"stderr:\n{result.stderr.strip()}")
    return jpeg.exists()


# ── GŁÓWNA FUNKCJA ────────────────────────────────────────────────────────────
def develop_file(raw: Path, preset_xmp: Path, out_jpeg: Path, kelvin: int | None) -> bool:
    """
    Wywołuje jeden plik RAW przez darktable-cli z presetem XMP.

    kelvin=None  → użyj presetu bez modyfikacji WB
    kelvin=0     → odczytaj WB z EXIF aparatu i podmień w presecie
    kelvin>0     → użyj podanej wartości i podmień w presecie
    """
    check_env()

    if not raw.exists():
        log.error(f"Plik RAW nie istnieje: {raw}")
        return False
    if not preset_xmp.exists():
        log.error(f"Preset XMP nie istnieje: {preset_xmp}")
        return False
    if raw.suffix.lower() not in RAW_EXT:
        log.warning(f"Nieznane rozszerzenie RAW: {raw.suffix}")

    log.info(f"RAW    : {raw.name}")
    log.info(f"Preset : {preset_xmp.name}")
    log.info(f"Out    : {out_jpeg.name}")

    # Przygotuj treść XMP
    xmp_content = preset_xmp.read_text(encoding="utf-8")

    if kelvin is None:
        # Tryb "z presetu" — nie dotykaj temperature
        log.info("WB     : z presetu XMP (bez zmian)")
    else:
        # kelvin=0 → odczytaj z EXIF, kelvin>0 → użyj podanej wartości
        if kelvin == 0:
            exif_k = get_wb_kelvin(raw)
            effective_k = exif_k if 3200 <= exif_k <= 8000 else 5800
            log.info(f"WB     : EXIF {exif_k}K → użyto {effective_k}K")
        else:
            effective_k = kelvin
            log.info(f"WB     : {effective_k}K (podany)")
        xmp_content = patch_temperature_in_xmp(xmp_content, effective_k)

    # Zapisz tymczasowy XMP obok RAW (darktable wymaga tego samego katalogu)
    tmp_xmp = raw.parent / (raw.name + ".tmp_dev.xmp")
    try:
        tmp_xmp.write_text(xmp_content, encoding="utf-8")
        log.debug(f"Tymczasowy XMP: {tmp_xmp.name}")

        ok = export_raw(raw, tmp_xmp, out_jpeg)
        if ok:
            log.info(f"✔ OK  {out_jpeg.name}  ({out_jpeg.stat().st_size // 1024} kB)")
            return True

        # Fallback bez XMP
        log.warning("Eksport z XMP nieudany → fallback bez XMP")
        ok = export_raw_fallback(raw, out_jpeg)
        if ok:
            log.warning(f"⚠ FALLBACK  {out_jpeg.name}  ({out_jpeg.stat().st_size // 1024} kB)")
            return True

        log.error(f"Eksport nieudany: {raw.name}")
        return False

    finally:
        if tmp_xmp.exists():
            tmp_xmp.unlink()
            log.debug(f"Usunięto tymczasowy XMP: {tmp_xmp.name}")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Wywołaj pojedynczy plik RAW przez darktable-cli z presetem XMP."
    )
    parser.add_argument("raw",        help="Ścieżka do pliku RAW")
    parser.add_argument("preset_xmp", help="Ścieżka do presetu XMP")
    parser.add_argument("out_jpeg",   help="Ścieżka wyjściowego JPEG")
    parser.add_argument(
        "--kelvin", type=int, default=None,
        help="Temperatura WB w Kelvinach (0=z EXIF, brak=z presetu)"
    )
    args = parser.parse_args()

    success = develop_file(
        raw        = Path(args.raw),
        preset_xmp = Path(args.preset_xmp),
        out_jpeg   = Path(args.out_jpeg),
        kelvin     = args.kelvin,
    )
    sys.exit(0 if success else 1)
