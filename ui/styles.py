"""
Wspólne style przycisków — używane we wszystkich widokach.
"""

# Globalny styl aplikacji — szara obwódka focus zamiast niebieskiej Fusion
# Zastosować: app.setStyleSheet(APP_STYLE) w main.py
APP_STYLE = (
    "QToolTip { color: #bbbbbb; background-color: #2b2b2b; border: 1px solid #555555; }"
    " QPushButton { background-color: palette(button); }"
    " QPushButton:hover { background-color: palette(midlight); }"
    " QPushButton:focus, QPushButton:default {"
    " border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px;"
    " background-color: palette(midlight); }"
    " QPushButton:focus:hover, QPushButton:default:hover { background-color: palette(midlight); }"
)

# Czerwony przycisk destruktywny / stop (STOP SESSION, Format Card, Close All)
BTN_STYLE_RED = (
    "QPushButton { background-color: #c55d61; color: white; font-weight: bold; }"
    " QPushButton:hover { background-color: #d06e72; }"
    " QPushButton:disabled { background-color: #c55d61; color: rgba(255,255,255,140); }"
    " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: #c55d61; }"
    " QPushButton:focus:hover { background-color: #d06e72; }"
)

# ── Stałe dla dialogów informacyjnych ────────────────────────────────────────

# Geometria
DIALOG_SPACING    = 8
DIALOG_MARGINS    = (12, 12, 12, 12)
DIALOG_MIN_WIDTH  = 480
DIALOG_IMG_SIZE   = 280

# Rozmiary przycisków
DIALOG_BTN_W      = 90
DIALOG_BTN_H      = 34
DIALOG_BTN_SHOW_W = 55   # przycisk "Show" przy polach hasła

# Style tekstu
DIALOG_TEXT_STYLE = "font-size: 15px;"
DIALOG_HINT_STYLE = "color: #888; font-size: 11px;"
DIALOG_HINT_STYLE_PADDED = "color: #888; font-size: 11px; padding: 4px;"


def center_on_parent(dialog) -> None:
    """Centruje dialog na rodzicu. Bez rodzica — bez przesunięcia."""
    parent = dialog.parent()
    if parent is None:
        return
    geo = dialog.frameGeometry()
    geo.moveCenter(parent.frameGeometry().center())
    dialog.move(geo.topLeft())
