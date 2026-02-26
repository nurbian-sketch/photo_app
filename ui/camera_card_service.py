"""
CameraCardWorker — streamuje pliki z karty SD aparatu przez gphoto2 (PTP).
Dla każdego pliku emituje thumbnail (EXIF preview) i zapisuje pełny plik lokalnie.
Wymaga wolnego portu USB (Live View zatrzymane).
"""
import os
import logging
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class CameraCardWorker(QThread):
    """
    Jedno połączenie PTP: listuje pliki → dla każdego pobiera thumbnail
    i pełny plik. Emituje file_ready po każdym pobranym pliku.
    """
    file_ready = pyqtSignal(str)            # local_path
    progress   = pyqtSignal(int, int, str)  # (current_idx, total, filename)
    finished   = pyqtSignal(str, str)       # (dest_dir, error_msg)

    def __init__(self, dest_dir: str):
        super().__init__()
        self._dest = dest_dir

    def run(self):
        import gphoto2 as gp
        import time
        camera = None
        context = gp.Context()
        downloaded = 0
        error = ''

        def _reconnect():
            """Pelny reset polaczenia USB — nowy obiekt Camera i Context."""
            nonlocal camera, context
            try:
                camera.exit(context)
            except Exception:
                pass
            camera = None
            time.sleep(2.5)  # USB potrzebuje czasu na reset po zawieszonym transferze
            context = gp.Context()
            cam = gp.Camera()
            cam.init(context)
            return cam

        def _init_camera():
            cam = gp.Camera()
            cam.init(context)
            return cam

        try:
            camera = _init_camera()

            # Listowanie plikow na karcie
            files = []
            dcim = '/store_00020001/DCIM'
            try:
                folders = camera.folder_list_folders(dcim, context)
                for i in range(folders.count()):
                    subfolder = folders.get_name(i)
                    folder_path = f'{dcim}/{subfolder}'
                    filelist = camera.folder_list_files(folder_path, context)
                    for j in range(filelist.count()):
                        fname = filelist.get_name(j)
                        files.append((folder_path, fname))
            except Exception as e:
                raise RuntimeError(f"Blad listowania karty: {e}")

            total = len(files)
            for idx, (folder, fname) in enumerate(files):
                self.progress.emit(idx, total, fname)
                local_path = os.path.join(self._dest, fname)

                # Pelny plik — pomijaj jesli juz istnieje
                if not os.path.exists(local_path):
                    saved = False
                    for attempt in range(2):
                        try:
                            cam_file = gp.CameraFile()
                            camera.file_get(
                                folder, fname,
                                gp.GP_FILE_TYPE_NORMAL, cam_file, context
                            )
                            os.makedirs(self._dest, exist_ok=True)
                            cam_file.save(local_path)
                            saved = True
                            break
                        except Exception as e:
                            code = getattr(e, 'code', None)
                            logger.warning(f"Download {fname}: {e}")
                            if attempt == 0 and code in (-7, -52, -110):
                                # I/O, USB lub zawieszony transfer — pelny reset
                                logger.info(f"Blad {code} — pelny reconnect USB")
                                try:
                                    camera = _reconnect()
                                except Exception as re:
                                    error = f"Reconnect failed: {re}"
                                    saved = False
                                    break
                                # Ponow ten sam plik po reconnect
                            else:
                                break  # Nieznany blad — pominz plik
                    if not saved:
                        continue  # Nie emituj jesli plik nie zapisany

                downloaded += 1
                self.file_ready.emit(local_path)

        except Exception as e:
            error = str(e)
            logger.error(f"CameraCardWorker: {e}")
        finally:
            if camera:
                try:
                    camera.exit(context)
                except Exception:
                    pass

        self.finished.emit(self._dest if downloaded > 0 else '', error)
