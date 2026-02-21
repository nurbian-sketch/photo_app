from pathlib import Path
import subprocess
import tempfile
import os

import piexif
from PyQt6.QtGui import QPixmap, QTransform
from PyQt6.QtCore import Qt


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
        try:
            exif = piexif.load(str(path))
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

    def _crop_square(self, pixmap: QPixmap) -> QPixmap:
        size = self.target_size

        if pixmap.width() < pixmap.height():
            pixmap = pixmap.scaledToWidth(size, Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = pixmap.scaledToHeight(size, Qt.TransformationMode.SmoothTransformation)

        x = (pixmap.width() - size) // 2
        y = (pixmap.height() - size) // 2

        return pixmap.copy(x, y, size, size)

