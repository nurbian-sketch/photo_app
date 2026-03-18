"""
Wspólne style przycisków — używane we wszystkich widokach.
"""

# Globalny styl aplikacji — szara obwódka focus zamiast niebieskiej Fusion
# Zastosować: app.setStyleSheet(APP_STYLE) w main.py
APP_STYLE = (
    "QToolTip { color: #bbbbbb; background-color: #2b2b2b; border: 1px solid #555555; }"
    " QPushButton:focus, QPushButton:default {"
    " border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; }"
    " QToolButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; }"
    " QToolButton:hover { border: 1px solid rgba(180, 180, 180, 0.9); }"
)

# Czerwony przycisk destruktywny / stop (STOP SESSION, Format Card, Close All)
BTN_STYLE_RED = (
    "QPushButton { background-color: #9f2023; color: white; font-weight: bold; padding: 0 12px; }"
    " QPushButton:hover { background-color: #b52a2e; }"
    " QPushButton:disabled { background-color: #9f2023; color: rgba(255,255,255,140); }"
    " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: #9f2023; padding: 0 12px; }"
    " QPushButton:focus:hover { background-color: #b52a2e; }"
)

# ── Stałe dla dialogów informacyjnych ────────────────────────────────────────

# Geometria
DIALOG_SPACING    = 8
DIALOG_MARGINS    = (12, 12, 12, 12)
DIALOG_MIN_WIDTH  = 480
DIALOG_MIN_HEIGHT = 520
DIALOG_IMG_SIZE   = 280

# Rozmiary przycisków
DIALOG_BTN_H      = 34
DIALOG_BTN_W      = 120
DIALOG_BTN_H_SMALL = 28

# Style tekstu
DIALOG_TEXT_STYLE = "font-size: 15px;"
DIALOG_HINT_STYLE = "color: #888; font-size: 11px;"
DIALOG_HINT_STYLE_PADDED = "color: #888; font-size: 11px; padding: 4px;"


# ── SessionActiveDialog ──────────────────────────────────────────────────────

SESSION_PANEL_BG = "#3d3d3d"

# Countdown (duży zegar na ciemnym tle)
SESSION_COUNTDOWN_STYLE = "color: #e0e0e0; background: transparent;"

# Pasek postępu sesji
SESSION_PROGRESS_STYLE = (
    "QProgressBar { background-color: rgba(0,0,0,120); border-radius: 0px;"
    " border: 1px solid rgba(255,255,255,40); }"
    " QProgressBar::chunk { background-color: rgba(255,255,255,200); border-radius: 0px; }"
)

# Etykiety na ciemnym tle (info o sesji, postęp importu)
SESSION_INFO_STYLE   = "color: rgba(255,255,255,180); font-size: 14px; background: transparent; padding: 8px 0;"
SESSION_IMPORT_STYLE = "color: rgba(255,255,255,180); font-size: 13px; background: transparent;"

# Rozmiary przycisków sesji
SESSION_BTN_H      = 42
SESSION_BTN_STOP_H = 48


# Etykieta szczegółów / detali sesji (szara, mała)
DIALOG_DETAILS_STYLE = "color: #aaa; font-size: 13px;"

# Ostrzeżenia w dialogach
DIALOG_WARNING_STYLE = "color: #e65100; font-size: 12px;"

# Focus border dla QListWidget — spójny z APP_STYLE
LISTWIDGET_FOCUS_STYLE = "QListWidget:focus { border: 1px solid rgba(180, 180, 180, 0.6); }"

# ConfigPanel — info o wybranym trybie sesji
CONFIG_MODE_INFO_STYLE = "color: #aaa; font-style: italic;"

# Overlay — etykieta pod obrazem aparatu (brak kamery / brak SD)
OVERLAY_LABEL_STYLE = f"color: #aaa; font-size: 13px; background: {SESSION_PANEL_BG}; padding: 10px 0;"

# Ramka trybu bezprzewodowego (lewy panel podczas aktywnej sesji)
SESSION_WIRELESS_FRAME_STYLE = "QFrame { border: 2px solid #888; border-radius: 6px; margin: 12px; }"
SESSION_WIRELESS_MSG_STYLE   = "color: #c0c0c0; font-size: 15px; border: none;"


def set_panel_bg(widget, color: str = SESSION_PANEL_BG) -> None:
    """Ustawia kolor tła przez paletę — nie wchodzi w stylesheet mode, nie psuje dzieci."""
    from PyQt6.QtGui import QColor, QPalette
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(color))
    widget.setPalette(pal)
    widget.setAutoFillBackground(True)


def center_on_parent(dialog) -> None:
    """Centruje dialog na rodzicu. Bez rodzica — bez przesunięcia."""
    parent = dialog.parent()
    if parent is None:
        return
    geo = dialog.frameGeometry()
    geo.moveCenter(parent.frameGeometry().center())
    dialog.move(geo.topLeft())
