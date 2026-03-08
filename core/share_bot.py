"""
core/share_bot.py

Bot Telegram dla Pryzmat Studio — menu nawigacyjne + odbieranie zdjęć z sesji.
Uruchamiany jako osobny proces: python3 core/share_bot.py
Używa wyłącznie biblioteki standardowej (urllib) — brak zewnętrznych zależności.

Flow:
  /start         — menu główne
  /start ABC123  — deep link z QR kodu
  /code ABC123   — wpisanie kodu ręcznie
  /menu          — menu główne
  Przyciski inline — obsługa przez callback_query
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

STUDIO_LAT   = 50.81350099271024
STUDIO_LNG   = 19.112614510292705
STUDIO_ADDR  = "ul. Jana Henryka Dąbrowskiego 4/13\n42-202 Częstochowa"
STUDIO_PHONE = "+48 603 666 111"
BOT_USERNAME = "pryzmat_studio_bot"

# Zbiór kodów dla których już wysłano zdjęcia w tej sesji bota
_sent_this_session: set[str] = set()

# ─────────────────────────── Tłumaczenia

_TEXTS = {
    "pl": {
        "menu_greeting": (
            "Cześć! 👋 Witaj w bocie Pryzmat Studio.\nCzym mogę Ci pomóc?"
        ),
        "btn_location": "📍 Jak do nas trafić",
        "btn_call":     "📞 Zadzwoń do nas",
        "btn_photos":   "📸 Odbierz zdjęcia",
        "btn_cancel":   "📅 Odwołanie sesji",
        "btn_private":  "🔒 Sesja prywatna",
        "btn_rules":    "📋 Zasady studia",
        "location_text": (
            "📍 Pryzmat Studio\n"
            "ul. Jana Henryka Dąbrowskiego 4/13\n"
            "42-202 Częstochowa\n"
            "📞 +48 603 666 111"
        ),
        "call_text": "📞 Zadzwoń do nas:\n+48 603 666 111",
        "ask_code":  "Podaj kod sesji otrzymany w studio:\n/code TWÓJ_KOD",
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
            "👟 Wymagane obuwie zmienne lub brak obuwia "
            "(tak, boso można — wygodniej! 😄)\n"
            "👔 Możesz przynieść własne ubrania — mamy wieszaki.\n"
            "⏰ Sesję odwołaj min. 2h przed — zadzwoń do nas.\n\n"
            "Do zobaczenia! 📸"
        ),
        "coming_soon": "Wkrótce 🙂",
        # Obsługa kodów sesji
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
    },
    "ru": {
        "menu_greeting": (
            "Привет! 👋 Добро пожаловать в бот Pryzmat Studio.\nЧем могу помочь?"
        ),
        "btn_location": "📍 Как нас найти",
        "btn_call":     "📞 Позвони нам",
        "btn_photos":   "📸 Получить фото",
        "btn_cancel":   "📅 Отмена сессии",
        "btn_private":  "🔒 Частная сессия",
        "btn_rules":    "📋 Правила студии",
        "location_text": (
            "📍 Pryzmat Studio\n"
            "ул. Яна Хенрика Домбровского 4/13\n"
            "42-202 Ченстохова\n"
            "📞 +48 603 666 111"
        ),
        "call_text": "📞 Позвони нам:\n+48 603 666 111",
        "ask_code":  "Введи код сессии, полученный в студии:\n/code ТВОЙ_КОД",
        "cancel_text": (
            "Сессию можно отменить не позднее чем за 2 часа до её начала.\n"
            "Позвони нам: +48 603 666 111"
        ),
        "private_text": (
            "🔒 Частная сессия\n\n"
            "Просим прийти за 15 минут до начала сессии.\n\n"
            "💳 Карта памяти:\n"
            "Фотоаппарат требует карту SD или CF-express типа A. "
            "Рекомендуем карты UHS-II (мин. 60 МБ/с запись). "
            "Мы не несём ответственности за потерю данных из-за неисправной карты "
            "— лучше принеси свою, проверенную.\n\n"
            "Есть вопросы? Позвони: +48 603 666 111"
        ),
        "rules_text": (
            "📋 Правила студии\n\n"
            "👟 Требуется сменная обувь или без обуви "
            "(да, босиком можно — удобнее! 😄)\n"
            "👔 Можешь принести свою одежду — у нас есть вешалки.\n"
            "⏰ Отменяй сессию минимум за 2ч — позвони нам.\n\n"
            "До встречи! 📸"
        ),
        "coming_soon": "Скоро 🙂",
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
    },
    "uk": {
        "menu_greeting": (
            "Привіт! 👋 Ласкаво просимо до бота Pryzmat Studio.\nЧим можу допомогти?"
        ),
        "btn_location": "📍 Як нас знайти",
        "btn_call":     "📞 Зателефонуй нам",
        "btn_photos":   "📸 Отримати фото",
        "btn_cancel":   "📅 Скасування сесії",
        "btn_private":  "🔒 Приватна сесія",
        "btn_rules":    "📋 Правила студії",
        "location_text": (
            "📍 Pryzmat Studio\n"
            "вул. Яна Хенрика Домбровського 4/13\n"
            "42-202 Ченстохова\n"
            "📞 +48 603 666 111"
        ),
        "call_text": "📞 Зателефонуй нам:\n+48 603 666 111",
        "ask_code":  "Введи код сесії, отриманий у студії:\n/code ТВІЙ_КОД",
        "cancel_text": (
            "Сесію можна скасувати не пізніше ніж за 2 години до її початку.\n"
            "Зателефонуй нам: +48 603 666 111"
        ),
        "private_text": (
            "🔒 Приватна сесія\n\n"
            "Просимо прийти за 15 хвилин до початку сесії.\n\n"
            "💳 Карта пам'яті:\n"
            "Фотоапарат потребує карти SD або CF-express типу A. "
            "Рекомендуємо карти UHS-II (мін. 60 МБ/с запис). "
            "Ми не несемо відповідальності за втрату даних через несправну карту "
            "— краще принеси свою, перевірену.\n\n"
            "Маєш питання? Зателефонуй: +48 603 666 111"
        ),
        "rules_text": (
            "📋 Правила студії\n\n"
            "👟 Потрібне змінне взуття або без взуття "
            "(так, босоніж можна — зручніше! 😄)\n"
            "👔 Можеш принести власний одяг — у нас є вішаки.\n"
            "⏰ Скасовуй сесію мін. за 2г — зателефонуй нам.\n\n"
            "До побачення! 📸"
        ),
        "coming_soon": "Незабаром 🙂",
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
    },
    "en": {
        "menu_greeting": (
            "Hi! 👋 Welcome to the Pryzmat Studio bot.\nHow can I help you?"
        ),
        "btn_location": "📍 How to find us",
        "btn_call":     "📞 Call us",
        "btn_photos":   "📸 Get your photos",
        "btn_cancel":   "📅 Cancel session",
        "btn_private":  "🔒 Private session",
        "btn_rules":    "📋 Studio rules",
        "location_text": (
            "📍 Pryzmat Studio\n"
            "ul. Jana Henryka Dąbrowskiego 4/13\n"
            "42-202 Częstochowa\n"
            "📞 +48 603 666 111"
        ),
        "call_text": "📞 Call us:\n+48 603 666 111",
        "ask_code":  "Enter the session code you received at the studio:\n/code YOUR_CODE",
        "cancel_text": (
            "Sessions can be cancelled up to 2 hours before they begin.\n"
            "Call us: +48 603 666 111"
        ),
        "private_text": (
            "🔒 Private session\n\n"
            "Please arrive 15 minutes before the session.\n\n"
            "💳 Memory card:\n"
            "The camera requires an SD or CF-express Type A card. "
            "We recommend UHS-II cards (min. 60 MB/s write speed). "
            "We are not responsible for data loss caused by a faulty card "
            "— it's best to bring your own trusted card.\n\n"
            "Any questions? Call: +48 603 666 111"
        ),
        "rules_text": (
            "📋 Studio rules\n\n"
            "👟 Indoor shoes required or barefoot is fine "
            "(yes, really — it's more comfortable! 😄)\n"
            "👔 Feel free to bring your own clothes — we have hangers.\n"
            "⏰ Cancel at least 2h before — call us.\n\n"
            "See you there! 📸"
        ),
        "coming_soon": "Coming soon 🙂",
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
    },
}


def _t(lang: str, key: str, **kwargs) -> str:
    """Zwraca tekst w danym języku (fallback EN)."""
    texts = _TEXTS.get(lang) or _TEXTS["en"]
    text  = texts.get(key) or _TEXTS["en"].get(key, key)
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


def _build_multipart(chat_id: int, path: str) -> tuple[bytes, str]:
    """Buduje body multipart/form-data dla sendDocument. Zwraca (body, boundary)."""
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
    return body, boundary


def _post(endpoint: str, body: bytes, content_type: str) -> dict:
    """Wysyła żądanie POST do Telegram API. Zwraca odpowiedź jako dict."""
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{endpoint}",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        logger.warning(f"POST {endpoint} error: {e}")
        return {}


def _send_document(chat_id: int, path: str) -> bool:
    """Wysyła plik jako dokument (bezstratnie)."""
    body, boundary = _build_multipart(chat_id, path)
    result = _post("sendDocument", body, f"multipart/form-data; boundary={boundary}")
    if not result.get("ok"):
        logger.warning(f"sendDocument failed ({os.path.basename(path)}): {result}")
        return False
    return True


# ─────────────────────────── Menu i nawigacja

def _send_menu(chat_id: int, lang: str) -> None:
    """Wysyła powitanie z inline keyboard (2 kolumny, 3 wiersze)."""
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
    """Wysyła tekst z adresem + pinezka lokalizacji."""
    _send(chat_id, _t(lang, "location_text"))
    _api("sendLocation", chat_id=chat_id, latitude=STUDIO_LAT, longitude=STUDIO_LNG)


def _handle_callback(callback_id: str, chat_id: int, lang: str, data: str) -> None:
    """Obsługuje naciśnięcie przycisku inline."""
    if data == "location":
        _send_location(chat_id, lang)
    elif data == "call":
        _send(chat_id, _t(lang, "call_text"))
    elif data == "get_photos":
        _send(chat_id, _t(lang, "ask_code"))
    elif data == "cancel":
        _send(chat_id, _t(lang, "cancel_text"))
    elif data == "private":
        _send(chat_id, _t(lang, "private_text"))
    elif data == "rules":
        _send(chat_id, _t(lang, "rules_text"))
    # Potwierdź callback — usuwa spinner w UI Telegrama
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

def main():
    if not TOKEN:
        print("Błąd: ustaw zmienną środowiskową SHARE_BOT_TOKEN")
        sys.exit(1)

    logger.info("Share bot uruchomiony")
    offset = 0

    while True:
        result  = _api("getUpdates", offset=offset, timeout=20)
        updates = result.get("result", [])

        for update in updates:
            offset = update["update_id"] + 1

            # ── callback z przycisku inline ──────────────────────────────
            cb = update.get("callback_query")
            if cb:
                cb_chat = cb.get("message", {}).get("chat", {})
                if cb_chat.get("type") == "private":
                    lang = cb.get("from", {}).get("language_code", "en")[:2]
                    _handle_callback(cb["id"], cb_chat["id"], lang, cb.get("data", ""))
                continue

            # ── wiadomość tekstowa ───────────────────────────────────────
            msg = update.get("message", {})
            if not msg:
                continue
            if msg.get("chat", {}).get("type") != "private":
                continue

            text = msg.get("text", "")
            if not text:
                continue

            chat_id = msg["chat"]["id"]
            lang    = msg.get("from", {}).get("language_code", "en")[:2]
            parts   = text.strip().split()
            cmd     = parts[0] if parts else ""

            if cmd == "/start" and len(parts) >= 2:
                _handle_code(chat_id, lang, parts[1])
            elif cmd in ("/start", "/menu"):
                _send_menu(chat_id, lang)
            elif cmd == "/code" and len(parts) >= 2:
                _handle_code(chat_id, lang, parts[1])
            else:
                _send_menu(chat_id, lang)

        time.sleep(POLL_INT)


if __name__ == "__main__":
    main()
