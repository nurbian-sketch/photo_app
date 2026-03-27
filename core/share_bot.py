"""
core/share_bot.py

Bot Telegram dla Pryzmat Studio — menu nawigacyjne + odbieranie zdjęć z sesji.
Uruchamiany przez share_bot_tray/__main__.py jako odłączony subprocess.
Używa wyłącznie biblioteki standardowej (urllib) — brak zewnętrznych zależności.

Zmiany vs oryginał:
- TOKEN i GROQ_KEY z QSettings (nie z env)
- lock file dla singleton
- status JSON dla ikony w pasku aplikacji
- pending_sends: zdjęcia w trakcie obróbki → auto-wysyłka gdy gotowe
- Groq AI: wykrywanie intencji z dowolnego tekstu (klient nie musi znać komend)
- fallback na statyczne teksty gdy Groq niedostępny
- [fix1] nieznany tekst → podpowiedź z przyciskiem Menu (nie spam całego menu)
- [fix2] greeting + privacy + email_info → jedna wiadomość przed plikami
- [fix3] komunikat o paczkowaniu używa _t() zamiast hardkodowanego angielskiego
- [fix4] _sent_this_session persystentne na dysku (odporność na restart bota)
- [fix5] state machine: kontekst oczekiwania na kod sesji
- [fix6] lang=None → bezpieczny fallback "en"
"""
import json
import logging
import mimetypes
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta

# Dodaj katalog projektu do ścieżki
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_DIR)
import core.session_codes as session_codes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [share_bot] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────── Ścieżki

_DATA_DIR    = os.path.expanduser("~/.local/share/photo_app")
LOCK_FILE    = os.path.join(_DATA_DIR, "share_bot.lock")
STATUS_FILE  = os.path.join(_DATA_DIR, "share_bot_status.json")
PENDING_FILE = os.path.join(_DATA_DIR, "share_bot_pending.json")
SENT_FILE    = os.path.join(_DATA_DIR, "share_bot_sent.json")   # [fix4]

# ─────────────────────────── Konfiguracja z QSettings

def _read_settings() -> dict:
    try:
        QSettings = __import__(
            'PyQt6.QtCore', fromlist=['QSettings']
        ).QSettings
        s = QSettings("Grzeza", "SessionsAssistant")
        return {
            "token":    s.value("telegram/bot_token", "").strip(),
            "groq_key": s.value("groq/api_key", "").strip(),
            "expiry":   s.value("sharing/code_expiry_days", 14, type=int),
            "remote":   s.value("rclone/remote", "gdrive").strip(),
            "dest":     s.value("rclone/destination", "Sessions").strip(),
        }
    except Exception as e:
        logger.warning(f"Błąd odczytu QSettings: {e}")
        return {"token": "", "groq_key": "", "expiry": 14, "remote": "gdrive", "dest": "Sessions"}


_cfg           = _read_settings()
TOKEN          = _cfg["token"]
GROQ_KEY       = _cfg["groq_key"]
EXPIRY         = _cfg["expiry"]
POLL_INT       = 2   # sekundy między getUpdates
_RCLONE_REMOTE = _cfg.get("remote", "gdrive")
_RCLONE_DEST   = _cfg.get("dest", "Sessions")

STUDIO_LAT   = 50.81350099271024
STUDIO_LNG   = 19.112614510292705
STUDIO_ADDR  = "ul. Jana Henryka Dąbrowskiego 4/13\n42-202 Częstochowa"
STUDIO_PHONE = "+48 603 666 111"
BOT_USERNAME = "pryzmat_studio_bot"

# [fix4] historia wysłanych kodów — ładowana z dysku przy starcie
_sent_this_session: set[str] = set()

# [fix5] state machine — chat_id → lang oczekujący na kod
_waiting_for_code: dict[int, str] = {}

# ─────────────────────────── Lock + Status

def _acquire_lock() -> bool:
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                return False  # już działa
            except (ProcessLookupError, ValueError):
                pass
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return False   # przy błędzie — nie startuj, bezpieczniej


def _release_lock():
    try:
        os.unlink(LOCK_FILE)
    except OSError:
        pass


def _write_status(status: str, pending_count: int = 0):
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "status":        status,
                "pid":           os.getpid(),
                "updated_at":    datetime.now().isoformat(),
                "pending_count": pending_count,
            }, f, indent=2)
    except OSError:
        pass


# ─────────────────────────── Pending sends

