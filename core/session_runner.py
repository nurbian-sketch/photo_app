"""
SessionRunner — silnik sesji fotograficznej.
QThread z deterministyczną maszyną stanów.
Brak zależności od GUI — komunikacja wyłącznie przez sygnały PyQt6.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from typing import Optional

import gphoto2 as gp
from PyQt6.QtCore import QThread, pyqtSignal

from core.session_context import (
    CameraSettings,
    EndReason,
    SessionContext,
    SessionMode,
    SessionState,
    SessionSummary,
)
from core.session_store import SessionStore

logger = logging.getLogger(__name__)

# Opóźnienie countdown przed startem — obsługuje dialog w SessionView, tu =0
COUNTDOWN_SEC = 0

# Timeout importu pojedynczego pliku (sekundy)
IMPORT_FILE_TIMEOUT = 60

# Minimalna różnica rozmiaru pliku traktowana jako błąd transferu (bajty)
SIZE_TOLERANCE = 0


class SessionRunner(QThread):
    """
    Silnik sesji fotograficznej.
    Przechodzi przez stany: COUNTDOWN → ACTIVE → IMPORTING → SYNCING → FINISHED/INTERRUPTED.
    Emituje sygnały do SessionView.
    """

    # ─────────────────────────── SYGNAŁY

    # Zmiana stanu maszyny
    state_changed = pyqtSignal(object)          # SessionState

    # Tick timera: (pozostałe_sekundy, całkowite_sekundy)
    timer_tick = pyqtSignal(int, int)

    # Countdown przed startem: pozostałe sekundy
    countdown_tick = pyqtSignal(int)

    # Postęp importu: (skopiowane, total, nazwa_pliku)
    import_progress = pyqtSignal(int, int, str)

    # Postęp rclone: linia stdout
    sync_progress = pyqtSignal(str)

    # Sesja zakończona
    session_finished = pyqtSignal(object)       # SessionSummary

    # Błąd niekrytyczny (logowany, sesja kontynuuje)
    warning = pyqtSignal(str)

    # Błąd krytyczny (sesja przerwana)
    error = pyqtSignal(str)

    # ─────────────────────────── INIT

    def __init__(
        self,
        context: SessionContext,
        store: SessionStore,
        rclone_remote: str = "",
        rclone_dest: str = "",
        parent=None,
    ):
        """
        Args:
            context:       gotowy SessionContext z make_session_context()
            store:         SessionStore do zapisu metadanych
            rclone_remote: nazwa remote rclone (np. "gdrive")
            rclone_dest:   ścieżka docelowa na remote (np. "Sessions")
        """
        super().__init__(parent)
        self.context       = context
        self.store         = store
        self.rclone_remote = rclone_remote
        self.rclone_dest   = rclone_dest

        self._state        = SessionState.IDLE
        self._stop_flag    = False
        self._end_reason: Optional[EndReason] = None
        self._errors:   list[str] = []
        self._warnings: list[str] = []

    # ─────────────────────────── API PUBLICZNE

    def request_stop(self, reason: EndReason = EndReason.MANUAL):
        """Zleca zatrzymanie sesji z zewnątrz (z wątku UI)."""
        logger.info(f"SessionRunner: request_stop({reason})")
        self._end_reason = reason
        self._stop_flag  = True

    @property
    def state(self) -> SessionState:
        return self._state

    # ─────────────────────────── MASZYNA STANÓW

    def run(self):
        """Główna pętla wątku — sekwencja stanów."""
        try:
            self._run_countdown()
            if not self._stop_flag:
                self._run_active()
            self._run_stopping()

            if self.context.mode != SessionMode.PRIVATE:
                self._run_import()
                self._run_sync()

            self._finish()

        except Exception as e:
            logger.exception("SessionRunner: nieoczekiwany błąd")
            self._errors.append(str(e))
            self._set_state(SessionState.FAILED)
            self.error.emit(str(e))
            self._finish(force_failed=True)

    # ─────────────────────────── COUNTDOWN

    def _run_countdown(self):
        """Odlicza COUNTDOWN_SEC sekund — czas na odłączenie USB przez użytkownika."""
        self._set_state(SessionState.COUNTDOWN)
        for remaining in range(COUNTDOWN_SEC, 0, -1):
            if self._stop_flag:
                return
            self.countdown_tick.emit(remaining)
            time.sleep(1)

    # ─────────────────────────── AKTYWNA SESJA

    def _run_active(self):
        """
        Główna pętla sesji: tylko tick timera.
        Brak komunikacji z aparatem — kamera używa modułu bezprzewodowego.
        """
        self._set_state(SessionState.ACTIVE)
        self.context.started_at = datetime.now()

        total_sec = self.context.duration_sec

        while not self._stop_flag:
            elapsed   = int((datetime.now() - self.context.started_at).total_seconds())
            remaining = max(0, total_sec - elapsed)

            self.timer_tick.emit(remaining, total_sec)

            if remaining == 0:
                self._end_reason = EndReason.TIMEOUT
                self._stop_flag  = True
                break

            time.sleep(1)

    # ─────────────────────────── STOPPING

    def _run_stopping(self):
        """Rejestruje czas zakończenia i ustawia stan końcowy."""
        self.context.ended_at   = datetime.now()
        self.context.end_reason = self._end_reason

        if self._end_reason == EndReason.TIMEOUT:
            self._set_state(SessionState.FINISHED)
        else:
            self._set_state(SessionState.INTERRUPTED)

        logger.info(
            f"SessionRunner: sesja zakończona — "
            f"reason={self._end_reason}, "
            f"elapsed={self.context.elapsed_sec}s"
        )

    # ─────────────────────────── IMPORT

    def _run_import(self):
        """
        Pobiera zdjęcia z karty SD aparatu.
        Tylko pliki nowsze niż session_start (z korektą offsetu zegarów).
        """
        self._set_state(SessionState.IMPORTING)

        # Połącz z aparatem
        camera, gp_context = self._connect_camera()
        print(f"[IMPORT] connect: {'OK' if camera else 'FAIL'}", flush=True)
        if camera is None:
            msg = "Import: nie można połączyć z aparatem"
            logger.warning(msg)
            self._warnings.append(msg)
            return

        try:
            # Odczytaj offset zegarów
            self.context.camera_time_offset = self._get_time_offset(camera, gp_context)
            print(f"[IMPORT] offset={self.context.camera_time_offset}s  started_at={self.context.started_at}", flush=True)
            logger.info(f"Offset zegarów aparat↔system: {self.context.camera_time_offset}s")

            # Snapshot karty — pliki nowsze niż start sesji
            files_to_import = self._list_new_files(camera, gp_context)
            print(f"[IMPORT] znaleziono {len(files_to_import)} plików do importu", flush=True)
            logger.info(f"Import: znaleziono {len(files_to_import)} nowych plików")

            if not files_to_import:
                self._warnings.append("Import: brak nowych plików na karcie")
                return

            # Utwórz katalog sesji (zdjęcia trafiają bezpośrednio tu)
            os.makedirs(self.context.session_path, exist_ok=True)

            # Reset flagi — import musi działać niezależnie od powodu zakończenia sesji
            self._stop_flag = False

            # Transfer
            total = len(files_to_import)
            for idx, (folder, filename) in enumerate(files_to_import, 1):
                if self._stop_flag:
                    break

                self.import_progress.emit(idx, total, filename)
                success = self._download_file(camera, gp_context, folder, filename)

                if success:
                    self.context.imported_files.append(filename)
                else:
                    self._warnings.append(f"Import: błąd transferu {filename}")

        finally:
            try:
                camera.exit(gp_context)
            except Exception:
                pass

        # Zapis metadanych po imporcie
        self.store.save(self.context)
        logger.info(
            f"Import zakończony: {len(self.context.imported_files)}/{len(files_to_import)} plików"
        )

    # Maksymalna liczba prób połączenia podczas importu (15 × 2s = 30s)
    _CONNECT_MAX_ATTEMPTS = 15

    def _connect_camera(self) -> tuple[Optional[object], Optional[object]]:
        """Łączy z aparatem przez USB. Zwraca (camera, context) lub (None, None).
        Przy sesji interrupted daje użytkownikowi 30 sekund na podłączenie aparatu."""
        for attempt in range(self._CONNECT_MAX_ATTEMPTS):
            try:
                gp_context = gp.Context()
                port_info_list = gp.PortInfoList()
                port_info_list.load()
                abilities_list = gp.CameraAbilitiesList()
                abilities_list.load(gp_context)
                cameras = abilities_list.detect(port_info_list, gp_context)

                if not cameras:
                    if attempt == 0:
                        self.warning.emit("Connect camera via USB to import photos...")
                    logger.warning(f"Import connect: brak aparatu (próba {attempt+1}/{self._CONNECT_MAX_ATTEMPTS})")
                    time.sleep(2)
                    continue

                model, port = cameras[0]
                camera = gp.Camera()
                camera.set_abilities(abilities_list[abilities_list.lookup_model(model)])
                camera.set_port_info(port_info_list[port_info_list.lookup_path(port)])
                camera.init(gp_context)
                logger.info(f"Import: połączono z {model}")
                return camera, gp_context

            except gp.GPhoto2Error as e:
                if attempt == 0:
                    self.warning.emit("Connect camera via USB to import photos...")
                logger.warning(f"Import connect error {e.code} (próba {attempt+1}/{self._CONNECT_MAX_ATTEMPTS})")
                time.sleep(2)

        return None, None

    def _get_time_offset(self, camera, gp_context) -> int:
        """
        Odczytuje czas z aparatu i oblicza offset względem czasu systemowego.
        Zwraca różnicę w sekundach (camera_time - system_time).
        """
        try:
            config  = camera.get_config(gp_context)
            widget  = config.get_child_by_name("datetime")
            cam_ts  = int(widget.get_value())
            sys_ts  = int(datetime.now().timestamp())
            offset  = cam_ts - sys_ts
            logger.info(f"Czas aparatu: {cam_ts}, systemu: {sys_ts}, offset: {offset}s")
            return offset
        except Exception as e:
            logger.warning(f"Nie można odczytać czasu aparatu: {e}")
            return 0

    def _list_new_files(
        self, camera, gp_context
    ) -> list[tuple[str, str]]:
        """
        Listuje pliki na karcie SD nowsze niż czas startu sesji.
        Uwzględnia offset zegarów.
        Zwraca listę (folder, filename).
        """
        # Przelicz próg: czas startu sesji w czasie aparatu
        session_start_ts = int(self.context.started_at.timestamp())
        threshold_ts     = session_start_ts + self.context.camera_time_offset
        # Bufor 30s — na wypadek drobnych rozbieżności
        threshold_ts    -= 30
        print(f"[LIST] session_start_ts={session_start_ts}  threshold_ts={threshold_ts}", flush=True)

        result = []

        try:
            dcim_folders = camera.folder_list_folders("/store_00020001/DCIM", gp_context)

            for i in range(dcim_folders.count()):
                folder_name = dcim_folders.get_name(i)
                folder_path = f"/store_00020001/DCIM/{folder_name}"

                files = camera.folder_list_files(folder_path, gp_context)
                for j in range(files.count()):
                    filename = files.get_name(j)

                    # Pobierz info o pliku (mtime)
                    try:
                        info = camera.file_get_info(folder_path, filename, gp_context)
                        mtime = info.file.mtime
                        inc = mtime == 0 or mtime >= threshold_ts
                        print(f"[LIST]  {filename}: mtime={mtime}  include={inc}", flush=True)
                        # mtime=0 → gphoto2 nie odczytał czasu (Canon EOS RP) → dołącz plik
                        if inc:
                            result.append((folder_path, filename))
                    except Exception as e:
                        logger.debug(f"file_get_info błąd {filename}: {e}")
                        # Jeśli nie można sprawdzić czasu — dołącz z ostrzeżeniem
                        result.append((folder_path, filename))
                        self._warnings.append(
                            f"Nie można sprawdzić czasu pliku {filename} — dołączono"
                        )

        except gp.GPhoto2Error as e:
            logger.error(f"Błąd listowania karty: {e.code}")
            self._errors.append(f"Błąd listowania karty: {e.code}")

        return result

    def _download_file(
        self, camera, gp_context, folder: str, filename: str
    ) -> bool:
        """
        Pobiera jeden plik z karty do katalogu captures.
        Weryfikuje rozmiar po transferze.
        Zwraca True przy sukcesie.
        """
        local_path = os.path.join(self.context.captures_path, filename)
        print(f"[DL] {filename}  folder={folder}  local={local_path}", flush=True)

        try:
            # Pobierz info — rozmiar referencyjny
            info = camera.file_get_info(folder, filename, gp_context)
            expected_size = info.file.size
            print(f"[DL] info OK, size={expected_size}", flush=True)

            # Transfer
            camera_file = camera.file_get(
                folder, filename, gp.GP_FILE_TYPE_NORMAL, gp_context
            )
            camera_file.save(local_path)

            # Weryfikacja rozmiaru
            actual_size = os.path.getsize(local_path)
            if abs(actual_size - expected_size) > SIZE_TOLERANCE:
                logger.warning(
                    f"Rozmiar pliku {filename}: "
                    f"oczekiwano {expected_size}B, pobrano {actual_size}B"
                )
                self._warnings.append(f"Niezgodność rozmiaru: {filename}")

            print(f"[DL] OK: {filename} ({actual_size}B)", flush=True)
            logger.debug(f"OK: {filename} ({actual_size}B)")
            return True

        except gp.GPhoto2Error as e:
            print(f"[DL] GPhoto2Error {filename}: code={e.code} {e}", flush=True)
            logger.error(f"Błąd pobierania {filename}: {e.code}")
            # Usuń niekompletny plik
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError:
                    pass
            return False

        except Exception as e:
            print(f"[DL] Exception {filename}: {type(e).__name__}: {e}", flush=True)
            logger.exception(f"Nieoczekiwany błąd pobierania {filename}")
            return False

    # ─────────────────────────── SYNC (rclone)

    def _run_sync(self):
        """
        Uruchamia rclone sync po zakończeniu importu.
        Pomija HOME i PRIVATE.
        Nie blokuje kolejnej sesji — uruchamia subprocess i śledzi stdout.
        """
        if self.context.mode != SessionMode.CLIENT:
            self.context.sync_status = "skipped"
            self.store.save(self.context)
            return

        if not self.rclone_remote or not self.rclone_dest:
            logger.warning("SessionRunner: rclone nie skonfigurowany — pomijam sync")
            self.context.sync_status = "skipped"
            self.store.save(self.context)
            return

        self._set_state(SessionState.SYNCING)
        self.context.sync_status = "pending"

        source = self.store.base_dir
        dest   = f"{self.rclone_remote}:{self.rclone_dest}"

        cmd = [
            "rclone", "sync", source, dest,
            "--exclude", "*_home/**",
            "--exclude", "*_private/**",
            "--progress",
            "--stats", "1s",
        ]

        logger.info(f"rclone sync: {source} → {dest}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            for line in proc.stdout:
                line = line.strip()
                if line:
                    self.sync_progress.emit(line)
                    logger.debug(f"rclone: {line}")

            proc.wait()

            if proc.returncode == 0:
                self.context.sync_status = "done"
                logger.info("rclone sync: zakończony sukcesem")
            else:
                self.context.sync_status = "failed"
                msg = f"rclone zakończył się kodem {proc.returncode}"
                logger.warning(msg)
                self._warnings.append(msg)

        except FileNotFoundError:
            self.context.sync_status = "failed"
            msg = "rclone nie jest zainstalowany lub niedostępny w PATH"
            logger.error(msg)
            self._warnings.append(msg)

        except Exception as e:
            self.context.sync_status = "failed"
            logger.exception("Nieoczekiwany błąd rclone")
            self._warnings.append(str(e))

        self.store.save(self.context)

    # ─────────────────────────── FINISH

    def _finish(self, force_failed: bool = False):
        """Zapisuje metadane i emituje session_finished."""
        if not force_failed:
            final_state = (
                SessionState.FINISHED
                if self._end_reason == EndReason.TIMEOUT
                else SessionState.INTERRUPTED
            )
            self._set_state(final_state)

        self.store.save(self.context)

        # Odczytaj liczbę zdjęć
        shot_count = len(self.context.imported_files)
        if self.context.mode == SessionMode.PRIVATE:
            shot_count = 0  # nieznana bez USB

        summary = SessionSummary(
            context=self.context,
            shot_count=shot_count,
            end_reason=self._end_reason or EndReason.ERROR,
            errors=list(self._errors),
            warnings=list(self._warnings),
        )

        self.session_finished.emit(summary)
        logger.info(
            f"SessionRunner: DONE — "
            f"{shot_count} zdjęć, "
            f"errors={len(self._errors)}, "
            f"warnings={len(self._warnings)}"
        )

    # ─────────────────────────── POMOCNICZE

    def _set_state(self, state: SessionState):
        """Aktualizuje stan i emituje sygnał."""
        logger.info(f"SessionRunner: {self._state.name} → {state.name}")
        self._state = state
        self.state_changed.emit(state)
