"""
Test doboru koloru czerwonego dla przycisków STOP.
Uruchom: python3 test_red_picker.py
Kliknij przyciski — podaj numer wybranego koloru.
"""
import sys
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtCore import Qt

COLORS = [
    ("#b85050", "1 — #b85050  (za jasny — punkt odniesienia)"),
    ("#a04444", "2 — #a04444"),
    ("#924040", "3 — #924040  (ok. -20% Fusion pressed)"),
    ("#853c3c", "4 — #853c3c"),
    ("#783838", "5 — #783838"),
    ("#6b3232", "6 — #6b3232  (najciemniejszy)"),
]

def make_btn_style(color: str) -> str:
    return (
        f"QPushButton {{ background-color: {color}; color: white; font-weight: bold; font-size: 14px; }}"
        f" QPushButton:focus {{ border: 1px solid rgba(180,180,180,0.9); border-radius: 3px; background-color: {color}; }}"
    )

app = QApplication(sys.argv)
app.setStyle("Fusion")

# Ciemna paleta jak w apce
pal = app.palette()
pal.setColor(QPalette.ColorRole.Window,      QColor("#3c3c3c"))
pal.setColor(QPalette.ColorRole.WindowText,  QColor("#e0e0e0"))
pal.setColor(QPalette.ColorRole.Base,        QColor("#2b2b2b"))
pal.setColor(QPalette.ColorRole.Button,      QColor("#4a4a4a"))
pal.setColor(QPalette.ColorRole.ButtonText,  QColor("#e0e0e0"))
pal.setColor(QPalette.ColorRole.Midlight,    QColor("#5a5a5a"))
pal.setColor(QPalette.ColorRole.Highlight,   QColor("#a0a0a0"))
pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#0a0a0a"))
app.setPalette(pal)

win = QWidget()
win.setWindowTitle("Wybierz kolor przycisku STOP")
win.setMinimumWidth(480)

root = QVBoxLayout(win)
root.setSpacing(12)
root.setContentsMargins(30, 30, 30, 30)

title = QLabel("Kliknij każdy przycisk i wybierz numer:")
title.setStyleSheet("font-size: 13px; color: #ccc;")
root.addWidget(title)

root.addSpacing(8)

for color, label in COLORS:
    row = QHBoxLayout()

    desc = QLabel(label)
    desc.setFixedWidth(260)
    desc.setStyleSheet("font-size: 12px; color: #aaa;")
    row.addWidget(desc)

    btn = QPushButton("■  STOP SESSION")
    btn.setFixedSize(200, 44)
    btn.setStyleSheet(make_btn_style(color))
    row.addWidget(btn)

    root.addLayout(row)

root.addSpacing(8)
note = QLabel("Statyczne kolory — bez efektu hover/press. Wybierz ten który wygląda jak #b85050 po naciśnięciu.")
note.setWordWrap(True)
note.setStyleSheet("font-size: 11px; color: #888;")
root.addWidget(note)

win.show()
sys.exit(app.exec())
