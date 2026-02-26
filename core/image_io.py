"""
core/image_io.py

Shared image I/O and EXIF utilities used by camera_view and darkroom_view.

Responsibilities:
  - Detect and load image files: JPEG, PNG, RAW (CR3/CR2/NEF/ARW/ORF/RW2/DNG).
  - For RAW: try companion JPEG first (RAW+L pair), then extract embedded
    preview via exiftool.
  - Read EXIF metadata: shutter, aperture, ISO, focal length, date,
    dimensions, camera model, orientation.
    JPEG/companion → piexif (fast). RAW-only → exiftool -j (accurate dims).
  - Provide ImageLoader QThread for non-blocking async loading in UI.

Rules:
  - load_pixmap_from_path(), read_exif(), ImageLoader.run() — call from
    worker thread only (exiftool blocks).
  - No UI widgets here — only Qt data classes (QPixmap, QThread).
"""

import os

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QImageReader


# ─────────────────────────────── Stałe

RAW_EXTENSIONS = {'.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng'}


# ─────────────────────────────── Funkcje pomocnicze

def is_raw(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in RAW_EXTENSIONS


def find_companion_jpg(raw_path: str) -> str | None:
    """Szuka pliku JPG o tej samej nazwie bazowej co plik RAW (RAW + L JPEG)."""
    base = os.path.splitext(raw_path)[0]
    for ext in ('.jpg', '.JPG', '.jpeg', '.JPEG'):
        candidate = base + ext
        if os.path.exists(candidate):
            return candidate
    return None


def exiftool_extract_preview(path: str) -> str | None:
    """
    Wyciąga embedded PreviewImage z pliku RAW do temp JPEG.
    Zwraca ścieżkę do temp pliku (caller odpowiada za usunięcie) lub None.
    Wywołuj tylko z wątku roboczego.
    """
    import subprocess
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name
        with open(tmp_path, 'wb') as out_fh:
            result = subprocess.run(
                ['exiftool', '-b', '-PreviewImage', path],
                stdout=out_fh,
                stderr=subprocess.PIPE,
                timeout=10,
            )
        if result.returncode == 0 and os.path.getsize(tmp_path) > 0:
            return tmp_path
        os.unlink(tmp_path)
    except Exception as e:
        print(f"exiftool error ({os.path.basename(path)}): {e}")
    return None


# ─────────────────────────────── Ładowanie pixmapy

def load_pixmap_from_path(path: str) -> QPixmap:
    """
    Ładuje pixmapę z pliku JPEG lub RAW.
    Dla RAW: companion JPG (RAW+L) → exiftool PreviewImage.
    Wywołuj tylko z wątku roboczego — exiftool blokuje.
    """
    if not is_raw(path):
        pix = QPixmap(path)
        return pix if not pix.isNull() else QPixmap()

    # RAW + L JPEG — companion JPG w tym samym katalogu
    jpg = find_companion_jpg(path)
    if jpg:
        pix = QPixmap(jpg)
        if not pix.isNull():
            print(f"RAW+JPG companion: {os.path.basename(jpg)}")
            return pix

    # Embedded preview z RAW przez exiftool
    tmp_path = exiftool_extract_preview(path)
    if tmp_path:
        pix = QPixmap(tmp_path)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        if not pix.isNull():
            print(f"RAW preview via exiftool: {os.path.basename(path)}")
            return pix

    return QPixmap()


# ─────────────────────────────── EXIF

def read_exif(path: str) -> dict:
    """
    Czyta podstawowe dane EXIF.
    JPEG / companion JPG → piexif (szybkie, prawidłowa orientacja).
    RAW bez companion      → exiftool -j (prawdziwe wymiary sensora + orientacja).
    Wywołuj tylko z wątku roboczego.
    """
    r = {
        'shutter': '', 'aperture': '', 'iso': '', 'focal': '',
        'date': '', 'dims': '', 'size': '', 'camera': '', 'orientation': 0,
    }
    try:
        r['size'] = f"{os.path.getsize(path) / (1024 * 1024):.1f}\u00a0MB"
        if is_raw(path):
            jpg = find_companion_jpg(path)
            if jpg:
                _fill_exif_piexif(jpg, r)
            else:
                _fill_exif_exiftool_json(path, r)
        else:
            _fill_exif_piexif(path, r)
    except Exception as e:
        print(f"EXIF read error ({os.path.basename(path)}): {e}")
    return r


def _fill_exif_piexif(source_path: str, r: dict):
    """Wypełnia r danymi EXIF przez piexif (dla JPEG / companion JPG)."""
    import piexif

    exif = piexif.load(source_path)
    ifd0 = exif.get('0th', {})
    exif_ifd = exif.get('Exif', {})

    orientation_map = {1: 0, 3: 180, 6: 90, 8: 270}
    r['orientation'] = orientation_map.get(
        ifd0.get(piexif.ImageIFD.Orientation, 1), 0
    )

    reader = QImageReader(source_path)
    sz = reader.size()
    if sz.isValid():
        r['dims'] = f"{sz.width()}\u00d7{sz.height()}"

    def frac(v):
        if isinstance(v, tuple) and len(v) == 2 and v[1]:
            return v[0], v[1]
        return int(v), 1

    exp = exif_ifd.get(piexif.ExifIFD.ExposureTime)
    if exp:
        n, d = frac(exp)
        if n and d:
            ratio = d / n
            r['shutter'] = (
                f"1/{int(round(ratio))}s" if ratio >= 1 else f"{n / d:.1f}s"
            )

    fn = exif_ifd.get(piexif.ExifIFD.FNumber)
    if fn:
        n, d = frac(fn)
        if d:
            r['aperture'] = f"f/{n / d:.1f}"

    iso = exif_ifd.get(piexif.ExifIFD.ISOSpeedRatings)
    if iso:
        r['iso'] = f"ISO\u00a0{iso}"

    fl = exif_ifd.get(piexif.ExifIFD.FocalLength)
    if fl:
        n, d = frac(fl)
        if d:
            r['focal'] = f"{int(round(n / d))}mm"

    dt = (
        exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
        or ifd0.get(piexif.ImageIFD.DateTime)
    )
    if dt:
        s = dt.decode('ascii', errors='ignore') if isinstance(dt, bytes) else str(dt)
        r['date'] = s[:10].replace(':', '-') + ' ' + s[11:16]

    make = (ifd0.get(piexif.ImageIFD.Make) or b'').decode('ascii', errors='ignore').strip()
    model_b = (ifd0.get(piexif.ImageIFD.Model) or b'').decode('ascii', errors='ignore').strip()
    if model_b:
        r['camera'] = model_b if model_b.startswith(make) else (
            f"{make} {model_b}".strip() if make else model_b
        )


def _fill_exif_exiftool_json(path: str, r: dict):
    """
    Wypełnia r danymi EXIF przez exiftool -j (dla RAW bez companion JPG).
    Daje prawdziwe wymiary sensora i orientację z oryginalnego pliku RAW.
    """
    import subprocess
    import json

    try:
        result = subprocess.run(
            ['exiftool', '-j', '-n',
             '-Orientation', '-ImageWidth', '-ImageHeight',
             '-ExifImageWidth', '-ExifImageHeight',
             '-ExposureTime', '-FNumber', '-ISO',
             '-FocalLength', '-DateTimeOriginal',
             '-Make', '-Model', path],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
        data = json.loads(result.stdout)[0]

        orientation_map = {1: 0, 3: 180, 6: 90, 8: 270}
        r['orientation'] = orientation_map.get(int(data.get('Orientation', 1)), 0)

        w = data.get('ImageWidth') or data.get('ExifImageWidth')
        h = data.get('ImageHeight') or data.get('ExifImageHeight')
        if w and h:
            r['dims'] = f"{int(w)}\u00d7{int(h)}"

        exp = data.get('ExposureTime')
        if exp:
            try:
                v = float(exp)
                if v > 0:
                    r['shutter'] = (
                        f"1/{int(round(1 / v))}s" if v < 1 else f"{v:.1f}s"
                    )
            except (ValueError, ZeroDivisionError):
                pass

        fn = data.get('FNumber')
        if fn:
            r['aperture'] = f"f/{float(fn):.1f}"

        iso = data.get('ISO')
        if iso:
            r['iso'] = f"ISO\u00a0{int(iso)}"

        fl = data.get('FocalLength')
        if fl:
            r['focal'] = f"{int(round(float(fl)))}mm"

        dt = str(data.get('DateTimeOriginal', ''))
        if dt and len(dt) >= 16:
            r['date'] = dt[:10].replace(':', '-') + ' ' + dt[11:16]

        make = str(data.get('Make', '')).strip()
        model_s = str(data.get('Model', '')).strip()
        if model_s:
            r['camera'] = model_s if model_s.startswith(make) else (
                f"{make} {model_s}".strip() if make else model_s
            )
    except Exception as e:
        print(f"exiftool JSON error ({os.path.basename(path)}): {e}")


# ─────────────────────────────── Asynchroniczny loader

def _load_raw_no_companion(path: str) -> tuple:
    """
    Dla RAW bez companion JPG: ekstrahuje embedded JPEG raz,
    czyta pixmapę i EXIF z tego samego pliku — prawidłowa orientacja.
    """
    r = {
        'shutter': '', 'aperture': '', 'iso': '', 'focal': '',
        'date': '', 'dims': '', 'size': '', 'camera': '', 'orientation': 0,
    }
    try:
        r['size'] = f"{os.path.getsize(path) / (1024 * 1024):.1f}\u00a0MB"
    except OSError:
        pass

    tmp_path = exiftool_extract_preview(path)
    if not tmp_path:
        return QPixmap(), r

    pixmap = QPixmap(tmp_path)
    try:
        _fill_exif_piexif(tmp_path, r)
    except Exception:
        try:
            _fill_exif_exiftool_json(path, r)
        except Exception:
            pass

    # Rozmiar oryginalnego RAW, nie temp JPEG
    try:
        r['size'] = f"{os.path.getsize(path) / (1024 * 1024):.1f}\u00a0MB"
    except OSError:
        pass

    try:
        os.unlink(tmp_path)
    except OSError:
        pass

    return pixmap if not pixmap.isNull() else QPixmap(), r


class ImageLoader(QThread):
    """
    Ładuje pixmapę i EXIF w tle.
    Emituje loaded(pixmap, exif_dict) gdy gotowe.
    """
    loaded = pyqtSignal(object, dict)   # QPixmap, dict

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        if is_raw(self._path) and not find_companion_jpg(self._path):
            pixmap, exif = _load_raw_no_companion(self._path)
        else:
            pixmap = load_pixmap_from_path(self._path)
            exif = read_exif(self._path)
        self.loaded.emit(pixmap, exif)


# ─────────────────────────────── Aliasy — zgodność wsteczna (usunąć po Kroku 5)

_is_raw = is_raw
_find_companion_jpg = find_companion_jpg
_exiftool_extract_preview = exiftool_extract_preview
_load_pixmap_from_path = load_pixmap_from_path
_read_exif = read_exif
_ImageLoader = ImageLoader
