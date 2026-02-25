from pathlib import Path
import subprocess
import tempfile
import os

import piexif
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtCore import Qt

from core.darkcache.thumbnail_reader import ExifThumbnailReader


class PreviewGenerator:
    """
    Generuje DUŻE preview (240x240) z PreviewImage (exiftool)
    """

    def __init__(self, target_size: int = 240):
        self.target_size = target_size

    def generate(self, path: Path) -> QPixmap | None:
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp_path = tmp.name

            result = subprocess.run(
                ["exiftool", "-b", "-PreviewImage", str(path)],
                stdout=open(tmp_path, "wb"),
                stderr=subprocess.PIPE,
                timeout=5,
            )

            if result.returncode != 0 or os.path.getsize(tmp_path) == 0:
                os.unlink(tmp_path)
                return None

            pixmap = QPixmap(tmp_path)
            os.unlink(tmp_path)

            if pixmap.isNull():
                return None

            pixmap = self._apply_orientation(pixmap, path)
            pixmap = self._crop_square(pixmap)

            return pixmap

        except Exception:
            return None

    # ---------- helpers ----------

    def _apply_orientation(self, pixmap: QPixmap, path: Path) -> QPixmap:
        angle = 0
        try:
            if path.suffix.lower() == '.cr3':
                angle = ExifThumbnailReader.read_cr3_orientation(path)
            else:
                exif = piexif.load(str(path))
                orientation = exif.get('0th', {}).get(piexif.ImageIFD.Orientation)
                angle = {3: 180, 6: 90, 8: 270}.get(orientation, 0)
        except Exception:
            pass

        if angle:
            pixmap = pixmap.transformed(
                QTransform().rotate(angle),
                Qt.TransformationMode.SmoothTransformation
            )
        return pixmap

    def _crop_square(self, pixmap: QPixmap) -> QPixmap:
        size = self.target_size

        if pixmap.width() < pixmap.height():
            pixmap = pixmap.scaledToWidth(size, Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = pixmap.scaledToHeight(size, Qt.TransformationMode.SmoothTransformation)

        x = (pixmap.width() - size) // 2
        y = (pixmap.height() - size) // 2

        return pixmap.copy(x, y, size, size)

