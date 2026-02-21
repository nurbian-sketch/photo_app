from pathlib import Path
from PyQt6.QtGui import QPixmap

from core.darkcache.cache_manager import PreviewCache
from core.darkcache.preview_generator import PreviewGenerator
from core.darkcache.thumbnail_reader import ExifThumbnailReader


class DarkCacheService:
    """
    Jedyny punkt dostępu do miniatur / preview.
    Zero UI. Zero side-effectów.
    """

    def __init__(
        self,
        cache: PreviewCache,
        preview_generator: PreviewGenerator,
        thumbnail_reader: ExifThumbnailReader,
    ):
        self.cache = cache
        self.preview_generator = preview_generator
        self.thumbnail_reader = thumbnail_reader

    def get_pixmap(self, path: Path, large: bool) -> QPixmap | None:
        if large:
            return self._get_large(path)
        else:
            return self._get_small(path)

    # ---------- internals ----------

    def _get_large(self, path: Path) -> QPixmap | None:
        pixmap = self.cache.get(path)
        if pixmap:
            return pixmap

        pixmap = self.preview_generator.generate(path)
        if pixmap:
            self.cache.put(path, pixmap)

        return pixmap

    def _get_small(self, path: Path) -> QPixmap | None:
        return self.thumbnail_reader.read(path)

