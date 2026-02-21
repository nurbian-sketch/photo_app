from pathlib import Path
import os
import hashlib
from PyQt6.QtGui import QPixmap


class PreviewCache:
    """
    Odpowiada WYŁĄCZNIE za:
    - nazwę pliku cache
    - odczyt / zapis
    - odświeżenie czasu użycia
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, image_path: Path) -> Path:
        mtime = image_path.stat().st_mtime
        key = hashlib.md5(f"{image_path}{mtime}".encode()).hexdigest()
        return self.cache_dir / f"{key}.jpg"

    def get(self, image_path: Path) -> QPixmap | None:
        path = self._cache_path(image_path)

        if not path.exists():
            return None

        # touch (LRU w przyszłości)
        os.utime(path, None)

        pixmap = QPixmap(str(path))
        return pixmap if not pixmap.isNull() else None

    def put(self, image_path: Path, pixmap: QPixmap, quality: int = 90):
        path = self._cache_path(image_path)

        if pixmap and not pixmap.isNull():
            pixmap.save(str(path), "JPG", quality)

