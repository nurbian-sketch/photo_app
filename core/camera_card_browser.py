"""
core/camera_card_browser.py

Przeglądarka plików karty SD aparatu przez gphoto2 PTP.
Pobiera każdy plik do katalogu tymczasowego — miniatury i podgląd
generuje istniejący pipeline dyskowy (DarkCacheService + ImageLoader).
"""
import os
import logging
import time

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

DCIM_ROOT = '/store_00020001/DCIM'
_TEMP_DIR = '/tmp/sessions_assistant_preview'


class CameraCardBrowserWorker(QThread):
    """
    Łączy się z aparatem przez PTP, listuje DCIM, pobiera każdy plik
    do katalogu tymczasowego i emituje jego lokalną ścieżkę.

    UI thread odbiera local_path i obsługuje miniatury oraz podgląd
    przez ten sam DarkCacheService + ImageLoader co pliki z dysku.

    Sygnały:
        file_found(ptp_folder, filename, local_path)
            — wyemitowany po pobraniu każdego pliku
        scan_finished(total_count, error_msg)
            — po przeskanowaniu całej karty; error_msg='' gdy OK
        progress(current, total, filename)
            — postęp skanowania
    """

    file_found    = pyqtSignal(str, str, str)  # (folder_ptp, nazwa, ścieżka_lokalna)
    scan_finished = pyqtSignal(int, str)        # (liczba_plików, błąd)
    progress      = pyqtSignal(int, int, str)   # (current, total, filename)

    def __init__(self):
        super().__init__()
        self._abort = False

    def abort(self):
        """Przerywa skanowanie — bezpieczne do wywołania z UI thread."""
        self._abort = True

    def run(self):
        import gphoto2 as gp

        os.makedirs(_TEMP_DIR, exist_ok=True)

        camera  = None
        context = gp.Context()
        found   = 0
        error   = ''

        try:
            camera = gp.Camera()
            camera.init(context)
            logger.info("CameraCardBrowser: połączono z aparatem")

            all_files = self._list_all_files(camera, context)
            total = len(all_files)
            logger.info(f"CameraCardBrowser: znaleziono {total} plików")

            for idx, (folder, fname) in enumerate(all_files):
                if self._abort:
                    break

                self.progress.emit(idx, total, fname)

                local_path = self._download_file(camera, context, folder, fname)
                if local_path:
                    self.file_found.emit(folder, fname, local_path)
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
                subfolder   = folders.get_name(i)
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

    def _download_file(
        self, camera, context, folder: str, fname: str
    ) -> str | None:
        """
        Pobiera plik z karty do _TEMP_DIR.
        Zwraca lokalną ścieżkę lub None przy błędzie.
        """
        import gphoto2 as gp

        dest = os.path.join(_TEMP_DIR, fname)

        # Plik już pobrany (poprzedni scan lub ten sam plik dwukrotnie)
        if os.path.exists(dest):
            return dest

        try:
            cam_file = gp.CameraFile()
            camera.file_get(
                folder, fname,
                gp.GP_FILE_TYPE_NORMAL,
                cam_file, context,
            )
            cam_file.save(dest)
            logger.debug(f"Pobrano: {fname}")
            return dest
        except Exception as e:
            logger.warning(f"Błąd pobierania {fname}: {e}")
            return None

    @classmethod
    def cleanup_temp(cls):
        """Usuwa katalog tymczasowy — wywołać przy wyjściu z trybu SD."""
        import shutil
        try:
            shutil.rmtree(_TEMP_DIR, ignore_errors=True)
            logger.debug("Wyczyszczono katalog tymczasowy SD card")
        except Exception:
            pass
