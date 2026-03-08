"""
core/share_bot.py

Bot Telegram do odbierania zdjęć z sesji przez kod udostępniania.
Uruchamiany jako osobny proces: python3 core/share_bot.py
Używa wyłącznie biblioteki standardowej (urllib) — brak zewnętrznych zależności.

Flow:
  /start ABC123  — deep link z QR kodu
  /code ABC123   — wpisanie ręcznie
"""
import os
import sys
import json
import time
import logging
import urllib.request
import urllib.parse
import mimetypes
import uuid
from datetime import datetime

# Dodaj katalog projektu do ścieżki
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core.session_codes as session_codes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [share_bot] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────── Konfiguracja

TOKEN    = os.environ.get("SHARE_BOT_TOKEN", "")
EXPIRY   = int(os.environ.get("SHARE_BOT_EXPIRY_DAYS", "14"))
POLL_INT = 2   # sekundy między getUpdates

# Zbiór kodów dla których już wysłano zdjęcia w tej sesji bota
# (czyszczone przy restarcie — wystarczy, bot sprawdza historię Telegrama)
_sent_this_session: set[str] = set()

# ─────────────────────────── Tłumaczenia

_TEXTS = {
    "pl": {
        "greeting": (
            "Cześć! 👋 Tu bot Pryzmat Studio — tu odbierzesz zdjęcia z sesji.\n"
            "Zaraz wyślę Twoje materiały. Chwilkę…"
        ),
        "privacy": (
            "🔒 Kilka słów o prywatności:\n"
            "Twoje zdjęcia przechowywane są wyłącznie na zaszyfrowanym serwerze studia "
            "i nie są udostępniane osobom trzecim. Bot nie zachowuje żadnych kopii — "
            "pliki są wysyłane bezpośrednio z serwera do Ciebie.\n"
            "Materiały będą dostępne przez {expiry} dni od daty sesji, po czym zostaną "
            "trwale i bezpowrotnie usunięte.\n"
            "W razie pytań lub wątpliwości — studio jest do Twojej dyspozycji. "
            "Nie zostaniesz sam z problemem."
        ),
        "done": "Gotowe! Zapraszamy ponownie do Pryzmat Studio 🙂",
        "not_found": (
            "Nie znalazłem zdjęć dla tego kodu. Możliwe że minęło {expiry} dni "
            "i materiały zostały usunięte zgodnie z polityką prywatności, "
            "lub kod jest nieprawidłowy.\n"
            "Skontaktuj się ze studiem — na pewno znajdziemy rozwiązanie."
        ),
        "already_sent": (
            "Twoje zdjęcia zostały już wysłane wcześniej — przewiń historię tego czatu, "
            "powinny tam być.\n"
            "Jeśli czegoś brakuje, napisz do studia. Nie zostaniesz sam z problemem. 🙂"
        ),
        "no_files": (
            "Znalazłem folder sesji, ale nie ma w nim zdjęć do wysłania. "
            "Skontaktuj się ze studiem."
        ),
        "use_code": "Podaj kod sesji komendą:\n/code TWÓJ_KOD",
    },
    "ru": {
        "greeting": (
            "Привет! 👋 Это бот Pryzmat Studio — здесь ты получишь фотографии с сессии.\n"
            "Сейчас отправлю твои материалы. Минутку…"
        ),
        "privacy": (
            "🔒 Несколько слов о конфиденциальности:\n"
            "Твои фотографии хранятся исключительно на зашифрованном сервере студии "
            "и не передаются третьим лицам. Бот не сохраняет никаких копий — "
            "файлы отправляются напрямую с сервера тебе.\n"
            "Материалы будут доступны в течение {expiry} дней с даты сессии, "
            "после чего будут безвозвратно удалены.\n"
            "Если есть вопросы — студия всегда на связи. Ты не останешься один с проблемой."
        ),
        "done": "Готово! Ждём тебя снова в Pryzmat Studio 🙂",
        "not_found": (
            "Фотографии по этому коду не найдены. Возможно, прошло {expiry} дней "
            "и материалы были удалены согласно политике конфиденциальности, "
            "или код неверный.\n"
            "Свяжись со студией — вместе найдём решение."
        ),
        "already_sent": (
            "Твои фотографии уже были отправлены ранее — прокрути историю этого чата, "
            "они должны быть там.\n"
            "Если чего-то не хватает, напиши в студию. Ты не останешься один с проблемой. 🙂"
        ),
        "no_files": (
            "Папка сессии найдена, но в ней нет фотографий для отправки. "
            "Свяжись со студией."
        ),
        "use_code": "Введи код сессии командой:\n/code ТВОЙ_КОД",
    },
    "uk": {
        "greeting": (
            "Привіт! 👋 Це бот Pryzmat Studio — тут ти отримаєш фотографії з сесії.\n"
            "Зараз надішлю твої матеріали. Хвилинку…"
        ),
        "privacy": (
            "🔒 Кілька слів про конфіденційність:\n"
            "Твої фотографії зберігаються виключно на зашифрованому сервері студії "
            "і не передаються третім особам. Бот не зберігає жодних копій — "
            "файли надсилаються безпосередньо з сервера тобі.\n"
            "Матеріали будуть доступні протягом {expiry} днів з дати сесії, "
            "після чого будуть безповоротно видалені.\n"
            "Якщо є питання — студія завжди на зв'язку. Ти не залишишся сам з проблемою."
        ),
        "done": "Готово! Чекаємо тебе знову в Pryzmat Studio 🙂",
        "not_found": (
            "Фотографії за цим кодом не знайдено. Можливо, минуло {expiry} днів "
            "і матеріали були видалені згідно з політикою конфіденційності, "
            "або код невірний.\n"
            "Зв'яжись зі студією — разом знайдемо рішення."
        ),
        "already_sent": (
            "Твої фотографії вже були надіслані раніше — прогорни історію цього чату, "
            "вони мають там бути.\n"
            "Якщо чогось не вистачає, напиши до студії. Ти не залишишся сам з проблемою. 🙂"
        ),
        "no_files": (
            "Папку сесії знайдено, але в ній немає фотографій для надсилання. "
            "Зв'яжись зі студією."
        ),
        "use_code": "Введи код сесії командою:\n/code ТВІЙ_КОД",
    },
    "en": {
        "greeting": (
            "Hi! 👋 This is the Pryzmat Studio bot — here you can receive your session photos.\n"
            "I'll send your files in a moment…"
        ),
        "privacy": (
            "🔒 A few words about privacy:\n"
            "Your photos are stored exclusively on the studio's encrypted server "
            "and are not shared with third parties. The bot does not keep any copies — "
            "files are sent directly from the server to you.\n"
            "Your materials will be available for {expiry} days from the session date, "
            "after which they will be permanently and irreversibly deleted.\n"
            "If you have any questions, the studio is here for you. "
            "You won't be left alone with a problem."
        ),
        "done": "Done! We hope to see you again at Pryzmat Studio 🙂",
        "not_found": (
            "I couldn't find photos for this code. It's possible that {expiry} days have passed "
            "and the materials were deleted according to our privacy policy, "
            "or the code is incorrect.\n"
            "Please contact the studio — we'll find a solution together."
        ),
        "already_sent": (
            "Your photos were already sent earlier — scroll up in this chat, "
            "they should be there.\n"
            "If anything is missing, contact the studio. You won't be left alone with a problem. 🙂"
        ),
        "no_files": (
            "Session folder found, but there are no photos to send. "
            "Please contact the studio."
        ),
        "use_code": "Send your session code with:\n/code YOUR_CODE",
    },
}


