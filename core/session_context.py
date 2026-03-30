"""
Kontekst sesji fotograficznej.
Dataclassy, enumeracje i struktury danych — bez logiki biznesowej.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional


# ─────────────────────────────────────────── ENUMERACJE

class SessionMode(Enum):
    """Tryb sesji — określa politykę importu i synchronizacji."""
    CLIENT  = "client"   # email klienta → import + rclone
    HOME    = "home"     # lokalnie → import, bez rclone
    PRIVATE = "private"  # tylko karta SD → bez importu


class SessionState(Enum):
    """Stany maszyny stanów SessionRunner."""
    IDLE         = auto()  # oczekiwanie na start
    COUNTDOWN    = auto()  # odliczanie przed sesją (USB disconnect)
    ACTIVE       = auto()  # sesja trwa
    STOPPING     = auto()  # kill switch (USB / manual / timeout)
    IMPORTING    = auto()  # transfer plików z karty
    SYNCING      = auto()  # rclone (tło)
    FINISHED     = auto()  # zakończona normalnie (timeout)
    INTERRUPTED  = auto()  # przerwana (manual / USB detected)
    FAILED       = auto()  # błąd krytyczny


class EndReason(Enum):
    """Przyczyna zakończenia sesji."""
    TIMEOUT      = "timeout"       # upłynął zadany czas
    MANUAL       = "manual"        # użytkownik nacisnął STOP
    USB_DETECTED = "usb_detected"  # aparat podłączony przez USB
    ERROR        = "error"         # błąd krytyczny


# ─────────────────────────────────────────── USTAWIENIA APARATU

@dataclass
class CameraSettings:
    """
    Snapshot ustawień aparatu z chwili przed startem sesji.
    Odczytywane z GPhotoInterface gdy USB jeszcze podłączone.
    """
    model:            str = ""
    lensname:         str = ""
    mode:             str = ""
    shutterspeed:     str = ""
    aperture:         str = ""
    iso:              str = ""
    whitebalance:     str = ""
    colortemperature: str = ""
    picturestyle:     str = ""
    imageformat:      str = ""

    def to_dict(self) -> dict:
        return {
            "model":            self.model,
            "lensname":         self.lensname,
            "mode":             self.mode,
            "shutterspeed":     self.shutterspeed,
            "aperture":         self.aperture,
            "iso":              self.iso,
            "whitebalance":     self.whitebalance,
            "colortemperature": self.colortemperature,
            "picturestyle":     self.picturestyle,
            "imageformat":      self.imageformat,
        }

    @staticmethod
    def from_dict(d: dict) -> "CameraSettings":
        return CameraSettings(
            model=d.get("model", ""),
            lensname=d.get("lensname", ""),
            mode=d.get("mode", ""),
            shutterspeed=d.get("shutterspeed", ""),
            aperture=d.get("aperture", ""),
            iso=d.get("iso", ""),
            whitebalance=d.get("whitebalance", ""),
            colortemperature=d.get("colortemperature", ""),
            picturestyle=d.get("picturestyle", ""),
            imageformat=d.get("imageformat", ""),
        )


# ─────────────────────────────────────────── KONTEKST SESJI

@dataclass
class SessionContext:
    """
    Żywy stan sesji — tworzony przy starcie, aktualizowany przez Runner.
    Serializowany do session.json po zakończeniu.
    """
    # Identyfikacja
    session_id:    str          # np. "2026-02-27_1430_jan@gmail.com"
    mode:          SessionMode
    email:         str          # adres klienta, "home" lub ""

    # Czas
    duration_min:  int          # zadany czas sesji w minutach
    started_at:    datetime     = field(default_factory=datetime.now)
    ended_at:      Optional[datetime] = None

    # Ścieżki (puste dla PRIVATE)
    session_path:  str          = ""  # ~/Obrazy/sessions/SESSION_ID/
    captures_path: str          = ""  # session_path/captures/

    # Ustawienia aparatu (snapshot przed startem)
    camera_settings: CameraSettings = field(default_factory=CameraSettings)

    # Pliki
    imported_files: list[str]   = field(default_factory=list)

    # Stan końcowy
    end_reason:    Optional[EndReason] = None
    sync_status:   str          = "pending"  # pending | done | failed | skipped
    share_code:    str          = ""          # 6-znakowy kod udostępniania (pusty = brak)

    # Przesunięcie zegara aparat↔system (sekundy) — ustalane przy imporcie
    camera_time_offset: int     = 0

    # Nadpisanie czasu trwania w sekundach (0 = użyj duration_min * 60); tylko do testów
    duration_sec_override: int  = 0

    @property
    def folder_name(self) -> str:
        """Nazwa folderu sesji — data_godzina_email."""
        return self.session_id

    @property
    def duration_sec(self) -> int:
        return self.duration_sec_override if self.duration_sec_override else self.duration_min * 60

    @property
    def elapsed_sec(self) -> int:
        """Ile sekund upłynęło od startu."""
        ref = self.ended_at or datetime.now()
        return int((ref - self.started_at).total_seconds())

    @property
    def remaining_sec(self) -> int:
        """Ile sekund pozostało (0 gdy przekroczono)."""
        return max(0, self.duration_sec - self.elapsed_sec)

    def to_dict(self) -> dict:
        def _fmt(dt):
            return dt.strftime("%Y-%m-%d %H:%M") if dt else None
        return {
            "session_id":           self.session_id,
            "session_path":         self.session_path,
            "share_code":           self.share_code,
            "mode":                 self.mode.value,
            "email":                self.email,
            "duration_min":         self.duration_min,
            "started_at":           _fmt(self.started_at),
            "ended_at":             _fmt(self.ended_at),
            "camera_settings":      self.camera_settings.to_dict(),
            "imported_files":       self.imported_files,
            # Wypełniane przez developer_worker po developmencie
            "develop_style":        None,
            "developed_files":      None,
            "develop_errors":       None,
            "develop_time_sec":     None,
            "develop_sec_per_photo": None,
            # Wypełniane przez rclone_sync_worker po synchronizacji
            "sync_status":          self.sync_status,
            "synced_at":            None,
            "camera_time_offset":   self.camera_time_offset,
        }

    @staticmethod
    def from_dict(d: dict) -> "SessionContext":
        def _parse_dt(s: str | None):
            if not s:
                return None
            # Obsługa starego formatu ISO i nowego "%Y-%m-%d %H:%M"
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    pass
            return datetime.fromisoformat(s)

        ctx = SessionContext(
            session_id=d["session_id"],
            mode=SessionMode(d["mode"]),
            email=d.get("email", ""),
            duration_min=d.get("duration_min", 0),
        )
        ctx.started_at         = _parse_dt(d.get("started_at")) or datetime.now()
        ctx.ended_at           = _parse_dt(d.get("ended_at"))
        ctx.session_path       = d.get("session_path", "")
        ctx.camera_settings    = CameraSettings.from_dict(d.get("camera_settings", {}))
        ctx.imported_files     = d.get("imported_files", [])
        ctx.end_reason         = EndReason(d["end_reason"]) if d.get("end_reason") else None
        ctx.sync_status        = d.get("sync_status", "pending")
        ctx.share_code         = d.get("share_code", "")
        ctx.camera_time_offset = d.get("camera_time_offset", 0)
        return ctx


# ─────────────────────────────────────────── PODSUMOWANIE

@dataclass
class SessionSummary:
    """
    Wynik sesji przekazywany do GUI po zakończeniu.
    Emitowany jako sygnał przez SessionRunner.
    """
    context:       SessionContext
    shot_count:    int
    end_reason:    EndReason
    errors:        list[str]       = field(default_factory=list)
    warnings:      list[str]       = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.end_reason in (EndReason.TIMEOUT, EndReason.MANUAL)

    @property
    def duration_str(self) -> str:
        """Czas trwania w formacie MM:SS."""
        sec = self.context.elapsed_sec
        return f"{sec // 60:02d}:{sec % 60:02d}"


# ─────────────────────────────────────────── FACTORY

def make_session_context(
    email: str,
    duration_min: int,
    session_base_dir: str,
    captures_subdir: str = "captures",   # zachowane dla zgodności — nieużywane
    camera_settings: Optional[CameraSettings] = None,
) -> SessionContext:
    """
    Fabryka SessionContext — tworzy kontekst przed startem sesji.
    Ścieżki i session_id są puste — ustawiane przez SessionRunner.finalize().
    Nie tworzy folderów na dysku.
    """
    # Wykryj tryb
    email_clean = email.strip().lower()
    if email_clean == "home":
        mode = SessionMode.HOME
    elif not email_clean:
        mode = SessionMode.PRIVATE
    else:
        mode = SessionMode.CLIENT

    return SessionContext(
        session_id="",
        mode=mode,
        email=email_clean,
        duration_min=duration_min,
        session_path="",
        captures_path="",
        camera_settings=camera_settings or CameraSettings(),
    )
