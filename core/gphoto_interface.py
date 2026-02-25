import os
os.environ['LANGUAGE'] = 'C'

import gphoto2 as gp
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from collections import deque
import time
import logging


def _setup_logger() -> logging.Logger:
    log = logging.getLogger("gphoto")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d  %(levelname)-5s  %(message)s",
        datefmt="%H:%M:%S"
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    log.addHandler(ch)
    fh = logging.FileHandler("log.txt", mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    return log


logger = _setup_logger()


class GPhotoInterface(QThread):
    frame_received = pyqtSignal(bytes, bool)
    settings_loaded = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    image_captured = pyqtSignal(str)
    capture_failed = pyqtSignal(str)

    # Kody bÅ‚Ä™dÃ³w gphoto2
    ERR_USB = -52
    ERR_TIMEOUT = -110
    ERR_NO_SPACE = -53
    ERR_IO = -7
    ERR_BUSY = -110
    ERR_GENERIC = -1

    # BÅ‚Ä™dy USB â€” dÅ‚uÅ¼sza pauza przed retry
    HEAVY_ERRORS = {ERR_USB, ERR_NO_SPACE}

    # BÅ‚Ä™dy lÅ¼ejsze â€” krÃ³tka pauza
    LIGHT_ERRORS = {ERR_TIMEOUT, ERR_BUSY, ERR_GENERIC, ERR_IO}

    MAX_CONSECUTIVE_ERRORS = 20
    MAX_CONSECUTIVE_HEAVY = 3   # Po 3× -52 z rzędu USB jest martwy — nie czekaj na 20

    def __init__(self):
        super().__init__()
        self.keep_running = False
        self.camera = None
        self.context = gp.Context()
        self.MAX_ISO = 1600
        self.MIN_SHUTTER_VAL = 0.25   # 1/4s
        self.MAX_SHUTTER_VAL = 0.001  # 1/1000s
        self.mutex = QMutex()
        self.command_queue = deque(maxlen=32)
        self._pending_error = None

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CAMERA DETECTION

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
        self.camera = gp.Camera()
        self.camera.set_abilities(
            abilities_list[abilities_list.lookup_model(model)]
        )
        self.camera.set_port_info(
            port_info_list[port_info_list.lookup_path(port)]
        )

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ VALUE PARSING

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

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ MAIN LOOP

    def run(self):
        try:
            self._autodetect_camera()

            # Retry init â€” port USB moÅ¼e byÄ‡ jeszcze zajÄ™ty po zabiciu gvfs
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
                        f"Init prÃ³ba {attempt + 1}/3: bÅ‚Ä…d {e.code}"
                    )
            else:
                raise Exception(
                    f"Nie udaÅ‚o siÄ™ zainicjalizowaÄ‡ aparatu "
                    f"po 3 prÃ³bach (ostatni bÅ‚Ä…d: {last_err})"
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
                    f"Config prÃ³ba {attempt + 1}/5 â€” brakuje: {missing}"
                )
                time.sleep(0.3)

            if initial_config:
                self.settings_loaded.emit(initial_config)
            
            if missing:
                logger.warning(
                    f"Nie udaÅ‚o siÄ™ pobraÄ‡: {missing} po 5 prÃ³bach"
                )

            self.keep_running = True
            consecutive_errors = 0

            while self.keep_running:
                fps_sleep = 0.05

                # --- PrzetwÃ³rz kolejkÄ™ komend ---
                self.mutex.lock()
                try:
                    while self.command_queue:
                        name, value = self.command_queue.popleft()
                        if name == '__CAPTURE__':
                            logger.info("[CAM ] BUSY  capture start")
                            self._execute_capture(value)
                            fps_sleep = 0.5
                        else:
                            logger.debug(f"[CMD ] --> {name} = '{value}'")
                            self._execute_update(name, value)
                            fps_sleep = 0.15
                finally:
                    self.mutex.unlock()

                # Capture mogło ustawić keep_running=False — wyjdź bez capture_preview
                if not self.keep_running:
                    break

                # --- Przechwycenie klatki live view ---
                try:
                    _t0 = time.monotonic()
                    camera_file = gp.CameraFile()
                    self.camera.capture_preview(camera_file, self.context)
                    file_data = camera_file.get_data_and_size()
                    _lv_ms = int((time.monotonic() - _t0) * 1000)
                    if _lv_ms > 300:
                        logger.warning(f"[LV  ] slow frame: {_lv_ms} ms")
                    else:
                        logger.debug(f"[LV  ] frame ok: {_lv_ms} ms  ({len(file_data)} B)")

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
                    logger.warning(f"[USB ] ERROR code={e.code} consecutive={consecutive_errors}/{self.MAX_CONSECUTIVE_ERRORS}")
                    logger.warning(
                        f"GPhoto2Error w pÄ™tli: code={e.code} "
                        f"(bÅ‚Ä…d {consecutive_errors}/{self.MAX_CONSECUTIVE_ERRORS})"
                    )

                    # CzyÅ›cimy kolejkÄ™ â€” stare komendy nie pomogÄ…
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

                    # Heavy error (USB -52): po MAX_CONSECUTIVE_HEAVY z rzędu wychodź natychmiast
                    # Nie czekaj na 20 iteracji × sleep — USB jest martwy, to strata czasu
                    heavy_limit = (self.MAX_CONSECUTIVE_HEAVY
                                   if e.code in self.HEAVY_ERRORS
                                   else self.MAX_CONSECUTIVE_ERRORS)
                    if consecutive_errors >= heavy_limit:
                        self._pending_error = (
                            f"Too many errors ({consecutive_errors}). "
                            f"Last: {e.code}. Stopping."
                        )
                        self.keep_running = False
                        break

                except Exception as e:
                    consecutive_errors += 1
                    logger.exception("Nieoczekiwany bÅ‚Ä…d w pÄ™tli live view")
                    if consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                        self._pending_error = f"Repeated error: {e}"
                        self.keep_running = False
                        break
                    fps_sleep = 0.5

                time.sleep(fps_sleep)

        except Exception as e:
            logger.exception("Camera init error")
            self._pending_error = str(e)

        finally:
            # Release USB FIRST, then notify UI.
            # Reversed order -> probe starts while camera.exit() still runs -> Err70.
            self._safe_camera_exit()
            if self._pending_error:
                self.error_occurred.emit(self._pending_error)

    def _safe_camera_exit(self):
        """Bezpieczne zamkniÄ™cie poÅ‚Ä…czenia z aparatem."""
        if self.camera:
            try:
                self.camera.exit(self.context)
                logger.info("Aparat bezpiecznie odÅ‚Ä…czony.")
            except Exception as e:
                logger.warning(f"BÅ‚Ä…d przy zamykaniu aparatu: {e}")
            finally:
                self.camera = None

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ CONFIG READ

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

                    # JeÅ›li brak opcji â€” pomijamy, by nie czyÅ›ciÄ‡ UI
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
                        f"Parametr {name} niedostÄ™pny: {e.code}"
                    )
                    continue
                except Exception as e:
                    logger.warning(
                        f"BÅ‚Ä…d odczytu parametru {name}: {e}"
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
                    logger.warning(f"Image param {name} niedostÄ™pny: {e}")

            return results

        except gp.GPhoto2Error as e:
            logger.error(f"Nie moÅ¼na pobraÄ‡ konfiguracji: {e.code}")
            return {}
        except Exception as e:
            logger.exception("Nieoczekiwany bÅ‚Ä…d konfiguracji")
            return {}

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ PARAM UPDATE (API)

    def update_camera_param(self, name, value):
        """
        Dodaje komendÄ™ do kolejki (thread-safe).
        WywoÅ‚ywane z wÄ…tku UI.
        """
        print(f"Queued: {name} = '{value}'")
        self.mutex.lock()
        try:
            self.command_queue.append((name, value))
        finally:
            self.mutex.unlock()

    def capture_photo(self, save_dir):
        """
        Kolejkuje zdjÄ™cie do wykonania (thread-safe).
        WywoÅ‚ywane z wÄ…tku UI.
        """
        print(f"Queued: __CAPTURE__ â†’ {save_dir}")
        self.mutex.lock()
        try:
            self.command_queue.append(('__CAPTURE__', save_dir))
        finally:
            self.mutex.unlock()

    # Parametry exposure â€” tylko te majÄ… 00ff Auto
    EXPOSURE_PARAMS = {'shutterspeed', 'aperture', 'iso', 'exposurecompensation'}

    def _execute_capture(self, save_dir):
        """
        Wykonuje zdjÄ™cie i pobiera plik z aparatu.
        WywoÅ‚ywane WEWNÄ„TRZ pÄ™tli roboczej.
        """
        import os
        from datetime import datetime

        try:
            _t_start = time.monotonic()
            logger.info("[CAM ] BUSY  camera.capture() START")
            file_path = self.camera.capture(
                gp.GP_CAPTURE_IMAGE, self.context
            )
            _t_cap = time.monotonic()
            logger.info(f"[CAM ] FREE  capture() done {int((_t_cap-_t_start)*1000)} ms  -> {file_path.folder}/{file_path.name}")

            # Pobierz plik z aparatu
            logger.debug("[CAM ] BUSY  file_get() START")
            camera_file = gp.CameraFile()
            self.camera.file_get(
                file_path.folder, file_path.name,
                gp.GP_FILE_TYPE_NORMAL, camera_file, self.context
            )
            _t_get = time.monotonic()
            logger.info(f"[CAM ] FREE  file_get() done {int((_t_get-_t_cap)*1000)} ms")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{file_path.name}"
            local_path = os.path.join(save_dir, filename)

            os.makedirs(save_dir, exist_ok=True)
            camera_file.save(local_path)
            _t_save = time.monotonic()
            logger.info(f"[CAM ] SAVED {local_path}  ({int((_t_save-_t_get)*1000)} ms disk)")

            self.image_captured.emit(local_path)

            # Po capture aparat wychodzi z LV - restart preview
            logger.debug("[CAM ] BUSY  LV recovery (sleep 0.3s)")
            time.sleep(0.3)
            try:
                recovery = gp.CameraFile()
                _t_rec = time.monotonic()
                self.camera.capture_preview(recovery, self.context)
                logger.info(f"[CAM ] FREE  LV recovered {int((time.monotonic()-_t_rec)*1000)} ms  total={int((time.monotonic()-_t_start)*1000)} ms")
            except Exception:
                logger.warning("[CAM ] WARN  LV recovery failed - next frame will retry")

            return True

        except gp.GPhoto2Error as e:
            logger.warning(f"Capture failed: gphoto2 error {e.code}")
            if e.code in self.HEAVY_ERRORS:
                # Heavy USB error po capture → sesja niezdatna, wychodź natychmiast
                # zamiast czekać na 20 iteracji pętli (każda ze sleepem)
                logger.warning("Capture: heavy USB error — kończę sesję")
                self.keep_running = False
                self._pending_error = f"Capture failed (USB error {e.code}). Reconnect required."
            else:
                self.capture_failed.emit(f"Capture failed: error {e.code}")
            return False

        except Exception as e:
            logger.exception(f"Unexpected capture error: {e}")
            self.capture_failed.emit(f"Capture error: {e}")
            return False

    def _execute_update(self, name, value) -> bool:
        """
        WysyÅ‚a parametr do aparatu. Zwraca True przy sukcesie.
        WywoÅ‚ywane WEWNÄ„TRZ pÄ™tli roboczej (mutex juÅ¼ zablokowany).
        Przy bÅ‚Ä™dzie NIE zatrzymuje live view â€” prÃ³buje odzyskaÄ‡ sesjÄ™.
        """
        try:
            config = self.camera.get_config(self.context)
            widget = config.get_child_by_name(name)
            target = str(value)

            # Auto â†’ 00ff tylko dla parametrÃ³w exposure
            if target == 'Auto' and name in self.EXPOSURE_PARAMS:
                target = next(
                    (c for c in widget.get_choices()
                     if '00ff' in c.lower() or 'bulb' in c.lower()),
                    'Auto'
                )

            _t0 = time.monotonic()
            logger.debug(f"[CMD ] BUSY  set_config {name} = '{target}'")
            widget.set_value(target)
            self.camera.set_config(config, self.context)
            logger.info(f"[CMD ] FREE  set_config {name} = '{target}'  {int((time.monotonic()-_t0)*1000)} ms")
            return True

        except gp.GPhoto2Error as e:
            logger.warning(
                f"Nie udaÅ‚o siÄ™ ustawiÄ‡ {name}={value}: "
                f"gphoto2 error {e.code}"
            )
            # PrÃ³ba odzyskania live view po bÅ‚Ä™dzie set_config
            try:
                time.sleep(0.3)
                recovery_file = gp.CameraFile()
                self.camera.capture_preview(recovery_file, self.context)
                logger.debug("Recovery capture_preview OK")
            except Exception:
                logger.warning("Recovery capture_preview failed")
            return False

        except Exception as e:
            logger.exception(f"Nieoczekiwany bÅ‚Ä…d ustawiania {name}={value}")
            return False

    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ STOP

    def stop(self):
        """Bezpieczne zatrzymanie wÄ…tku."""
        self.keep_running = False
        self.wait(3000)  # timeout 3s zamiast wiecznego czekania
        if self.isRunning():
            logger.warning("WÄ…tek gphoto nie zakoÅ„czyÅ‚ siÄ™ w 3s â€” terminate")
            self.terminate()
            self.wait(1000)
