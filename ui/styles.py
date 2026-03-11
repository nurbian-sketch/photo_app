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