def _t(lang: str, key: str, **kwargs) -> str:
    """Zwraca tekst w danym języku (fallback EN)."""
    texts = _TEXTS.get(lang) or _TEXTS["en"]
    text  = texts.get(key, _TEXTS["en"][key])
    return text.format(expiry=EXPIRY, **kwargs) if kwargs or "{expiry}" in text else text


# ─────────────────────────── Telegram API helpers

def _api(method: str, **params) -> dict:
    """Wywołuje metodę Telegram Bot API (GET z parametrami)."""
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        logger.warning(f"API {method} error: {e}")
        return {}


def _send(chat_id: int, text: str) -> None:
    """Wysyła wiadomość tekstową."""
    _api("sendMessage", chat_id=chat_id, text=text)


def _send_document(chat_id: int, path: str) -> bool:
    """Wysyła plik jako dokument (bezstratnie)."""
    with open(path, "rb") as f:
        data = f.read()
    filename = os.path.basename(path)
    ctype    = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{chat_id}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read().decode())
            return bool(result.get("ok"))
    except Exception as e:
        logger.warning(f"sendDocument error ({filename}): {e}")
        return False


# ─────────────────────────── Logika obsługi kodów

_JPEG_EXTS = {".jpg", ".jpeg", ".JPG", ".JPEG"}


