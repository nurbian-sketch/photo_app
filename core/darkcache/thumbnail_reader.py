from pathlib import Path
import piexif

from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtCore import Qt


class ExifThumbnailReader:
    """
    Czyta embedded thumbnail z EXIF (bez crop),
    obraca wg Orientation.
    """

    def read(self, path: Path) -> QPixmap | None:
        try:
            exif = piexif.load(str(path))
            thumbnail = exif.get("thumbnail")

            if not thumbnail:
                return None

            pixmap = QPixmap()
            pixmap.loadFromData(thumbnail)

            if pixmap.isNull():
                return None

            return self._apply_orientation(pixmap, exif)

        except Exception:
            return None

    def _apply_orientation(self, pixmap: QPixmap, exif: dict) -> QPixmap:
        try:
            orientation = exif.get("0th", {}).get(piexif.ImageIFD.Orientation)

            transform = QTransform()
            if orientation == 3:
                transform.rotate(180)
            elif orientation == 6:
                transform.rotate(90)
            elif orientation == 8:
                transform.rotate(-90)

            if orientation in (3, 6, 8):
                pixmap = pixmap.transformed(transform)

        except Exception:
            pass

        return pixmap

