"""
core/camera_card_browser.py

Przeglądarka plików karty SD aparatu przez gphoto2 PTP.
Listuje pliki i wyciąga thumbnails (GP_FILE_TYPE_PREVIEW) bez pobierania
pełnych plików na dysk.

Emituje file_found() dla każdego pliku osobno — miniatury pojawiają się
progressywnie tak samo jak przy lazy loading z dysku.
"""
import os
import logging
import time

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QPixmap

logger = logging.getLogger(__name__)

DCIM_ROOT = '/store_00020001/DCIM'


class CameraCardBrowserWorker(QThread):
    """
    Łączy się z aparatem przez PTP, listuje DCIM, wyciąga thumbnail
    każdego pliku (bez pełnego pobierania).

    Sygnały:
        file_found(camera_folder, filename, pixmap)
            — wyemitowany dla każdego pliku; pixmap może być null gdy
              aparat nie udostępnia preview dla danego formatu
        scan_finished(total_count, error_msg)
            — po przeskanowaniu całej karty; error_msg='' gdy OK
        progress(current, total, filename)
            — postęp skanowania
    """

    file_found    = pyqtSignal(str, str, object)   # (folder_na_karcie, nazwa, QPixmap)
    scan_finished = pyqtSignal(int, str)            # (liczba_plików, błąd)
    progress      = pyqtSignal(int, int, str)       # (current, total, filename)

    def __init__(self):
        super().__init__()
        self._abort = False

    def abort(self):
        """Przerywa skanowanie — bezpieczne do wywołania z UI thread."""
        self._abort = True

    def run(self):
        import gphoto2 as gp

        camera  = None
        context = gp.Context()
        found   = 0
        error   = ''

        try:
            camera = gp.Camera()
            camera.init(context)
            logger.info("CameraCardBrowser: połączono z aparatem")

            # Buduj listę plików (folder_na_karcie, nazwa)
            all_files = self._list_all_files(camera, context)
            total = len(all_files)
            logger.info(f"CameraCardBrowser: znaleziono {total} plików")

            for idx, (folder, fname) in enumerate(all_files):
                if self._abort:
                    break

                self.progress.emit(idx, total, fname)

                pixmap = self._get_thumbnail(camera, context, folder, fname)
                self.file_found.emit(folder, fname, pixmap)
                found += 1

                # Krótka przerwa — nie blokuj USB między żądaniami
                time.sleep(0.02)

        except Exception as e:
            error = str(e)
            logger.error(f"CameraCardBrowser: {e}")
        finally:
            if camera:
                try:
                    camera.exit(context)
                except Exception:
                    pass

        self.scan_finished.emit(found, error)

    # ─────────────────────────── helpers

    def _list_all_files(self, camera, context) -> list[tuple[str, str]]:
        """Zwraca listę (folder_ptp, nazwa_pliku) z całego DCIM."""
        import gphoto2 as gp

        result = []
        try:
            folders = camera.folder_list_folders(DCIM_ROOT, context)
            for i in range(folders.count()):
                if self._abort:
                    break
                subfolder = folders.get_name(i)
                folder_path = f'{DCIM_ROOT}/{subfolder}'
                try:
                    files = camera.folder_list_files(folder_path, context)
                    for j in range(files.count()):
                        result.append((folder_path, files.get_name(j)))
                except Exception as e:
                    logger.warning(f"Błąd listowania {folder_path}: {e}")
        except Exception as e:
            logger.warning(f"Błąd listowania DCIM: {e}")

        return result

    def _get_thumbnail(self, camera, context, folder: str, fname: str) -> QPixmap:
        """
        Wyciąga thumbnail z aparatu przez PTP (GP_FILE_TYPE_PREVIEW).
        Zwraca pustą QPixmap gdy aparat nie udostępnia preview.
        """
        import gphoto2 as gp

        try:
            camera_file = gp.CameraFile()
            camera.file_get(
                folder, fname,
                gp.GP_FILE_TYPE_PREVIEW,
                camera_file, context
            )
            data = camera_file.get_data_and_size()
            pixmap = QPixmap()
            pixmap.loadFromData(bytes(data))
            if not pixmap.isNull():
                # Przeskaluj do rozmiaru miniatury (120x120 center crop)
                return self._to_square(pixmap, 120)
        except Exception as e:
            logger.debug(f"Brak preview dla {fname}: {e}")

        return QPixmap()

    @staticmethod
    def _to_square(pixmap: QPixmap, size: int) -> QPixmap:
        """Center crop do kwadratu."""
        from PyQt6.QtCore import Qt

        scaled = pixmap.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (scaled.width()  - size) // 2
        y = (scaled.height() - size) // 2
        return scaled.copy(x, y, size, size)