def _collect_jpegs(folder: str) -> list[str]:
    """Zbiera pliki JPEG z folderu sesji (nierekurencyjnie)."""
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if os.path.splitext(f)[1] in _JPEG_EXTS
    )


def _handle_code(chat_id: int, lang: str, code: str) -> None:
    """Obsługuje kod sesji — sprawdza, wysyła zdjęcia."""
    code = code.upper().strip()
    key  = f"{chat_id}:{code}"

    # Już wysłano w tej sesji bota
    if key in _sent_this_session:
        _send(chat_id, _t(lang, "already_sent"))
        return

    folder = session_codes.resolve(code, EXPIRY)
    if not folder:
        _send(chat_id, _t(lang, "not_found"))
        return

    # Powitanie + prywatność
    _send(chat_id, _t(lang, "greeting"))
    _send(chat_id, _t(lang, "privacy"))

    # Wysyłka plików
    files = _collect_jpegs(folder)
    if not files:
        _send(chat_id, _t(lang, "no_files"))
        return

    ok = 0
    for path in files:
        if _send_document(chat_id, path):
            ok += 1
        time.sleep(0.3)   # throttle — Telegram limit 30 msg/s

    _sent_this_session.add(key)
    logger.info(f"Wysłano {ok}/{len(files)} plików dla kodu {code} → chat {chat_id}")
    _send(chat_id, _t(lang, "done"))


# ─────────────────────────── Główna pętla

def _parse_code_from_text(text: str) -> str | None:
    """Wyciąga kod z '/start ABC123' lub '/code ABC123'."""
    parts = text.strip().split()
    if len(parts) >= 2 and parts[0] in ("/start", "/code"):
        return parts[1]
    return None


def main():
    if not TOKEN:
        print("Błąd: ustaw zmienną środowiskową SHARE_BOT_TOKEN")
        sys.exit(1)

    logger.info("Share bot uruchomiony")
    offset = 0

    while True:
        result = _api("getUpdates", offset=offset, timeout=20)
        updates = result.get("result", [])

        for update in updates:
            offset = update["update_id"] + 1
            msg    = update.get("message", {})
            text   = msg.get("text", "")
            if not text:
                continue

            chat_id   = msg["chat"]["id"]
            # Ignoruj wiadomości z grup i kanałów — tylko prywatne czaty
            chat_type = msg.get("chat", {}).get("type", "")
            if chat_type != "private":
                continue
            lang    = msg.get("from", {}).get("language_code", "en")[:2]

            code = _parse_code_from_text(text)
            if code:
                _handle_code(chat_id, lang, code)
            else:
                _send(chat_id, _t(lang, "use_code"))

        time.sleep(POLL_INT)


if __name__ == "__main__":
    main()
