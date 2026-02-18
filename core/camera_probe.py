"""
Lekki moduł diagnostyczny aparatu.
Synchroniczne połączenie → odczyt → rozłączenie.
Nie uruchamia live view — tylko krótkie zapytania PTP.
Używany przez: initializer, main_window (przy zmianie widoku).
"""
import os
os.environ['LANGUAGE'] = 'C'

import logging
import time
import gphoto2 as gp

logger = logging.getLogger(__name__)

REQUIRED_MODE = 'Fv'


class CameraProbe:
    """Jednorazowe połączenie z aparatem do diagnostyki."""

    def __init__(self):
        self.camera = None
        self.context = None
        self.model = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.release()

    # ─────────────────────────── CONNECTION

    def connect(self) -> bool:
        """Wykrywa i inicjalizuje aparat. Zwraca True przy sukcesie."""
        try:
            self.context = gp.Context()
            pil = gp.PortInfoList()
            pil.load()
            al = gp.CameraAbilitiesList()
            al.load(self.context)
            cams = al.detect(pil, self.context)

            if len(cams) == 0:
                logger.info("CameraProbe: brak aparatu")
                return False

            model, port = cams[0]
            self.model = model

            self.camera = gp.Camera()
            self.camera.set_abilities(al[al.lookup_model(model)])
            self.camera.set_port_info(pil[pil.lookup_path(port)])
            self.camera.init(self.context)
            logger.info(f"CameraProbe: połączono z {model}")
            return True

        except gp.GPhoto2Error as e:
            logger.warning(f"CameraProbe connect error: {e.code}")
            return False
        except Exception as e:
            logger.warning(f"CameraProbe connect error: {e}")
            return False

    def release(self):
        """Zwalnia aparat — czyści port USB."""
        if self.camera:
            try:
                self.camera.exit(self.context)
            except Exception:
                pass
            self.camera = None
            self.context = None
            # USB potrzebuje chwili na reset portu
            time.sleep(0.3)

    @property
    def connected(self) -> bool:
        return self.camera is not None

    # ─────────────────────────── QUERIES

    def _get_widget(self, name):
        """Zwraca widget konfiguracji lub None."""
        try:
            config = self.camera.get_config(self.context)
            return config.get_child_by_name(name)
        except Exception:
            return None

    def _get_value(self, name) -> str:
        w = self._get_widget(name)
        return w.get_value() if w else ''

    def get_mode(self) -> str:
        """Zwraca tryb aparatu (P/TV/AV/Manual/Fv/...)."""
        return self._get_value('autoexposuremode')

    def is_fv_mode(self) -> bool:
        return self.get_mode() == REQUIRED_MODE

    def set_fv_mode(self) -> tuple:
        """
        Wymusza tryb Fv.
        Zwraca (success: bool, old_mode: str).
        old_mode to tryb PRZED zmianą (lub '' jeśli nie udało się odczytać).
        Jeśli aparat był już w Fv — old_mode == 'Fv', success == True.
        """
        try:
            config = self.camera.get_config(self.context)
            w = config.get_child_by_name('autoexposuremode')
            current = w.get_value()
            if current == REQUIRED_MODE:
                return True, REQUIRED_MODE  # Już w Fv
            w.set_value(REQUIRED_MODE)
            self.camera.set_config(config, self.context)
            logger.info(f"CameraProbe: tryb zmieniony {current} → {REQUIRED_MODE}")
            return True, current
        except Exception as e:
            logger.warning(f"CameraProbe: nie udało się ustawić Fv: {e}")
            return False, ''

    def get_battery(self) -> int:
        """Zwraca poziom baterii (0-100) lub -1."""
        val = self._get_value('batterylevel')
        try:
            return int(str(val).replace('%', '').strip())
        except (ValueError, AttributeError):
            return -1

    def check_storage(self) -> dict:
        """
        Sprawdza kartę SD. Zwraca dict:
        {ok, total_gb, free_gb, on_card, images_left, is_rw, percent_used}
        lub {ok: False} przy braku karty.
        """
        result = {'ok': False}
        try:
            info = self.camera.get_storageinfo(self.context)
            if not info:
                return result

            st = info[0]
            total_mb = getattr(st, 'capacitykbytes', 0) // 1024
            free_mb = getattr(st, 'freekbytes', 0) // 1024

            if total_mb <= 0:
                return result

            avg_photo_mb = 12
            is_rw = (getattr(st, 'access', -1) == 0)

            result = {
                'ok': is_rw and total_mb > 0,
                'total_gb': round(total_mb / 1024, 1),
                'free_gb': round(free_mb / 1024, 1),
                'on_card': self._count_files(),
                'images_left': int(free_mb / avg_photo_mb) if free_mb > 0 else 0,
                'is_rw': is_rw,
                'percent_used': ((total_mb - free_mb) / total_mb * 100) if total_mb > 0 else 0,
            }
            return result

        except Exception as e:
            logger.warning(f"CameraProbe storage error: {e}")
            return result

    def _count_files(self) -> int:
        try:
            count = 0
            folders = self.camera.folder_list_folders(
                '/store_00020001/DCIM', self.context
            )
            for i in range(folders.count()):
                name = folders.get_name(i)
                path = f'/store_00020001/DCIM/{name}'
                files = self.camera.folder_list_files(path, self.context)
                count += files.count()
            return count
        except Exception:
            return 0

    # ─────────────────────────── FULL CHECK

    def full_check(self) -> dict:
        """
        Pełna diagnostyka. Zwraca:
        {camera_on, sd_on, mode, battery, storage, model, warnings}
        """
        warnings = []

        if not self.connected:
            return {
                'camera_on': False, 'sd_on': False,
                'mode': '', 'battery': -1,
                'storage': {'ok': False},
                'model': '',
                'warnings': ['No camera found. Connect camera via USB.']
            }

        mode = self.get_mode()
        if mode != REQUIRED_MODE:
            warnings.append(
                f"Camera is in {mode} mode. Required: {REQUIRED_MODE}."
            )

        battery = self.get_battery()
        if 0 <= battery < 30:
            warnings.append(
                "Low battery! Change battery or connect AC power adapter."
            )

        storage = self.check_storage()
        if not storage['ok']:
            if storage.get('total_gb', 0) <= 0:
                warnings.append("No SD card! Insert a card to save photos.")
            elif not storage.get('is_rw', False):
                warnings.append(
                    "SD card is in Read-Only mode (check Lock switch)!"
                )

        if storage.get('percent_used', 0) > 80:
            warnings.append(
                f"Low card space (used {round(storage['percent_used'])}%)!"
            )

        return {
            'camera_on': True,
            'sd_on': storage['ok'],
            'mode': mode,
            'battery': battery,
            'storage': storage,
            'model': self.model or '',
            'warnings': warnings,
        }