def _load_pending() -> dict:
    """Wczytuje oczekujące wysyłki z pliku JSON."""
    try:
        if os.path.exists(PENDING_FILE):
            with open(PENDING_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_pending(pending: dict):
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def _add_pending(chat_id: int, code: str, lang: str, folder: str):
    """Dodaje oczekującą wysyłkę."""
    pending = _load_pending()
    key = f"{chat_id}:{code}"
    pending[key] = {
        "chat_id":  chat_id,
        "code":     code,
        "lang":     lang,
        "folder":   folder,
        "added_at": datetime.now().isoformat(),
    }
    _save_pending(pending)
    logger.info(f"Pending: dodano {key}")


def _check_pending():
    """
    Sprawdza oczekujące wysyłki.
    Jeśli JPG gotowe → wysyła i usuwa z kolejki.
    Jeśli > 48h bez plików → informuje klienta i usuwa.
    """
    pending = _load_pending()
    if not pending:
        return

    to_remove = []
    cutoff    = datetime.now() - timedelta(hours=48)

    for key, entry in pending.items():
        chat_id = entry["chat_id"]
        code    = entry["code"]
        lang    = entry["lang"]
        folder  = entry["folder"]
        added   = datetime.fromisoformat(entry["added_at"])

        # Timeout — zbyt długo czekamy
        if added < cutoff:
            _send(chat_id, _t(lang, "pending_timeout"))
            to_remove.append(key)
            logger.info(f"Pending: timeout dla {key}")
            continue

        # Folder zniknął
        if not os.path.isdir(folder):
            _send(chat_id, _t(lang, "pending_timeout"))
            to_remove.append(key)
            continue

        # Sprawdź czy JPG już są
        files = _collect_jpegs(folder)
        if not files:
            continue  # jeszcze nie gotowe

        # JPG gotowe — wyślij!
        logger.info(f"Pending: pliki gotowe dla {key} — wysyłam")
        _write_status("sending", len(pending) - 1)
        _send(chat_id, _t(lang, "pending_ready"))
        _send_files_to_client(chat_id, lang, code, files)
        to_remove.append(key)

    if to_remove:
        for key in to_remove:
            del pending[key]
        _save_pending(pending)


# ─────────────────────────── Persystentna historia wysłanych kodów [fix4]

def _load_sent() -> set[str]:
    """Wczytuje historię wysłanych kodów z dysku."""
    try:
        if os.path.exists(SENT_FILE):
            with open(SENT_FILE, encoding="utf-8") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()


def _save_sent(sent: set[str]):
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        with open(SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(list(sent), f)
    except OSError:
        pass


def _mark_sent(key: str):
    """Dodaje klucz do historii wysłanych (pamięć + dysk)."""
    _sent_this_session.add(key)
    _save_sent(_sent_this_session)


# ─────────────────────────── Email log (GDrive _meta)

_email_log_cache: list[dict] = []
_email_log_fetched_at: datetime | None = None
_EMAIL_LOG_TTL = 120   # sekundy — cache na 2 minuty


def _get_email_log() -> list[dict]:
    """
    Pobiera email_log.json z gdrive:Sessions/_meta/ przez rclone cat.
    Cache TTL = 2 minuty — nie odpytuje rclone przy każdej wiadomości.
    Zwraca listę wpisów lub [] przy błędzie.
    """
    global _email_log_cache, _email_log_fetched_at

    now = datetime.now()
    if (
        _email_log_fetched_at is not None
        and (now - _email_log_fetched_at).total_seconds() < _EMAIL_LOG_TTL
    ):
        return _email_log_cache

    remote_path = f"{_RCLONE_REMOTE}:{_RCLONE_DEST}/_meta/email_log.json"
    try:
        result = subprocess.run(
            ["rclone", "cat", remote_path],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            _email_log_cache      = json.loads(result.stdout)
            _email_log_fetched_at = now
            logger.debug(f"email_log: załadowano {len(_email_log_cache)} wpisów")
        else:
            _email_log_cache      = []
            _email_log_fetched_at = now
    except Exception as e:
        logger.warning(f"email_log: błąd rclone cat: {e}")
        _email_log_cache      = []
        _email_log_fetched_at = now

    return _email_log_cache


def _get_email_sent_info(code: str) -> dict | None:
    """
    Zwraca wpis email_log dla danego kodu lub None.
    { code, email, sent_at }
    """
    for entry in _get_email_log():
        if entry.get("code", "").upper() == code.upper():
            return entry
    return None


# ─────────────────────────── Groq AI

def _groq_detect_intent(text: str) -> dict:
    """
    Wykrywa intencję z dowolnego tekstu przez Groq.
    Zwraca: {"intent": "code"|"get_photos"|"other", "code": "ABC123"|null}
    Fallback: prosta heurystyka (regex).
    """
    import re as _re

    # Regex tylko gdy tekst jest krótki i wygląda jak sam kod
    stripped = text.strip()
    if _re.fullmatch(r'[A-Z0-9]{6}', stripped.upper()):
        return {"intent": "code", "code": stripped.upper()}

    # Bez Groq — prosta heurystyka
    if not GROQ_KEY:
        keywords = ["zdjęci", "photo", "foto", "код", "фото", "знімк"]
        if any(k in text.lower() for k in keywords):
            return {"intent": "get_photos", "code": None}
        return {"intent": "other", "code": None}

    # Groq
    system_prompt = (
        "You are an intent classifier for a photo studio Telegram bot. "
        "Analyze the user message and return ONLY valid JSON, no explanation.\n"
        "Return: {\"intent\": \"code\" | \"get_photos\" | \"other\", \"code\": \"XXXXXX\" or null}\n"
        "- code: user provided or mentioned a 6-character alphanumeric session code "
        "(extract it uppercase as 'code')\n"
        "- get_photos: user wants to receive their session photos but didn't provide a code\n"
        "- other: anything else\n"
        "A code is always exactly 6 uppercase letters/digits, e.g. AB3X7Z."
    )
    payload = json.dumps({
        "model":       "llama-3.3-70b-versatile",
        "messages":    [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": text[:500]},
        ],
        "max_tokens":  60,
        "temperature": 0,
    }).encode()

    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {GROQ_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"].strip()
        return json.loads(content)
    except Exception as e:
        logger.warning(f"Groq intent detection error: {e}")
        return {"intent": "other", "code": None}


# ─────────────────────────── Tłumaczenia

_TEXTS: dict[str, dict[str, str]] = {
    "pl": {
        "menu_greeting": "Cześć! 👋 Witaj w bocie Pryzmat Studio.\nCzym mogę Ci pomóc?",
        "btn_location":  "📍 Jak do nas trafić",
        "btn_call":      "📞 Zadzwoń do nas",
        "btn_photos":    "📸 Odbierz zdjęcia",
        "btn_cancel":    "📅 Odwołanie sesji",
        "btn_private":   "🔒 Sesja prywatna",
        "btn_rules":     "📋 Zasady studia",
        "btn_menu":      "📋 Menu",
        "location_text": (
            "📍 Pryzmat Studio\n"
            "ul. Jana Henryka Dąbrowskiego 4/13\n"
            "42-202 Częstochowa\n"
            "📞 +48 603 666 111"
        ),
        "call_text":   "📞 Zadzwoń do nas:\n+48 603 666 111",
        "ask_code":    "Podaj kod sesji ze zdjęcia QR lub wpisz go ręcznie:",
        "cancel_text": (
            "Sesję można odwołać najpóźniej na 2 godziny przed jej rozpoczęciem.\n"
            "Zadzwoń do nas: +48 603 666 111"
        ),
        "private_text": (
            "🔒 Sesja prywatna\n\n"
            "Prosimy o przybycie 15 minut przed sesją.\n\n"
            "💳 Karta pamięci:\n"
            "Aparat wymaga karty SD lub CF-express typu A. "
            "Polecamy karty UHS-II (min. 60 MB/s zapis). "
            "Nie odpowiadamy za utratę danych spowodowaną wadliwą kartą "
            "— najlepiej przynieś własną, sprawdzoną.\n\n"
            "Masz pytania? Zadzwoń: +48 603 666 111"
        ),
        "rules_text": (
            "📋 Zasady studia\n\n"
            "👟 Wymagane obuwie zmienne lub brak obuwia (tak, boso można — wygodniej! 😄)\n"
            "👔 Możesz przynieść własne ubrania — mamy wieszaki.\n"
            "⏰ Sesję odwołaj min. 2h przed — zadzwoń do nas.\n\n"
            "Do zobaczenia! 📸"
        ),
        "greeting": (
            "Cześć! 👋 Tu bot Pryzmat Studio.\n"
            "Zaraz wyślę Twoje zdjęcia. Chwilkę…"
        ),
        "privacy": (
            "🔒 Twoje zdjęcia przechowywane są wyłącznie na zaszyfrowanym serwerze studia "
            "i nie są udostępniane osobom trzecim. "
            "Materiały będą dostępne przez {expiry} dni od daty sesji."
        ),
        "done":     "Gotowe! Zapraszamy ponownie do Pryzmat Studio 🙂",
        "not_found": (
            "Nie znalazłem zdjęć dla tego kodu. Możliwe że minęło {expiry} dni "
            "i materiały zostały usunięte, lub kod jest nieprawidłowy.\n"
            "Skontaktuj się ze studiem — na pewno znajdziemy rozwiązanie."
        ),
        "already_sent": (
            "Twoje zdjęcia zostały już wysłane wcześniej — przewiń historię tego czatu.\n"
            "Jeśli czegoś brakuje, napisz do studia. 🙂"
        ),
        "no_files": (
            "Znalazłem folder sesji, ale nie ma w nim zdjęć. "
            "Skontaktuj się ze studiem."
        ),
        "developing": (
            "📸 Twoje zdjęcia są właśnie wywoływane z cyfrowych negatywów.\n"
            "Dam Ci znać gdy będą gotowe — zazwyczaj zajmuje to kilka minut. ⏳"
        ),
        "pending_ready":   "✅ Twoje zdjęcia są gotowe! Wysyłam je teraz… 📸",
        "pending_timeout": (
            "Przepraszamy za opóźnienie. Skontaktuj się ze studiem — "
            "na pewno znajdziemy rozwiązanie. 🙏\n"
            "📞 +48 603 666 111"
        ),
        "email_sent_info": (
            "📧 Link do pobrania został też wysłany na adres {email} w dniu {sent_at}."
        ),
        "not_ready":        "📸 Twoje zdjęcia nie są jeszcze wywołane.",
        "notify_ask":       "Chcesz, żebym dał Ci znać gdy będą gotowe?",
        "notify_yes_btn":   "✅ Tak, powiadom mnie",
        "notify_no_btn":    "❌ Nie, dziękuję",
        "notify_confirmed": "Super! Powiadomię Cię gdy zdjęcia będą gotowe. 🙂",
        "notify_declined":  "Ok! Jeśli zmienisz zdanie, napisz ponownie swój kod sesji.",
        "batch_sending":    "📦 Wysyłam {total} zdjęć w paczkach po {batch}…",   # [fix3]
        "unknown_text":     "Nie rozumiem. Skorzystaj z menu 👇",                 # [fix1]
    },
    "ru": {
        "menu_greeting": "Привет! 👋 Добро пожаловать в бот Pryzmat Studio.\nЧем могу помочь?",
        "btn_location":  "📍 Как нас найти",
        "btn_call":      "📞 Позвони нам",
        "btn_photos":    "📸 Получить фото",
        "btn_cancel":    "📅 Отмена сессии",
        "btn_private":   "🔒 Частная сессия",
        "btn_rules":     "📋 Правила студии",
        "btn_menu":      "📋 Меню",
        "location_text": (
            "📍 Pryzmat Studio\n"
            "ул. Яна Хенрика Домбровского 4/13\n"
            "42-202 Ченстохова\n"
            "📞 +48 603 666 111"
        ),
        "call_text":   "📞 Позвони нам:\n+48 603 666 111",
        "ask_code":    "Введи код сессии с QR-фото или напиши его вручную:",
        "cancel_text": (
            "Сессию можно отменить не позднее чем за 2 часа.\n"
            "Позвони нам: +48 603 666 111"
        ),
        "private_text": (
            "🔒 Частная сессия\n\n"
            "Просим прийти за 15 минут до начала.\n\n"
            "💳 Карта памяти: SD или CF-express типа A. "
            "Рекомендуем UHS-II (мин. 60 МБ/с). "
            "Лучше принеси свою, проверенную.\n\n"
            "Вопросы? Позвони: +48 603 666 111"
        ),
        "rules_text": (
            "📋 Правила студии\n\n"
            "👟 Сменная обувь или босиком (да, можно — удобнее! 😄)\n"
            "👔 Можешь принести свою одежду — у нас есть вешалки.\n"
            "⏰ Отменяй за 2ч — позвони нам.\n\nДо встречи! 📸"
        ),
        "greeting":        "Привет! 👋 Бот Pryzmat Studio.\nСейчас отправлю твои фото. Минутку…",
        "privacy":         (
            "🔒 Твои фото хранятся только на зашифрованном сервере студии. "
            "Доступны {expiry} дней с даты сессии."
        ),
        "done":     "Готово! Ждём тебя снова в Pryzmat Studio 🙂",
        "not_found": (
            "Фото по этому коду не найдены. Возможно прошло {expiry} дней, "
            "или код неверный.\nСвяжись со студией — найдём решение."
        ),
        "already_sent":    "Фото уже были отправлены ранее — прокрути историю чата. 🙂",
        "no_files":        "Папка сессии найдена, но фото отсутствуют. Свяжись со студией.",
        "developing":      (
            "📸 Твои фото сейчас обрабатываются.\n"
            "Сообщу, когда будут готовы. Обычно занимает несколько минут. ⏳"
        ),
        "pending_ready":   "✅ Твои фото готовы! Отправляю сейчас… 📸",
        "pending_timeout": (
            "Извини за задержку. Свяжись со студией — найдём решение. 🙏\n"
            "📞 +48 603 666 111"
        ),
        "email_sent_info": (
            "📧 Ссылка для скачивания также отправлена на адрес {email} ({sent_at})."
        ),
        "not_ready":        "📸 Твои фотографии ещё не обработаны.",
        "notify_ask":       "Хочешь, чтобы я сообщил, когда они будут готовы?",
        "notify_yes_btn":   "✅ Да, уведоми меня",
        "notify_no_btn":    "❌ Нет, спасибо",
        "notify_confirmed": "Отлично! Сообщу, когда фото будут готовы. 🙂",
        "notify_declined":  "Хорошо! Если передумаешь — напиши свой код снова.",
        "batch_sending":    "📦 Отправляю {total} фото пачками по {batch}…",
        "unknown_text":     "Не понимаю. Воспользуйся меню 👇",
    },
    "uk": {
        "menu_greeting": "Привіт! 👋 Ласкаво просимо до бота Pryzmat Studio.\nЧим можу допомогти?",
        "btn_location":  "📍 Як нас знайти",
        "btn_call":      "📞 Зателефонуй нам",
        "btn_photos":    "📸 Отримати фото",
        "btn_cancel":    "📅 Скасування сесії",
        "btn_private":   "🔒 Приватна сесія",
        "btn_rules":     "📋 Правила студії",
        "btn_menu":      "📋 Меню",
        "location_text": (
            "📍 Pryzmat Studio\n"
            "вул. Яна Хенрика Домбровського 4/13\n"
            "42-202 Ченстохова\n"
            "📞 +48 603 666 111"
        ),
        "call_text":   "📞 Зателефонуй нам:\n+48 603 666 111",
        "ask_code":    "Введи код сесії з QR-фото або напиши його вручну:",
        "cancel_text": (
            "Сесію можна скасувати не пізніше ніж за 2 години.\n"
            "Зателефонуй нам: +48 603 666 111"
        ),
        "private_text": (
            "🔒 Приватна сесія\n\n"
            "Просимо прийти за 15 хвилин до початку.\n\n"
            "💳 Карта пам'яті: SD або CF-express типу A. "
            "Рекомендуємо UHS-II (мін. 60 МБ/с). "
            "Краще принеси свою, перевірену.\n\n"
            "Питання? Зателефонуй: +48 603 666 111"
        ),
        "rules_text": (
            "📋 Правила студії\n\n"
            "👟 Змінне взуття або босоніж (так, можна — зручніше! 😄)\n"
            "👔 Можеш принести власний одяг — у нас є вішаки.\n"
            "⏰ Скасовуй за 2г — зателефонуй нам.\n\nДо побачення! 📸"
        ),
        "greeting":        "Привіт! 👋 Бот Pryzmat Studio.\nЗараз надішлю твої фото. Хвилинку…",
        "privacy":         (
            "🔒 Твої фото зберігаються лише на зашифрованому сервері студії. "
            "Доступні {expiry} днів з дати сесії."
        ),
        "done":     "Готово! Чекаємо тебе знову в Pryzmat Studio 🙂",
        "not_found": (
            "Фото за цим кодом не знайдено. Можливо минуло {expiry} днів, "
            "або код невірний.\nЗв'яжись зі студією — знайдемо рішення."
        ),
        "already_sent":    "Фото вже були надіслані раніше — прогорни історію чату. 🙂",
        "no_files":        "Папку сесії знайдено, але фото відсутні. Зв'яжись зі студією.",
        "developing":      (
            "📸 Твої фото зараз обробляються.\n"
            "Повідомлю, коли будуть готові. Зазвичай кілька хвилин. ⏳"
        ),
        "pending_ready":   "✅ Твої фото готові! Надсилаю зараз… 📸",
        "pending_timeout": (
            "Вибач за затримку. Зв'яжись зі студією — знайдемо рішення. 🙏\n"
            "📞 +48 603 666 111"
        ),
        "email_sent_info": (
            "📧 Посилання для завантаження також надіслано на адресу {email} ({sent_at})."
        ),
        "not_ready":        "📸 Твої фотографії ще не опрацьовані.",
        "notify_ask":       "Хочеш, щоб я повідомив, коли вони будуть готові?",
        "notify_yes_btn":   "✅ Так, повідом мене",
        "notify_no_btn":    "❌ Ні, дякую",
        "notify_confirmed": "Чудово! Повідомлю, коли фото будуть готові. 🙂",
        "notify_declined":  "Добре! Якщо зміниш думку — напиши свій код знову.",
        "batch_sending":    "📦 Надсилаю {total} фото пачками по {batch}…",
        "unknown_text":     "Не розумію. Скористайся меню 👇",
    },
    "en": {
        "menu_greeting": "Hi! 👋 Welcome to the Pryzmat Studio bot.\nHow can I help you?",
        "btn_location":  "📍 How to find us",
        "btn_call":      "📞 Call us",
        "btn_photos":    "📸 Get your photos",
        "btn_cancel":    "📅 Cancel session",
        "btn_private":   "🔒 Private session",
        "btn_rules":     "📋 Studio rules",
        "btn_menu":      "📋 Menu",
        "location_text": (
            "📍 Pryzmat Studio\n"
            "ul. Jana Henryka Dąbrowskiego 4/13\n"
            "42-202 Częstochowa\n"
            "📞 +48 603 666 111"
        ),
        "call_text":   "📞 Call us:\n+48 603 666 111",
        "ask_code":    "Enter the session code from your QR photo or type it manually:",
        "cancel_text": (
            "Sessions can be cancelled up to 2 hours before they begin.\n"
            "Call us: +48 603 666 111"
        ),
        "private_text": (
            "🔒 Private session\n\n"
            "Please arrive 15 minutes before the session.\n\n"
            "💳 Memory card: SD or CF-express Type A. "
            "We recommend UHS-II (min. 60 MB/s). "
            "Best to bring your own trusted card.\n\n"
            "Questions? Call: +48 603 666 111"
        ),
        "rules_text": (
            "📋 Studio rules\n\n"
            "👟 Indoor shoes or barefoot (yes, really — more comfortable! 😄)\n"
            "👔 Feel free to bring your own clothes — we have hangers.\n"
            "⏰ Cancel at least 2h before — call us.\n\nSee you there! 📸"
        ),
        "greeting":        "Hi! 👋 Pryzmat Studio bot here.\nSending your photos in a moment…",
        "privacy":         (
            "🔒 Your photos are stored exclusively on the studio's encrypted server. "
            "Available for {expiry} days from your session date."
        ),
        "done":     "Done! We hope to see you again at Pryzmat Studio 🙂",
        "not_found": (
            "I couldn't find photos for this code. It's possible {expiry} days have passed "
            "and the materials were deleted, or the code is incorrect.\n"
            "Please contact the studio — we'll find a solution."
        ),
        "already_sent":    "Your photos were already sent — scroll up in this chat. 🙂",
        "no_files":        "Session folder found, but there are no photos. Contact the studio.",
        "developing":      (
            "📸 Your photos are currently being developed from digital negatives.\n"
            "I'll notify you when they're ready — usually takes a few minutes. ⏳"
        ),
        "pending_ready":   "✅ Your photos are ready! Sending them now… 📸",
        "pending_timeout": (
            "Sorry for the delay. Please contact the studio — we'll sort it out. 🙏\n"
            "📞 +48 603 666 111"
        ),
        "email_sent_info": (
            "📧 A download link was also sent to {email} on {sent_at}."
        ),
        "not_ready":        "📸 Your photos haven't been developed yet.",
        "notify_ask":       "Would you like me to notify you when they're ready?",
        "notify_yes_btn":   "✅ Yes, notify me",
        "notify_no_btn":    "❌ No, thanks",
        "notify_confirmed": "Great! I'll let you know when your photos are ready. 🙂",
        "notify_declined":  "No problem! If you change your mind, just send your code again.",
        "batch_sending":    "📦 Sending {total} photos in batches of {batch}…",
        "unknown_text":     "I didn't understand that. Use the menu 👇",
    },
}


def _t(lang: str, key: str, **kwargs) -> str:
    texts = _TEXTS.get(lang) or _TEXTS["en"]
    text  = texts.get(key) or _TEXTS["en"].get(key, key)
    return text.format(expiry=EXPIRY, **kwargs) if kwargs or "{expiry}" in text else text


# ─────────────────────────── Telegram API

def _api(method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning(f"API {method} error: {e}")
        return {}


def _post(method: str, body: bytes, content_type: str) -> dict:
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning(f"POST {method} error: {e}")
        return {}


def _send(chat_id: int, text: str) -> bool:
    result = _post(
        "sendMessage",
        json.dumps({"chat_id": chat_id, "text": text}).encode(),
        "application/json",
    )
    return result.get("ok", False)


def _make_thumbnail(file_path: str) -> bytes | None:
    """Generuje miniaturę JPEG max 320x320 przez Pillow. Zwraca None przy błędzie."""
    try:
        from PIL import Image
        import io
        with Image.open(file_path) as img:
            img = img.convert("RGB")
            img.thumbnail((320, 320))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            return buf.getvalue()
    except Exception as e:
        logger.debug(f"Thumbnail generation failed for {os.path.basename(file_path)}: {e}")
        return None


def _build_multipart(chat_id: int, file_path: str) -> tuple[bytes, str]:
    boundary  = uuid.uuid4().hex
    filename  = os.path.basename(file_path)
    mime      = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        file_data = f.read()

    thumb_data = _make_thumbnail(file_path)

    def _field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()

    def _file_field(name: str, fname: str, data: bytes, ctype: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode() + data + b"\r\n"

    body = (
        _field("chat_id", str(chat_id))
        + _file_field("document", filename, file_data, mime)
    )
    if thumb_data:
        body += _file_field("thumbnail", "thumb.jpg", thumb_data, "image/jpeg")
    body += f"--{boundary}--\r\n".encode()

    return body, boundary


def _send_document(chat_id: int, path: str) -> bool:
    body, boundary = _build_multipart(chat_id, path)
    result = _post("sendDocument", body, f"multipart/form-data; boundary={boundary}")
    if not result.get("ok"):
        logger.warning(f"sendDocument failed ({os.path.basename(path)}): {result}")
        return False
    return True


# ─────────────────────────── Menu i nawigacja

def _send_menu(chat_id: int, lang: str) -> None:
    keyboard = {
        "inline_keyboard": [
            [
                {"text": _t(lang, "btn_location"), "callback_data": "location"},
                {"text": _t(lang, "btn_call"),     "callback_data": "call"},
            ],
            [
                {"text": _t(lang, "btn_photos"),   "callback_data": "get_photos"},
                {"text": _t(lang, "btn_cancel"),   "callback_data": "cancel"},
            ],
            [
                {"text": _t(lang, "btn_private"),  "callback_data": "private"},
                {"text": _t(lang, "btn_rules"),    "callback_data": "rules"},
            ],
        ]
    }
    _post(
        "sendMessage",
        json.dumps({
            "chat_id":      chat_id,
            "text":         _t(lang, "menu_greeting"),
            "reply_markup": keyboard,
        }).encode(),
        "application/json",
    )


def _send_location(chat_id: int, lang: str) -> None:
    _send(chat_id, _t(lang, "location_text"))
    _api("sendLocation", chat_id=chat_id, latitude=STUDIO_LAT, longitude=STUDIO_LNG)


def _send_unknown(chat_id: int, lang: str) -> None:
    """[fix1] Nieznany tekst → krótka podpowiedź z przyciskiem Menu (bez spamu całego menu)."""
    keyboard = {
        "inline_keyboard": [[
            {"text": _t(lang, "btn_menu"), "callback_data": "menu"},
        ]]
    }
    _post(
        "sendMessage",
        json.dumps({
            "chat_id":      chat_id,
            "text":         _t(lang, "unknown_text"),
            "reply_markup": keyboard,
        }).encode(),
        "application/json",
    )


def _handle_callback(callback_id: str, chat_id: int, lang: str, data: str) -> None:
    if data == "location":
        _send_location(chat_id, lang)
    elif data == "call":
        _send(chat_id, _t(lang, "call_text"))
    elif data == "get_photos":
        # [fix5] ustaw stan oczekiwania na kod
        _waiting_for_code[chat_id] = lang
        _send(chat_id, _t(lang, "ask_code"))
    elif data == "menu":
        # [fix5] wyczyść stan przy powrocie do menu
        _waiting_for_code.pop(chat_id, None)
        _send_menu(chat_id, lang)
    elif data == "cancel":
        _send(chat_id, _t(lang, "cancel_text"))
    elif data == "private":
        _send(chat_id, _t(lang, "private_text"))
    elif data == "rules":
        _send(chat_id, _t(lang, "rules_text"))
    elif data == "notify_no":
        _send(chat_id, _t(lang, "notify_declined"))
    elif data.startswith("notify_yes:"):
        # format: notify_yes:KOD:lang
        parts = data.split(":")
        if len(parts) >= 3:
            cb_code   = parts[1]
            cb_lang   = parts[2]
            cb_folder = session_codes.resolve(cb_code, EXPIRY)
            if cb_folder:
                _add_pending(chat_id, cb_code, cb_lang, cb_folder)
                _send(chat_id, _t(cb_lang, "notify_confirmed"))
            else:
                _send(chat_id, _t(lang, "not_found"))
    _api("answerCallbackQuery", callback_query_id=callback_id)


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


def _send_files_to_client(chat_id: int, lang: str, code: str, files: list[str]):
    """Wysyła pliki JPEG jako dokumenty (bezstratnie). Dzieli na paczki po 10."""
    BATCH = 10
    total = len(files)
    ok    = 0

    if total > BATCH:
        # [fix3] lokalizowany komunikat zamiast hardkodowanego angielskiego
        _send(chat_id, _t(lang, "batch_sending", total=total, batch=BATCH))

    for path in files:
        if _send_document(chat_id, path):
            ok += 1
        time.sleep(0.3)

    # [fix4] persystentny zapis wysłanych kodów
    _mark_sent(f"{chat_id}:{code}")
    logger.info(f"Wysłano {ok}/{total} plików dla kodu {code} → chat {chat_id}")
    _send(chat_id, _t(lang, "done"))


def _send_notify_ask(chat_id: int, lang: str, code: str) -> None:
    """Wysyła pytanie czy klient chce powiadomienie z przyciskami Tak/Nie."""
    keyboard = {
        "inline_keyboard": [[
            {"text": _t(lang, "notify_yes_btn"),
             "callback_data": f"notify_yes:{code}:{lang}"},
            {"text": _t(lang, "notify_no_btn"),
             "callback_data": f"notify_no"},
        ]]
    }
    _post(
        "sendMessage",
        json.dumps({
            "chat_id":      chat_id,
            "text":         _t(lang, "not_ready") + "\n\n" + _t(lang, "notify_ask"),
            "reply_markup": keyboard,
        }).encode(),
        "application/json",
    )


def _handle_code(chat_id: int, lang: str, code: str) -> None:
    """Obsługuje kod sesji — sprawdza, wysyła lub informuje o obróbce."""
    code = code.upper().strip()
    key  = f"{chat_id}:{code}"

    # [fix5] wyczyść stan oczekiwania niezależnie od wyniku
    _waiting_for_code.pop(chat_id, None)

    if key in _sent_this_session:
        _send(chat_id, _t(lang, "already_sent"))
        return

    folder = session_codes.resolve(code, EXPIRY)
    if not folder:
        _send(chat_id, _t(lang, "not_found"))
        return

    # Sprawdź czy zdjęcia już są
    files = _collect_jpegs(folder)

    if not files:
        # Brak JPG — zapytaj czy klient chce powiadomienie
        _send_notify_ask(chat_id, lang, code)
        return

    # [fix2] greeting + privacy + email_sent_info → jedna wiadomość
    _write_status("sending", len(_load_pending()))

    intro_lines = [_t(lang, "greeting"), _t(lang, "privacy")]

    email_info = _get_email_sent_info(code)
    if email_info:
        try:
            sent_dt  = datetime.fromisoformat(email_info["sent_at"].replace("Z", "+00:00"))
            sent_str = sent_dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            sent_str = email_info.get("sent_at", "")
        intro_lines.append(_t(lang, "email_sent_info",
                              email=email_info.get("email", ""),
                              sent_at=sent_str))

    _send(chat_id, "\n\n".join(intro_lines))
    _send_files_to_client(chat_id, lang, code, files)


# ─────────────────────────── Główna pętla

def main():
    global _sent_this_session

    if not TOKEN:
        print("[share_bot] Błąd: brak tokenu Telegram w QSettings")
        sys.exit(1)

    if not _acquire_lock():
        print("[share_bot] Już uruchomiony — wychodzę")
        sys.exit(0)

    # [fix4] załaduj historię wysłanych kodów z dysku
    _sent_this_session = _load_sent()
    logger.info(
        "Share bot uruchomiony (PID %d), załadowano %d wysłanych kodów",
        os.getpid(), len(_sent_this_session),
    )
    _write_status("idle")

    offset        = 0
    pending_check = 0   # licznik iteracji — sprawdzaj pending co 60 iteracji (~2 min)

    try:
        while True:
            _write_status("idle", len(_load_pending()))

            # Sprawdź oczekujące wysyłki co ~2 minuty
            pending_check += 1
            if pending_check >= 60:
                pending_check = 0
                _check_pending()

            # Pobierz aktualizacje
            result  = _api("getUpdates", offset=offset, timeout=20)
            updates = result.get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                _write_status("active", len(_load_pending()))

                # ── callback z przycisku inline
                cb = update.get("callback_query")
                if cb:
                    cb_chat = cb.get("message", {}).get("chat", {})
                    if cb_chat.get("type") == "private":
                        # [fix6] bezpieczny fallback gdy language_code=None
                        lang = (cb.get("from", {}).get("language_code") or "en")[:2]
                        _handle_callback(cb["id"], cb_chat["id"], lang, cb.get("data", ""))
                    continue

                # ── wiadomość tekstowa
                msg = update.get("message", {})
                if not msg or msg.get("chat", {}).get("type") != "private":
                    continue

                text = msg.get("text", "").strip()
                if not text:
                    continue

                chat_id = msg["chat"]["id"]
                # [fix6] bezpieczny fallback gdy language_code=None
                lang    = (msg.get("from", {}).get("language_code") or "en")[:2]
                parts   = text.split()
                cmd     = parts[0] if parts else ""

                # Obsłuż komendy
                if cmd == "/start" and len(parts) >= 2:
                    _waiting_for_code.pop(chat_id, None)
                    _handle_code(chat_id, lang, parts[1])
                elif cmd in ("/start", "/menu"):
                    _waiting_for_code.pop(chat_id, None)
                    _send_menu(chat_id, lang)
                elif cmd == "/code" and len(parts) >= 2:
                    _handle_code(chat_id, lang, parts[1])
                else:
                    # [fix5] sprawdź stan oczekiwania na kod
                    if chat_id in _waiting_for_code:
                        _handle_code(chat_id, _waiting_for_code[chat_id], text)
                    else:
                        # Dowolny tekst → Groq wykrywa intencję
                        intent = _groq_detect_intent(text)
                        if intent["intent"] == "code" and intent.get("code"):
                            _handle_code(chat_id, lang, intent["code"])
                        elif intent["intent"] == "get_photos":
                            # [fix5] ustaw stan oczekiwania na kod
                            _waiting_for_code[chat_id] = lang
                            _send(chat_id, _t(lang, "ask_code"))
                        else:
                            # [fix1] krótka podpowiedź zamiast pełnego menu
                            _send_unknown(chat_id, lang)

            time.sleep(POLL_INT)

    except KeyboardInterrupt:
        logger.info("Share bot zatrzymany")
    finally:
        _write_status("stopped")
        _release_lock()


if __name__ == "__main__":
    main()
