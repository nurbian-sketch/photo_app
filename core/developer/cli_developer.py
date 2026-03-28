#!/usr/bin/env python3
"""
cli_developer.py — wywołanie pojedynczego pliku RAW przez darktable-cli.

Użycie:
    python3 cli_developer.py <raw> <style> <out_jpeg> [--kelvin <int>]

Tryby stylu:
    "__auto__"              — bez stylu (darktable domyślnie)
    "Nazwa stylu"           — styl z bazy darktable (~/.config/darktable/data.db)
    "/ścieżka/plik.dtstyle" — importuje plik do bazy i używa

Tryby WB:
    --kelvin 0   — WB z EXIF aparatu (domyślne)
    brak         — EXIF (tak samo)
    --kelvin N   — ręczna wartość (TODO: nie wspierana w trybie --style)
"""

import argparse
import base64
import sqlite3
import subprocess
import sys
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

# ── KONFIGURACJA ─────────────────────────────────────────────────────────────
JPEG_QUALITY   = 95
RAW_EXT        = {".cr2", ".cr3", ".nef", ".arw", ".dng"}
DARKTABLE_VER  = "4.6"
EXPORT_TIMEOUT = 300   # sekund — zabezpieczenie gdy GUI trzyma SQLite lock

DARKTABLE_DB   = Path("~/.config/darktable/data.db").expanduser()

_AUTO_PRESET = "__auto__"

# ── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(levelname)-7s] %(message)s"
)
log = logging.getLogger("cli_developer")


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


# ── DETEKCJA GUI DARKTABLE ────────────────────────────────────────────────────
def darktable_gui_running() -> bool:
    """Zwraca True gdy darktable GUI jest uruchomione (trzyma lock na data.db)."""
    return subprocess.run(
        ["pgrep", "-x", "darktable"], capture_output=True
    ).returncode == 0


