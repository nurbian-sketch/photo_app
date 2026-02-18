import os
# Wymuszamy angielskie nazwy z libgphoto2 (gettext).
# PyQt6 aktywuje systemowe locale (pl_PL), co powoduje
# polskie tłumaczenia parametrów aparatu.
os.environ['LANGUAGE'] = 'C'

import gphoto2 as gp
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from collections import deque
import time
import logging
import subprocess

logger = logging.getLogger(__name__)


class GPhotoInterface(QThread):
    frame_received = pyqtSignal(bytes, bool)
    settings_loaded = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    image_captured = pyqtSignal(str)  # ścieżka do zapisanego pliku
    capture_failed = pyqtSignal(str)  # błąd capture — NIE zabija sesji LV

    # Kody błędów gphoto2
    ERR_USB = -52
    ERR_TIMEOUT = -110
    ERR_NO_SPACE = -53
    ERR_IO = -7
    ERR_BUSY = -110
    ERR_GENERIC = -1

    # Błędy USB — dłuższa pauza przed retry
    HEAVY_ERRORS = {ERR_USB, ERR_NO_SPACE}

    # Błędy lżejsze — krótka pauza
    LIGHT_ERRORS = {ERR_TIMEOUT, ERR_BUSY, ERR_GENERIC, ERR_IO}

    MAX_CONSECUTIVE_ERRORS = 20

    # Timeout dla stop() — normalny vs podczas capture
    STOP_TIMEOUT_MS = 3000
    STOP_TIMEOUT_CAPTURE_MS = 15000

    def __init__(self):
        super().__init__()
        self.keep_running = False
        self._capturing = False  # Flaga trwającego capture
        self.camera = None
        self.context = gp.Context()
        self.MAX_ISO = 1600
        self.MIN_SHUTTER_VAL = 0.25   # 1/4s
        self.MAX_SHUTTER_VAL = 0.001  # 1/1000s
        self.mutex = QMutex()
        self.command_queue = deque(maxlen=32)
        self._usb_bus_device = None  # Cache dla USB reset

    # ─────────────────────────────────── CAMERA DETECTION

    def _autodetect_camera(self):
        port_info_list = gp.PortInfoList()
        port_info_list.load()
        abilities_list = gp.CameraAbilitiesList()
        abilities_list.load(self.context)
        cameras = abilities_list.detect(port_info_list, self.context)
        if not cameras:
            raise Exception("Brak aparatu.")
        model, port = cameras[0]
        logger.info(f"Wykryto aparat: {model} na {port}")

        # Cache USB bus:device dla ewentualnego resetu
        # port format: "usb:001,004" → bus=001, dev=004
        if port.startswith("usb:"):
            self._usb_bus_device = port[4:]  # "001,004"

        self.camera = gp.Camera()
        self.camera.set_abilities(
            abilities_list[abilities_list.lookup_model(model)]
        )
        self.camera.set_port_info(
            port_info_list[port_info_list.lookup_path(port)]
        )

    # ─────────────────────────────────── VALUE PARSING

    def _clean_value(self, val):
        v = str(val).lower()
        return 'Auto' if ('00ff' in v or 'bulb' in v) else str(val)

    def _parse_shutter(self, val):
        try:
            if '/' in val:
                n, d = val.split('/')
                return float(n) / float(d)
            return float(val)
        except (ValueError, ZeroDivisionError):
            return 0

    # ─────────────────────────────────── MAIN LOOP

    def run(self):
        try:
            self._autodetect_camera()

            # Retry init — port USB może być jeszcze zajęty po zabiciu gvfs
            last_err = None
            for attempt in range(3):
                try:
                    if attempt > 0:
                        # Po nieudanym init() obiekt Camera jest uszkodzony
                        try:
                            self.camera.exit(self.context)
                        except Exception:
                            pass
                        self.camera = None
                        time.sleep(1.5)
                        self._autodetect_camera()

                    self.camera.init(self.context)
                    logger.info("Aparat zainicjalizowany.")
                    break
                except gp.GPhoto2Error as e:
                    last_err = e
                    logger.warning(
                        f"Init próba {attempt + 1}/3: błąd {e.code}"
                    )
            else:
                raise Exception(
                    f"Nie udało się zainicjalizować aparatu "
                    f"po 3 próbach (ostatni błąd: {last_err})"
                )

            expected_params = {
                'shutterspeed', 'aperture', 'iso', 'exposurecompensation'
            }
            initial_config = {}
            for attempt in range(5):
                config = self._get_filtered_config()
                initial_config.update(config)
                missing = expected_params - initial_config.keys()
                if not missing:
                    break
                logger.info(
                    f"Config próba {attempt + 1}/5 — brakuje: {missing}"
                )
                time.sleep(0.3)

            if initial_config:
                self.settings_loaded.emit(initial_config)
            
            if missing:
                logger.warning(
                    f"Nie udało się pobrać: {missing} po 5 próbach"
                )

            self.keep_running = True
            consecutive_errors = 0

            while self.keep_running:
                fps_sleep = 0.05

                # --- Przetwórz kolejkę komend ---
                self.mutex.lock()
                try:
                    while self.command_queue:
                        name, value = self.command_queue.popleft()
                        if name == '__CAPTURE__':
                            self._execute_capture(value)
                            fps_sleep = 0.5
                        else:
                            self._execute_update(name, value)
                            fps_sleep = 0.15
                finally:
                    self.mutex.unlock()

                # --- Przechwycenie klatki live view ---
                try:
                    camera_file = gp.CameraFile()
                    self.camera.capture_preview(camera_file, self.context)
                    file_data = camera_file.get_data_and_size()

                    typ, ev_data = self.camera.wait_for_event(
                        10, self.context
                    )
                    is_blinking = (
                        typ == gp.GP_EVENT_UNKNOWN
                        and "1,3,0.0" in str(ev_data)
                    )
                    self.frame_received.emit(bytes(file_data), is_blinking)
                    consecutive_errors = 0

                except gp.GPhoto2Error as e:
                    consecutive_errors += 1
                    logger.warning(
                        f"GPhoto2Error w pętli: code={e.code} "
                        f"(błąd {consecutive_errors}/{self.MAX_CONSECUTIVE_ERRORS})"
                    )

                    # Czyścimy kolejkę — stare komendy nie pomogą
                    self.mutex.lock()
                    try:
                        dropped = len(self.command_queue)
                        self.command_queue.clear()
                        if dropped:
                            logger.info(f"Wyczyszczono {dropped} komend z kolejki")
                    finally:
                        self.mutex.unlock()

                    if e.code in self.HEAVY_ERRORS:
                        fps_sleep = 1.5
                    elif e.code in self.LIGHT_ERRORS:
                        fps_sleep = 0.5
                    else:
                        fps_sleep = 0.5

                    if consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                        self.error_occurred.emit(
                            f"Zbyt wiele błędów ({consecutive_errors}). "
                            f"Ostatni: {e.code}. Przerywam."
                        )
                        self.keep_running = False
                        break

                except Exception as e:
                    consecutive_errors += 1
                    logger.exception("Nieoczekiwany błąd w pętli live view")
                    if consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                        self.error_occurred.emit(f"Powtarzający się błąd: {e}")
                        self.keep_running = False
                        break
                    fps_sleep = 0.5

                time.sleep(fps_sleep)

        except Exception as e:
            logger.exception("Błąd inicjalizacji aparatu")
            self.error_occurred.emit(str(e))

        finally:
            self._capturing = False  # Reset flagi przy wyjściu
            self._safe_camera_exit()

    def _safe_camera_exit(self):
        """Bezpieczne zamknięcie połączenia z aparatem."""
        if self.camera:
            try:
                self.camera.exit(self.context)
                logger.info("Aparat bezpiecznie odłączony.")
            except Exception as e:
                logger.warning(f"Błąd przy zamykaniu aparatu: {e}")
            finally:
                self.camera = None

    # ─────────────────────────────────── CONFIG READ

    def _get_filtered_config(self):
        try:
            config = self.camera.get_config(self.context)
            results = {}

            for name in [
                'shutterspeed', 'aperture', 'iso', 'exposurecompensation'
            ]:
                try:
                    w = config.get_child_by_name(name)
                    raw_choices = list(w.get_choices())

                    # Jeśli brak opcji — pomijamy, by nie czyścić UI
                    if not raw_choices:
                        continue

                    curr = self._clean_value(w.get_value())
                    choices = []

                    for c in raw_choices:
                        val = self._clean_value(c)
                        if (name == 'iso' and val.isdigit()
                                and int(val) > self.MAX_ISO):
                            continue
                        if name == 'shutterspeed' and val != 'Auto':
                            fv = self._parse_shutter(val)
                            if (fv > self.MIN_SHUTTER_VAL
                                    or fv < self.MAX_SHUTTER_VAL):
                                continue
                        if val not in choices:
                            choices.append(val)

                    if ("Auto" not in choices
                            and any('00ff' in str(c).lower()
                                    for c in raw_choices)):
                        choices.insert(0, "Auto")

                    results[name] = {"current": curr, "choices": choices}

                except gp.GPhoto2Error as e:
                    logger.debug(
                        f"Parametr {name} niedostępny: {e.code}"
                    )
                    continue
                except Exception as e:
                    logger.warning(
                        f"Błąd odczytu parametru {name}: {e}"
                    )
                    continue

            # Odczyt image + AF params z tego samego drzewa config
            for name in [
                'whitebalance', 'colortemperature', 'picturestyle',
                'alomode', 'imageformat',
                'focusmode', 'afmethod', 'continuousaf'
            ]:
                try:
                    w = config.get_child_by_name(name)
                    curr = w.get_value()
                    try:
                        choices = list(w.get_choices())
                    except Exception:
                        choices = []
                    results[name] = {
                        "current": str(curr),
                        "choices": [str(c) for c in choices]
                    }
                    print(
                        f"Config {name}: current='{curr}', "
                        f"choices={[str(c) for c in choices[:5]]}..."
                    )
                except Exception as e:
                    logger.warning(f"Image param {name} niedostępny: {e}")

            return results

        except gp.GPhoto2Error as e:
            logger.error(f"Nie można pobrać konfiguracji: {e.code}")
            return {}
        except Exception as e:
            logger.exception("Nieoczekiwany błąd konfiguracji")
            return {}

    # ─────────────────────────────────── PARAM UPDATE (API)

    def update_camera_param(self, name, value):
        """
        Dodaje komendę do kolejki (thread-safe).
        Wywoływane z wątku UI.
        """
        print(f"Queued: {name} = '{value}'")
        self.mutex.lock()
        try:
            self.command_queue.append((name, value))
        finally:
            self.mutex.unlock()

    def capture_photo(self, save_dir):
        """
        Kolejkuje zdjęcie do wykonania (thread-safe).
        Wywoływane z wątku UI.
        """
        print(f"Queued: __CAPTURE__ → {save_dir}")
        self.mutex.lock()
        try:
            self.command_queue.append(('__CAPTURE__', save_dir))
        finally:
            self.mutex.unlock()

    # Parametry exposure — tylko te mają 00ff Auto
    EXPOSURE_PARAMS = {'shutterspeed', 'aperture', 'iso', 'exposurecompensation'}

    def _execute_capture(self, save_dir):
        """
        Wykonuje zdjęcie i pobiera plik BEZPOŚREDNIO do komputera.
        Plik NIE jest zapisywany na karcie SD aparatu.
        Wywoływane WEWNĄTRZ pętli roboczej.
        """
        import os
        from datetime import datetime

        self._capturing = True  # ← Flaga: capture w toku
        original_target = None

        try:
            # 1. Przełącz capturetarget na RAM (nie kartę SD)
            try:
                config = self.camera.get_config(self.context)
                target_widget = config.get_child_by_name('capturetarget')
                original_target = target_widget.get_value()

                # Zawsze używamy Memory card — Internal RAM powoduje zawieszenie USB
                choices = list(target_widget.get_choices())
                card_option = None
                for choice in choices:
                    if 'card' in choice.lower() or 'memory' in choice.lower() or 'sd' in choice.lower():
                        card_option = choice
                        break

                if card_option and original_target != card_option:
                    print(f">>> CAPTURE: switching target {original_target} → {card_option}")
                    target_widget.set_value(card_option)
                    self.camera.set_config(config, self.context)
                    time.sleep(0.1)
                else:
                    print(f">>> CAPTURE: target already '{original_target}'")
                    original_target = None  # Nie przywracaj później

            except Exception as e:
                logger.warning(f"Could not set capturetarget: {e}")
                # Kontynuuj mimo błędu — capture może działać z domyślnym targetem

            # 2. Wykonaj zdjęcie
            print(">>> CAPTURE: trigger")
            file_path = self.camera.capture(
                gp.GP_CAPTURE_IMAGE, self.context
            )
            print(f"<<< CAPTURE: {file_path.folder}/{file_path.name}")

            # 3. Pobierz plik z aparatu (z RAM lub karty)
            camera_file = gp.CameraFile()
            self.camera.file_get(
                file_path.folder, file_path.name,
                gp.GP_FILE_TYPE_NORMAL, camera_file, self.context
            )

            # 4. Zapisz lokalnie: save_dir/captures/YYYYMMDD_HHMMSS_IMG_xxxx.CR3
            captures_dir = os.path.join(save_dir, "captures")
            os.makedirs(captures_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{file_path.name}"
            local_path = os.path.join(captures_dir, filename)

            camera_file.save(local_path)
            print(f"<<< SAVED: {local_path}")

            # 5. Usuń plik z aparatu (zwolnij RAM/kartę)
            try:
                self.camera.file_delete(
                    file_path.folder, file_path.name, self.context
                )
                print(f"<<< DELETED from camera: {file_path.name}")
            except Exception as e:
                logger.debug(f"Could not delete from camera (may be normal): {e}")

            self.image_captured.emit(local_path)

            # 6. Po capture aparat wychodzi z LV — restart preview
            time.sleep(0.3)
            try:
                recovery = gp.CameraFile()
                self.camera.capture_preview(recovery, self.context)
                print("<<< LV recovered after capture")
            except Exception:
                print("<<< LV recovery failed — next frame will retry")

            return True

        except gp.GPhoto2Error as e:
            logger.warning(f"Capture failed: gphoto2 error {e.code}")
            # NIE emituj error_occurred — to zabiłoby sesję LV!
            # capture_failed to "miękki" błąd, LV będzie próbować się odzyskać
            self.capture_failed.emit(f"Capture failed (error {e.code}). Retrying...")
            return False

        except Exception as e:
            logger.exception(f"Unexpected capture error: {e}")
            self.capture_failed.emit(f"Capture error: {e}")
            return False

        finally:
            self._capturing = False  # ← Zawsze resetuj flagę

            # Przywróć oryginalny capturetarget (jeśli zmienialiśmy)
            if original_target:
                try:
                    config = self.camera.get_config(self.context)
                    target_widget = config.get_child_by_name('capturetarget')
                    target_widget.set_value(original_target)
                    self.camera.set_config(config, self.context)
                    print(f"<<< CAPTURE: restored target → {original_target}")
                except Exception as e:
                    logger.warning(f"Could not restore capturetarget: {e}")

    def _execute_update(self, name, value) -> bool:
        """
        Wysyła parametr do aparatu. Zwraca True przy sukcesie.
        Wywoływane WEWNĄTRZ pętli roboczej (mutex już zablokowany).
        Przy błędzie NIE zatrzymuje live view — próbuje odzyskać sesję.
        """
        try:
            config = self.camera.get_config(self.context)
            widget = config.get_child_by_name(name)
            target = str(value)

            # Auto → 00ff tylko dla parametrów exposure
            if target == 'Auto' and name in self.EXPOSURE_PARAMS:
                target = next(
                    (c for c in widget.get_choices()
                     if '00ff' in c.lower() or 'bulb' in c.lower()),
                    'Auto'
                )

            print(f">>> SEND {name} = '{target}'")
            widget.set_value(target)
            self.camera.set_config(config, self.context)
            print(f"<<< OK {name} = '{target}'")
            return True

        except gp.GPhoto2Error as e:
            logger.warning(
                f"Nie udało się ustawić {name}={value}: "
                f"gphoto2 error {e.code}"
            )
            # Próba odzyskania live view po błędzie set_config
            try:
                time.sleep(0.3)
                recovery_file = gp.CameraFile()
                self.camera.capture_preview(recovery_file, self.context)
                logger.debug("Recovery capture_preview OK")
            except Exception:
                logger.warning("Recovery capture_preview failed")
            return False

        except Exception as e:
            logger.exception(f"Nieoczekiwany błąd ustawiania {name}={value}")
            return False

    # ─────────────────────────────────── USB RESET FALLBACK

    def _try_usb_reset(self):
        """
        Fallback: próbuje zresetować port USB po wymuszonym terminate().
        Wymaga pakietu usbutils (usbreset) lub sudo.
        """
        if not self._usb_bus_device:
            logger.warning("USB reset: brak informacji o porcie USB")
            return False

        try:
            # Format: "001,004" → bus=001, device=004
            parts = self._usb_bus_device.split(',')
            if len(parts) != 2:
                logger.warning(f"USB reset: nieprawidłowy format portu: {self._usb_bus_device}")
                return False

            bus, dev = parts[0], parts[1]
            usb_path = f"/dev/bus/usb/{bus}/{dev}"

            # Metoda 1: usbreset (z pakietu usbutils)
            # Wymaga: sudo apt install usbutils
            # oraz dodania użytkownika do grupy z dostępem do USB
            try:
                result = subprocess.run(
                    ['usbreset', usb_path],
                    capture_output=True,
                    timeout=5
                )
                if result.returncode == 0:
                    logger.info(f"USB reset OK: {usb_path}")
                    time.sleep(1.0)  # Czas na re-enumerację
                    return True
                else:
                    logger.warning(f"USB reset failed: {result.stderr.decode()}")
            except FileNotFoundError:
                logger.debug("usbreset nie znaleziony, próbuję alternatywnej metody")
            except subprocess.TimeoutExpired:
                logger.warning("USB reset timeout")

            # Metoda 2: Unbind/rebind przez sysfs (wymaga sudo lub odpowiednich uprawnień)
            # To jest bardziej agresywne ale nie wymaga dodatkowych narzędzi
            logger.info("USB reset: próba unbind/rebind przez sysfs")
            # Nie implementujemy tutaj — wymaga root lub skomplikowanej konfiguracji udev

            return False

        except Exception as e:
            logger.warning(f"USB reset error: {e}")
            return False

    # ─────────────────────────────────── STOP

    def stop(self):
        """
        Bezpieczne zatrzymanie wątku.
        Czeka dłużej jeśli capture jest w toku.
        """
        self.keep_running = False

        # Zawsze krótki timeout — nie czekamy na zakończenie capture.
        # Przy terminate USB zostaje zablokowany; recovery czeka 4s.
        if self._capturing:
            logger.warning("Stop requested during capture — forcing terminate")

        self.wait(self.STOP_TIMEOUT_MS)

        if self.isRunning():
            logger.warning(
                f"Wątek gphoto nie zakończył się w {self.STOP_TIMEOUT_MS}ms — terminate"
            )
            self.terminate()
            self.wait(1000)

            # USB needs time to recover after forced terminate
            logger.info("Czekam 4s na zwolnienie portu USB...")
            time.sleep(4.0)
            logger.info("USB recovery sleep done")
