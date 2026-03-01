from pathlib import Path
import piexif

from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtCore import Qt


_CR3_EXTENSIONS = {'.cr3'}
_ORIENTATION_MAP = {1: 0, 3: 180, 6: 90, 8: 270}


def _tiff_orientation_scan(data: bytes) -> int:
    """
    Skanuje binarne dane (np. pierwsze 512KB CR3) w poszukiwaniu tagu
    Orientation (0x0112) w strukturze TIFF/EXIF. Bez subprocess, bez I/O.
    """
    import struct
    offset = 0
    while offset < len(data) - 8:
        ii = data.find(b'II\x2a\x00', offset)
        mm = data.find(b'MM\x00\x2a', offset)
        candidates = [x for x in (ii, mm) if x >= 0]
        if not candidates:
            break
        pos = min(candidates)
        bo = '<' if data[pos:pos + 2] == b'II' else '>'
        try:
            ifd_offset = struct.unpack_from(bo + 'I', data, pos + 4)[0]
            ifd_abs = pos + ifd_offset
            if ifd_abs + 2 > len(data):
                offset = pos + 1
                continue
            num_entries = struct.unpack_from(bo + 'H', data, ifd_abs)[0]
            if not (1 <= num_entries <= 500):
                offset = pos + 1
                continue
            for i in range(num_entries):
                entry_abs = ifd_abs + 2 + i * 12
                if entry_abs + 12 > len(data):
                    break
                tag = struct.unpack_from(bo + 'H', data, entry_abs)[0]
                if tag == 0x0112:  # Orientation
                    val = struct.unpack_from(bo + 'H', data, entry_abs + 8)[0]
                    return _ORIENTATION_MAP.get(val, 0)
        except Exception:
            pass
        offset = pos + 1
    return 0


class ExifThumbnailReader:
    """
    Czyta embedded thumbnail z EXIF, obraca wg Orientation.
    JPEG/CR2/NEF → piexif (szybkie, brak subprocess).
    CR3           → SOI scan w pierwszych 512KB pliku.
                    Orientacja z companion JPG (piexif nie obsługuje CR3).
    """

    def read(self, path: Path) -> QPixmap | None:
        if path.suffix.lower() in _CR3_EXTENSIONS:
            return self._read_cr3(path)
        return self._read_piexif(path)

    # ─────────────────────────── JPEG / CR2 / NEF

    def _read_piexif(self, path: Path) -> QPixmap | None:
        try:
            exif = piexif.load(str(path))
            thumbnail = exif.get('thumbnail')
            if not thumbnail:
                return None
            pixmap = QPixmap()
            pixmap.loadFromData(thumbnail)
            if pixmap.isNull():
                return None
            return self._apply_orientation(pixmap, exif)
        except Exception:
            return None

    # ─────────────────────────── CR3

    def _read_cr3(self, path: Path) -> QPixmap | None:
        try:
            with open(path, 'rb') as f:
                data = f.read(512 * 1024)

            soi = data.find(b'\xff\xd8')
            if soi < 0:
                return None

            eoi = data.find(b'\xff\xd9', soi)
            if eoi < 0:
                return None

            jpeg_bytes = data[soi:eoi + 2]
            pixmap = QPixmap()
            pixmap.loadFromData(jpeg_bytes)
            if pixmap.isNull():
                return None

            # Priorytet: companion JPG (RAW+L) — zawsze poprawna orientacja.
            # Fallback: skan TIFF/EXIF w binarnych danych CR3 —
            # potrzebny gdy companion jeszcze nie istnieje (np. SD card,
            # pliki pobierane po kolei i JPG jeszcze nie dotarł do /tmp).
            orientation = self.read_cr3_orientation(path)
            if orientation == 0:
                orientation = _tiff_orientation_scan(data)
            return self._rotate(pixmap, orientation)

        except Exception:
            return None

    # ─────────────────────────── helpers

    def _apply_orientation(self, pixmap: QPixmap, exif: dict) -> QPixmap:
        try:
            orientation = exif.get('0th', {}).get(piexif.ImageIFD.Orientation)
            angle = {3: 180, 6: 90, 8: 270}.get(orientation, 0)
            return self._rotate(pixmap, angle)
        except Exception:
            return pixmap

    def _rotate(self, pixmap: QPixmap, angle: int) -> QPixmap:
        if not angle:
            return pixmap
        return pixmap.transformed(
            QTransform().rotate(angle),
            Qt.TransformationMode.SmoothTransformation
        )

    @staticmethod
    def read_cr3_orientation(path: Path) -> int:
        """Zwraca kat rotacji (0/90/180/270) z CR3.
        Priorytet: companion JPG (piexif nie obsluguje CR3 natywnie).
        Fallback: 0."""
        for suffix in ('.JPG', '.jpg', '.JPEG', '.jpeg'):
            companion = path.with_suffix(suffix)
            if companion.exists():
                try:
                    exif = piexif.load(str(companion))
                    ifd0 = exif.get('0th', {})
                    v = ifd0.get(piexif.ImageIFD.Orientation, 1)
                    return {1: 0, 3: 180, 6: 90, 8: 270}.get(v, 0)
                except Exception:
                    pass
        return 0
