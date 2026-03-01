"""
Telegram Sender — wysyłanie plików przez Telegram Bot API.
Używa wyłącznie biblioteki standardowej (urllib) — brak zewnętrznych zależności.
Obsługuje dwa tryby:
  - as_photos=True  → sendPhoto (kompresja Telegrama, maks. 10 MB)
  - as_photos=False → sendDocument (bezstratnie, maks. 50 MB)
"""
import os
import mimetypes
import urllib.request
import urllib.parse
import json
import uuid
import logging
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

# Limity Telegram Bot API
PHOTO_MAX_BYTES    = 10 * 1024 * 1024   # 10 MB — sendPhoto
DOCUMENT_MAX_BYTES = 50 * 1024 * 1024   # 50 MB — sendDocument


def _build_multipart(fields: dict, files: list) -> tuple[bytes, str]:
    """
    Buduje ciało multipart/form-data.
    fields: {name: value}
    files:  [(field_name, filename, data_bytes, content_type)]
    Zwraca (body_bytes, content_type_header).
    """
    boundary = uuid.uuid4().hex
    parts = []

    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f'{value}\r\n'
        )

    for field_name, filename, data, ctype in files:
        header = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f'Content-Type: {ctype}\r\n\r\n'
        )
        parts.append(header.encode() + data + b'\r\n')

    body = b''.join(
        p.encode() if isinstance(p, str) else p for p in parts
    ) + f'--{boundary}--\r\n'.encode()

    return body, f'multipart/form-data; boundary={boundary}'


def _api_url(token: str, method: str) -> str:
    return f'https://api.telegram.org/bot{token}/{method}'


class TelegramSender(QThread):
    """
    Wysyła listę plików do Telegrama przez Bot API.
    Sygnały:
      progress(index, total, filename)  — przed każdym plikiem
      file_done(index, filename, ok)    — po każdym pliku
      finished_all(sent, skipped, errors) — podsumowanie
      error(message)                    — błąd krytyczny (np. brak tokenu)
    """
    progress     = pyqtSignal(int, int, str)   # index, total, filename
    file_done    = pyqtSignal(int, str, bool)  # index, filename, ok
    finished_all = pyqtSignal(int, int, int)   # sent, skipped, errors
    error        = pyqtSignal(str)

    def __init__(self, token: str, chat_id: str,
                 file_paths: list[str], as_photos: bool = True,
                 parent=None):
        super().__init__(parent)
        self.token      = token
        self.chat_id    = chat_id
        self.file_paths = file_paths
        self.as_photos  = as_photos
        self._stop      = False

    def stop(self):
        self._stop = True

    def run(self):
        if not self.token or not self.chat_id:
            self.error.emit("Telegram bot token or chat ID is not configured.")
            return

        total   = len(self.file_paths)
        sent    = 0
        skipped = 0
        errors  = 0

        for idx, path in enumerate(self.file_paths):
            if self._stop:
                break

            filename = os.path.basename(path)
            self.progress.emit(idx + 1, total, filename)

            try:
                size = os.path.getsize(path)
                ok = False

                if self.as_photos:
                    if size > PHOTO_MAX_BYTES:
                        logger.warning(
                            f"Pomijam {filename}: {size/1024/1024:.1f} MB > 10 MB (limit sendPhoto)"
                        )
                        skipped += 1
                        self.file_done.emit(idx + 1, filename, False)
                        continue
                    ok = self._send_photo(path, filename)
                else:
                    if size > DOCUMENT_MAX_BYTES:
                        logger.warning(
                            f"Pomijam {filename}: {size/1024/1024:.1f} MB > 50 MB (limit sendDocument)"
                        )
                        skipped += 1
                        self.file_done.emit(idx + 1, filename, False)
                        continue
                    ok = self._send_document(path, filename)

                if ok:
                    sent += 1
                else:
                    errors += 1
                self.file_done.emit(idx + 1, filename, ok)

            except Exception as e:
                logger.exception(f"Błąd wysyłania {filename}: {e}")
                errors += 1
                self.file_done.emit(idx + 1, filename, False)

        self.finished_all.emit(sent, skipped, errors)

    # ──────────────────────── wysyłanie

    def _send_photo(self, path: str, filename: str) -> bool:
        """Wysyła plik jako zdjęcie (kompresja Telegrama)."""
        with open(path, 'rb') as f:
            data = f.read()
        ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        body, ct_header = _build_multipart(
            {'chat_id': self.chat_id},
            [('photo', filename, data, ctype)]
        )
        return self._post(_api_url(self.token, 'sendPhoto'), body, ct_header)

    def _send_document(self, path: str, filename: str) -> bool:
        """Wysyła plik jako dokument (bezstratnie)."""
        with open(path, 'rb') as f:
            data = f.read()
        ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        body, ct_header = _build_multipart(
            {'chat_id': self.chat_id},
            [('document', filename, data, ctype)]
        )
        return self._post(_api_url(self.token, 'sendDocument'), body, ct_header)

    def _post(self, url: str, body: bytes, content_type: str) -> bool:
        """Wysyła żądanie POST i zwraca True jeśli API odpowiedziało ok=true."""
        req = urllib.request.Request(
            url,
            data=body,
            headers={'Content-Type': content_type},
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
                if not result.get('ok'):
                    logger.warning(f"Telegram API error: {result}")
                return bool(result.get('ok'))
        except urllib.error.HTTPError as e:
            body_err = e.read().decode(errors='replace')
            logger.warning(f"HTTP {e.code}: {body_err}")
            return False
        except Exception as e:
            logger.warning(f"Request error: {e}")
            return False
