# Sessions Assistant — instalacja

Aplikacja do zarządzania sesjami fotograficznymi. PyQt6 + gphoto2, Canon EOS RP.

## Wymagania systemowe

Ubuntu / Linux Mint 22+

```bash
sudo apt-get update
sudo apt-get install -y \
    python3 python3-pip python3-venv \
    libgphoto2-dev libgphoto2-6 gphoto2 \
    exiftool \
    rclone \
    qt6-base-dev
```

## Instalacja

```bash
# Rozpakuj archiwum
tar -xzf photo_app_*.tar.gz
cd photo_app

# Utwórz i aktywuj virtualenv
python3 -m venv venv
source venv/bin/activate

# Zainstaluj pakiety Python
pip install --upgrade pip
pip install -r requirements.txt

# Utwórz katalogi danych
mkdir -p ~/.cache/photo_app/previews
mkdir -p ~/Obrazy/sessions
```

## Uruchomienie

```bash
cd ~/Projekty/photo_app
source venv/bin/activate
python3 main.py
```

Tryb diagnostyczny (pełne logi):

```bash
python3 main.py -verbose
```

## Dostęp do aparatu (Canon EOS RP przez USB)

System domyślnie montuje aparat przez GVFS, blokując dostęp gphoto2.
Skrypt `camera-mount.sh` rozwiązuje ten problem:

```bash
# Wyłącz automatyczne montowanie (wymagane do pracy z aplikacją)
./camera-mount.sh disable

# Przywrócenie (gdy chcesz znów używać aparatu jako dysk w menedżerze plików)
./camera-mount.sh enable
```

## Bot Telegram (opcjonalnie)

```bash
export SHARE_BOT_TOKEN="twój_token"
export SHARE_BOT_EXPIRY_DAYS=14   # domyślnie 14 dni
python3 core/share_bot.py
```

## Zależności Python

| Pakiet | Wersja |
|---|---|
| PyQt6 | 6.4.0+ |
| gphoto2 | 2.6.3+ |
| Pillow | 12.x |
| opencv-python | 4.x |
| qrcode | 8.x |
| numpy | 2.x |
| piexif | 1.1.3 |