# ── IMPORT STYLU DO BAZY DARKTABLE ───────────────────────────────────────────
def ensure_style_in_db(style_name: str, dtstyle_path: Path | None = None) -> bool:
    """
    Sprawdza czy styl istnieje w bazie darktable.
    Jeśli nie i podano dtstyle_path — importuje z pliku XML.
    Zwraca True gdy styl jest dostępny do użycia.
    """
    if not DARKTABLE_DB.exists():
        log.error(f"Baza darktable nie istnieje: {DARKTABLE_DB}")
        return False

    con = None
    try:
        con = sqlite3.connect(str(DARKTABLE_DB))

        # Sprawdź czy styl już istnieje
        row = con.execute(
            "SELECT id FROM styles WHERE name=?", (style_name,)
        ).fetchone()

        if row:
            log.debug(f"Styl '{style_name}' już w bazie (id={row[0]})")
            return True

        # Styl nie istnieje — importuj z pliku .dtstyle
        if dtstyle_path is None or not dtstyle_path.exists():
            log.error(f"Styl '{style_name}' nie w bazie i brak pliku .dtstyle")
            return False

        log.info(f"Importuję styl '{style_name}' z {dtstyle_path.name}")

        tree = ET.parse(str(dtstyle_path))
        root = tree.getroot()

        # Odczytaj opis
        description = ""
        info = root.find("info")
        if info is not None:
            desc_el = info.find("description")
            if desc_el is not None and desc_el.text:
                description = desc_el.text.strip()

        # Wstaw rekord stylu
        cur = con.execute(
            "INSERT INTO styles (name, description) VALUES (?, ?)",
            (style_name, description)
        )
        style_id = cur.lastrowid

        # Wstaw elementy historii stylu
        for plugin in root.findall(".//plugin"):
            def _text(tag, default=""):
                el = plugin.find(tag)
                return el.text.strip() if el is not None and el.text else default

            num            = int(_text("num",            "0"))
            module         = int(_text("module",         "1"))
            operation      =     _text("operation")
            op_params_b64  =     _text("op_params")
            blendop_b64    =     _text("blendop_params")
            blendop_ver    = int(_text("blendop_version","13"))
            multi_priority = int(_text("multi_priority", "0"))
            multi_name     =     _text("multi_name")
            enabled        = int(_text("enabled",        "1"))

            # Params w dtstyle są base64 — baza przechowuje BLOB
            op_blob    = base64.b64decode(op_params_b64) if op_params_b64 else b""
            blend_blob = base64.b64decode(blendop_b64)   if blendop_b64   else b""

            con.execute(
                """INSERT INTO style_items
                   (styleid, num, module, operation, op_params, enabled,
                    blendop_params, blendop_version, multi_priority, multi_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (style_id, num, module, operation, op_blob, enabled,
                 blend_blob, blendop_ver, multi_priority, multi_name)
            )

        con.commit()
        log.info(f"Styl '{style_name}' zaimportowany (id={style_id})")
        return True

    except Exception as exc:
        log.error(f"Błąd importu stylu '{style_name}': {exc}")
        return False
    finally:
        if con:
            con.close()


# ── EKSPORT ───────────────────────────────────────────────────────────────────
def export_with_style(raw: Path, style_name: str, jpeg: Path,
                      opencl: bool = True) -> bool:
    """Eksportuje RAW z podanym stylem darktable (GPU domyślnie)."""
    cmd = [
        "darktable-cli", str(raw), str(jpeg),
        "--style", style_name,
        "--core",
        "--conf", f"plugins/imageio/format/jpeg/quality={JPEG_QUALITY}",
        "--conf", "plugins/imageio/format/jpeg/bpp=8",
        "--conf", "plugins/colorout/iccprofile=sRGB",
        "--conf", f"opencl={'true' if opencl else 'false'}",
    ]
    log.debug("CMD: " + " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=EXPORT_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        log.error(f"Timeout ({EXPORT_TIMEOUT}s) — darktable GUI może trzymać lock")
        return False
    if result.stdout.strip():
        log.debug(f"stdout:\n{result.stdout.strip()}")
    if result.stderr.strip():
        log.debug(f"stderr:\n{result.stderr.strip()}")
    return jpeg.exists()


def export_auto(raw: Path, jpeg: Path, opencl: bool = True) -> bool:
    """Eksportuje RAW bez stylu — darktable auto pipeline."""
    cmd = [
        "darktable-cli", str(raw), str(jpeg),
        "--core",
        "--conf", f"plugins/imageio/format/jpeg/quality={JPEG_QUALITY}",
        "--conf", "plugins/imageio/format/jpeg/bpp=8",
        "--conf", "plugins/colorout/iccprofile=sRGB",
        "--conf", f"opencl={'true' if opencl else 'false'}",
    ]
    log.debug("CMD: " + " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=EXPORT_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        log.error(f"Timeout ({EXPORT_TIMEOUT}s)")
        return False
    if result.stdout.strip():
        log.debug(f"stdout:\n{result.stdout.strip()}")
    if result.stderr.strip():
        log.debug(f"stderr:\n{result.stderr.strip()}")
    return jpeg.exists()


# ── GŁÓWNA FUNKCJA ────────────────────────────────────────────────────────────
def develop_file(raw: Path, preset: str, out_jpeg: Path,
                 kelvin: int | None) -> bool:
    """
    Wywołuje darktable-cli dla jednego pliku RAW.

    preset:
        "__auto__"              — bez stylu
        "Nazwa stylu"           — styl z bazy darktable
        "/ścieżka/plik.dtstyle" — import do bazy + użycie

    kelvin:
        0 lub None → WB z EXIF (darktable domyślnie)
        N>0        → TODO: nie wspierane w trybie --style (loguje ostrzeżenie)
    """
    check_env()

    if not raw.exists():
        log.error(f"Plik RAW nie istnieje: {raw}")
        return False
    if raw.suffix.lower() not in RAW_EXT:
        log.warning(f"Nieznane rozszerzenie RAW: {raw.suffix}")

    log.info(f"RAW    : {raw.name}")
    log.info(f"Preset : {preset}")
    log.info(f"Out    : {out_jpeg.name}")

    if kelvin is not None and kelvin > 0:
        log.warning(
            f"Ręczna wartość WB ({kelvin}K) nie jest wspierana w trybie --style"
            " — WB z EXIF"
        )

    # Tryb: bez stylu
    if preset == _AUTO_PRESET:
        log.info("Tryb: auto (bez stylu)")
        ok = export_auto(raw, out_jpeg)
        if ok:
            log.info(f"OK  {out_jpeg.name}  ({out_jpeg.stat().st_size // 1024} kB)")
        else:
            log.error(f"Eksport nieudany: {raw.name}")
        return ok

    # Tryb: plik .dtstyle — importuj do bazy
    p = Path(preset)
    if p.is_absolute() and preset.lower().endswith(".dtstyle"):
        style_name = p.stem
        if not ensure_style_in_db(style_name, p):
            log.error(f"Nie można zaimportować stylu z {preset}")
            return False
    else:
        style_name = preset

    log.info(f"Styl   : {style_name}")
    ok = export_with_style(raw, style_name, out_jpeg)
    if ok:
        log.info(f"OK  {out_jpeg.name}  ({out_jpeg.stat().st_size // 1024} kB)")
        return True

    # Fallback bez stylu
    log.warning("Eksport ze stylem nieudany => fallback auto")
    ok = export_auto(raw, out_jpeg)
    if ok:
        log.warning(f"FALLBACK  {out_jpeg.name}  ({out_jpeg.stat().st_size // 1024} kB)")
        return True

    log.error(f"Eksport nieudany: {raw.name}")
    return False


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Wywolaj pojedynczy plik RAW przez darktable-cli ze stylem."
    )
    parser.add_argument("raw",      help="Sciezka do pliku RAW")
    parser.add_argument("style",    help="Nazwa stylu, sciezka .dtstyle lub '__auto__'")
    parser.add_argument("out_jpeg", help="Sciezka wyjsciowego JPEG")
    parser.add_argument(
        "--kelvin", type=int, default=None,
        help="Temperatura WB w Kelvinach (0=z EXIF)"
    )
    args = parser.parse_args()

    success = develop_file(
        raw      = Path(args.raw),
        preset   = args.style,
        out_jpeg = Path(args.out_jpeg),
        kelvin   = args.kelvin,
    )
    sys.exit(0 if success else 1)
