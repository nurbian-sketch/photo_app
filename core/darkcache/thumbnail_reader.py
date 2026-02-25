from pathlib import Path
import piexif

from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtCore import Qt


_CR3_EXTENSIONS = {'.cr3'}


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

            orientation = self.read_cr3_orientation(path)
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
