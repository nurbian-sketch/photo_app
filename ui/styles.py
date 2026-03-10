"""
Wspólne style przycisków — używane we wszystkich widokach.
"""

# Czerwony przycisk destruktywny / stop (STOP LIVE VIEW, STOP SESSION, Format Card, Close All)
BTN_STYLE_RED = (
    "QPushButton { background-color: #9e3535; color: white; font-weight: bold; }"
    " QPushButton:disabled { background-color: #9e3535; color: rgba(255,255,255,140); }"
    " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: #9e3535; }"
    " QPushButton:focus:hover { background-color: #9e3535; }"
)
