# Sessions Assistant — zasady pracy z kodem

## Projekt
Aplikacja do zarządzania sesjami fotograficznymi. PyQt6 + gphoto2, Canon EOS RP.
Katalog: `~/Projekty/photo_app/`

## Struktura
```
core/          — logika biznesowa (gphoto, darkcache, probe)
ui/views/      — widoki (camera_view, darkroom_view, session_view)
ui/widgets/    — wielokrotnego użytku widgety
ui/dialogs/    — dialogi
ui/            — main_window, camera_card_service
files/         — pliki robocze, testy, archiwum (NIE wdrażaj stąd bez polecenia)
assets/        — ikony, obrazy (nie modyfikuj)
```

## Język
- Komentarze w kodzie: **polski**
- UI (etykiety, przyciski, komunikaty): **angielski**
- Nazwy metod, zmiennych, modułów: **angielski**
- Aplikacja przygotowana pod tłumaczenia (tr())

## Styl interfejsu
- Motyw: **Fusion** — nie wychodzić poza niego bez uzgodnienia
- Żadnych `setStyleSheet` które łamią Fusion (wyjątek: kolory statusów — zielony/czerwony)

## Zasady edycji kodu

### Przed każdą zmianą
1. Upewnij się że masz aktualny plik — przeczytaj go z dysku (`cat` lub `view`)
2. Jeśli plik był już modyfikowany w tej sesji i nie jesteś pewien stanu — powiedz wprost
3. Nigdy nie edytuj z pamięci po serii zmian

### Podczas zmian
- Tylko **chirurgiczne zmiany** — minimum kodu, maksimum efektu
- Nie przepisuj działających fragmentów bez wyraźnego powodu
- Nie usuwaj funkcjonalności bez polecenia

### Po każdej zmianie
- Podaj liczby linii: `[plik: NNN → MMM linii]`
- Duży spadek linii (>15%) = sygnał alarmowy — opisz co usunięto
- Sprawdź składnię: `python3 -c "import ast; ast.parse(open('plik.py').read())"`

## Deployment
```bash
# Zawsze cp z files/ do docelowego katalogu, nigdy odwrotnie
cp ~/Projekty/photo_app/files/PLIK ~/Projekty/photo_app/DOCELOWY/PLIK
python3 ~/Projekty/photo_app/main.py
```

## Git
- Git jest prawdą — wersja referencyjna zawsze w repozytorium
- Commit po każdym zakończonym etapie
- Opis commita: zwięzły, po angielsku, opisuje CO i DLACZEGO

## Pliki których nie ruszamy bez wyraźnego polecenia
- `core/gphoto_interface.py` — krytyczny, race conditions w wątkach
- `core/camera_probe.py` — diagnostyka USB, delikatna logika
- `assets/` — tylko do odczytu

## Architektura wątków
- `GPhotoInterface` to `QThread` — komunikacja TYLKO przez sygnały Qt
- Nigdy nie wywołuj metod gphoto bezpośrednio z wątku UI
- `keep_running = False` + `wait(3000)` + `terminate()` jako fallback

## Darkcache
- CR3: binarny parser ISOBMFF w `thumbnail_reader.py` — nie zastępuj exiftool subprocess
- `DarkCacheService` → `ExifThumbnailReader` (miniatury) → `PreviewGenerator` (duże preview)
- Cache na dysku — nie czyść bez powodu

## Sygnały problemów do zgłoszenia
- Gubisz kontekst po wielu zmianach → powiedz wprost, przygotuj HANDOFF.md
- Nie wiesz który plik jest aktualny → zapytaj o upload
- Zmiana dotyczy >3 plików naraz → zaproponuj podział na etapy
