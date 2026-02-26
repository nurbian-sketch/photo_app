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

    def _get_small(self, path: Path) -> QPixmap:
        pixmap = self.thumbnail_reader.read(path)
        if pixmap and not pixmap.isNull():
            return self._to_square(pixmap, 120)
        # Brak embedded thumbnail — szary placeholder zamiast None
        return self._placeholder(120)

    @staticmethod
    def _placeholder(size: int) -> QPixmap:
        """Szary kwadrat gdy brak embedded thumbnail."""
        from PyQt6.QtGui import QColor
        canvas = QPixmap(size, size)
        canvas.fill(QColor("#2a2a2a"))
        return canvas

    @staticmethod
    def _trim_black(pixmap: QPixmap, threshold: int = 12) -> QPixmap:
        """Przycina czarne pasy z krawedzi (wypieczone przez aparat w EXIF thumbnail)."""
        img = pixmap.toImage()
        w, h = img.width(), img.height()

        def is_dark_row(y):
            for x in range(0, w, max(1, w // 16)):
                c = img.pixel(x, y)
                r, g, b = (c >> 16) & 0xff, (c >> 8) & 0xff, c & 0xff
                if r > threshold or g > threshold or b > threshold:
                    return False
            return True

        def is_dark_col(x):
            for y in range(0, h, max(1, h // 16)):
                c = img.pixel(x, y)
                r, g, b = (c >> 16) & 0xff, (c >> 8) & 0xff, c & 0xff
                if r > threshold or g > threshold or b > threshold:
                    return False
            return True

        top = 0
        while top < h and is_dark_row(top):
            top += 1
        bottom = h - 1
        while bottom > top and is_dark_row(bottom):
            bottom -= 1
        left = 0
        while left < w and is_dark_col(left):
            left += 1
        right = w - 1
        while right > left and is_dark_col(right):
            right -= 1

        if top == 0 and left == 0 and bottom == h - 1 and right == w - 1:
            return pixmap  # brak pasow — bez zmian
        return pixmap.copy(left, top, right - left + 1, bottom - top + 1)

    @staticmethod
    def _to_square(pixmap: QPixmap, size: int) -> QPixmap:
        """Center crop — przycina czarne pasy, skaluje wypelniajac kadr, przycina srodek."""
        from PyQt6.QtCore import Qt

        pixmap = DarkCacheService._trim_black(pixmap)

        # Skaluj tak aby krotszy bok = size (wypelnienie kwadratu bez czarnych pasow)
        scaled = pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Przetnij srodek do dokladnie size x size
        x = (scaled.width() - size) // 2
        y = (scaled.height() - size) // 2
        return scaled.copy(x, y, size, size)

