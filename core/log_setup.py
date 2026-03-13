"""
core/log_setup.py

Centralna konfiguracja logowania dla całej aplikacji.
Wywołuj jako pierwszą operację w main.py, przed importem innych modułów.

Domyślnie (bez -verbose):
  - plik log.txt : WARNING i wyżej
  - konsola      : INFO i wyżej

Z flagą -verbose:
  - plik log.txt : DEBUG (pełne)
  - konsola      : DEBUG (pełne)
"""
import logging

_LOG_FILE = "log.txt"
_FMT = logging.Formatter(
    "%(asctime)s.%(msecs)03d  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)


def setup(verbose: bool = False) -> None:
    """Konfiguruje root logger z handlerem pliku i konsoli.

    Poziomy:
      verbose=False — plik: WARNING, konsola: INFO
      verbose=True  — plik: DEBUG,   konsola: DEBUG
    """
    root = logging.getLogger()
    if root.handlers:
        return  # już skonfigurowany (np. przy ponownym imporcie w testach)

    root.setLevel(logging.DEBUG)  # root przepuszcza wszystko — filtrują handlery

    file_level    = logging.DEBUG   if verbose else logging.WARNING
    console_level = logging.DEBUG   if verbose else logging.INFO

    fh = logging.FileHandler(_LOG_FILE, mode="a", encoding="utf-8")
    fh.setLevel(file_level)
    fh.setFormatter(_FMT)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(_FMT)
    root.addHandler(ch)

    if verbose:
        logging.getLogger(__name__).info("Tryb verbose — pełne logowanie aktywne")
