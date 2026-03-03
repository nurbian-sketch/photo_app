"""
CameraSettingsWorker — lekki wątek ustawień aparatu bez live view.

Interface kompatybilny z GPhotoInterface (update_camera_param, settings_loaded).
Używany gdy LV nieaktywne, ale aparat podłączony przez USB.

session_mode_init=True: po połączeniu sprawdza i ustawia tryb Fv + drivemode 2s
(wymagane przed sesją bezprzewodową).
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from typing import Optional

os.environ.setdefault('LANGUAGE', 'C')
import gphoto2 as gp
from PyQt6.QtCore import QMutex, QThread, pyqtSignal

logger = logging.getLogger(__name__)

# Wymagane wartości konfiguracji przed sesją
_SESSION_CAMERA_MODE = 'Fv'
_SESSION_DRIVE_MODE  = 'Timer 2 sec'

# Parametry exposure mające wartość Auto = 00ff
_EXPOSURE_PARAMS = {'shutterspeed', 'aperture', 'iso', 'exposurecompensation'}


class CameraSettingsWorker(QThread):
    """
    Wątek ustawień aparatu — bez live view.
    Kompatybilny interfejs z GPhotoInterface:
      update_camera_param(name, value) — dodaje do kolejki
      settings_loaded(dict)            — emitowany po odczycie konfiguracji

    Dodatkowy sygnał:
      status_message(str)  — komunikaty o automatycznych zmianach trybu
    """

    settings_loaded = pyqtSignal(dict)
    status_message  = pyqtSignal(str)

    def __init__(self, session_mode_init: bool = False, parent=None):
        """
        session_mode_init: gdy True — po połączeniu sprawdza i ustawia
            tryb Fv oraz drivemode (samowyzwalacz 2s).
        """
        super().__init__(parent)
        self.keep_running      = True   # False ustawiane przez stop() przed/w trakcie run()
        self.camera: Optional[gp.Camera] = None
        self.context           = gp.Context()
        self.mutex             = QMutex()
        self.command_queue     = deque(maxlen=32)
        self.session_mode_init = session_mode_init

    # ─────────────────────────── API publiczne

    def update_camera_param(self, name: str, value: str):
        """Dodaje komendę do kolejki (thread-safe). Interfejs zgodny z GPhotoInterface."""
        self.mutex.lock()
        try:
            self.command_queue.append((name, value))
        finally:
            self.mutex.unlock()

    # ─────────────────────────── Wątek główny

    def run(self):
        try:
            if not self._connect():
                return

            # Sprawdź stop po połączeniu (stop() mógł być wywołany podczas connect)
            if not self.keep_running:
                return

            config = self._load_config()
            if config:
                self.settings_loaded.emit(config)

            if self.session_mode_init and self.keep_running:
                self._apply_session_init()

            while self.keep_running:
                self._process_queue()
                time.sleep(0.1)

        except Exception as e:
            logger.exception(f"CameraSettingsWorker: nieoczekiwany błąd: {e}")
        finally:
            self._safe_exit()

    # ─────────────────────────── Połączenie

    def _connect(self) -> bool:
        """Łączy z aparatem przez USB. Zwraca True przy sukcesie.
        Ponawia 3 razy z pauzą 0.5s — na wypadek że USB właśnie się zwalnia."""
        for attempt in range(3):
            try:
                pil = gp.PortInfoList()
                pil.load()
                al = gp.CameraAbilitiesList()
                al.load(self.context)
                cams = al.detect(pil, self.context)

                if not cams:
                    logger.debug(f"CameraSettingsWorker: brak aparatu (próba {attempt+1})")
                    time.sleep(0.5)
                    continue

                model, port = cams[0]
                self.camera = gp.Camera()
                self.camera.set_abilities(al[al.lookup_model(model)])
                self.camera.set_port_info(pil[pil.lookup_path(port)])
                self.camera.init(self.context)
                logger.info(f"CameraSettingsWorker: połączono z {model}")
                return True

            except gp.GPhoto2Error as e:
                logger.debug(f"CameraSettingsWorker: błąd połączenia {e.code} (próba {attempt+1})")
                self.camera = None
                time.sleep(0.5)
            except Exception as e:
                logger.debug(f"CameraSettingsWorker: błąd połączenia: {e} (próba {attempt+1})")
                self.camera = None
                time.sleep(0.5)

        logger.info("CameraSettingsWorker: nie udało się połączyć z aparatem")
        return False

    # ─────────────────────────── Odczyt konfiguracji

    def _load_config(self) -> dict:
        """Odczytuje konfigurację aparatu — identycznie jak GPhotoInterface."""
        if not self.camera:
            return {}
        try:
            config  = self.camera.get_config(self.context)
            results = {}

            # Parametry exposure
            for name in ['shutterspeed', 'aperture', 'iso', 'exposurecompensation']:
                try:
                    w           = config.get_child_by_name(name)
                    raw_choices = list(w.get_choices())
                    if not raw_choices:
                        continue
                    curr    = self._clean_value(w.get_value())
                    choices = [self._clean_value(c) for c in raw_choices]
                    results[name] = {"current": curr, "choices": choices}
                except Exception:
                    continue

            # Parametry image + AF
            for name in [
                'whitebalance', 'colortemperature', 'picturestyle',
                'alomode', 'imageformat',
                'focusmode', 'afmethod', 'continuousaf',
                'meteringmode',
            ]:
                try:
                    w = config.get_child_by_name(name)
                    curr = w.get_value()
                    try:
                        choices = [str(c) for c in w.get_choices()]
                    except Exception:
                        choices = []
                    results[name] = {"current": str(curr), "choices": choices}
                except Exception:
                    continue

            return results

        except Exception as e:
            logger.warning(f"CameraSettingsWorker: błąd odczytu konfiguracji: {e}")
            return {}

    # ─────────────────────────── Inicjalizacja trybu sesji

    def _apply_session_init(self):
        """Sprawdza i w razie potrzeby ustawia tryb Fv + samowyzwalacz 2s."""
        if not self.camera:
            return
        try:
            config = self.camera.get_config(self.context)

            # ── Tryb aparatu → Fv
            try:
                w    = config.get_child_by_name('autoexposuremode')
                curr = w.get_value()
                if curr != _SESSION_CAMERA_MODE:
                    w.set_value(_SESSION_CAMERA_MODE)
                    self.camera.set_config(config, self.context)
                    msg = f"Camera mode: {curr} → {_SESSION_CAMERA_MODE}"
                    logger.info(f"CameraSettingsWorker: {msg}")
                    self.status_message.emit(msg)
                    # Przeładuj config po zmianie
                    config = self.camera.get_config(self.context)
            except Exception as e:
                logger.warning(f"CameraSettingsWorker: nie można ustawić trybu Fv: {e}")

            # ── Drive mode → Timer 2 sec
            try:
                w    = config.get_child_by_name('drivemode')
                curr = w.get_value()
                if curr != _SESSION_DRIVE_MODE:
                    w.set_value(_SESSION_DRIVE_MODE)
                    self.camera.set_config(config, self.context)
                    msg = f"Drive mode: {curr} → {_SESSION_DRIVE_MODE}"
                    logger.info(f"CameraSettingsWorker: {msg}")
                    self.status_message.emit(msg)
            except Exception as e:
                logger.warning(f"CameraSettingsWorker: nie można ustawić drivemode: {e}")

        except Exception as e:
            logger.warning(f"CameraSettingsWorker: _apply_session_init błąd: {e}")

    # ─────────────────────────── Kolejka komend

    def _process_queue(self):
        self.mutex.lock()
        try:
            cmds = list(self.command_queue)
            self.command_queue.clear()
        finally:
            self.mutex.unlock()

        for name, value in cmds:
            self._execute_update(name, value)

    def _execute_update(self, name: str, value: str) -> bool:
        """Wysyła parametr do aparatu. Zwraca True przy sukcesie."""
        if not self.camera:
            return False
        try:
            config = self.camera.get_config(self.context)
            widget = config.get_child_by_name(name)
            target = str(value)

            # Auto → 00ff dla parametrów exposure
            if target == 'Auto' and name in _EXPOSURE_PARAMS:
                target = next(
                    (c for c in widget.get_choices()
                     if '00ff' in c.lower() or 'bulb' in c.lower()),
                    'Auto'
                )

            widget.set_value(target)
            self.camera.set_config(config, self.context)
            logger.debug(f"CameraSettingsWorker: {name} = '{target}'")
            return True

        except gp.GPhoto2Error as e:
            logger.warning(f"CameraSettingsWorker: błąd ustawiania {name}={value}: {e.code}")
            return False
        except Exception as e:
            logger.warning(f"CameraSettingsWorker: błąd ustawiania {name}={value}: {e}")
            return False

    # ─────────────────────────── Pomocnicze

    def _clean_value(self, val) -> str:
        v = str(val).lower()
        return 'Auto' if ('00ff' in v or 'bulb' in v) else str(val)

    def _safe_exit(self):
        if self.camera:
            try:
                self.camera.exit(self.context)
                logger.info("CameraSettingsWorker: aparat bezpiecznie odłączony")
            except Exception as e:
                logger.warning(f"CameraSettingsWorker: błąd zamykania: {e}")
            finally:
                self.camera = None
