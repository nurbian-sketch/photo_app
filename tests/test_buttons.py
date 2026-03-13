#!/usr/bin/env python3
"""
Podgląd przycisków aplikacji — 3 rodzaje.
Użycie:
  python3 tests/test_buttons.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton,
)

from ui.styles import APP_STYLE, BTN_STYLE_RED

BTN_STYLE_AUTO = (
    "QPushButton:checked { background-color: #2e7d32; color: white; font-weight: bold; }"
    " QPushButton:disabled { background-color: #3a3a3a; color: #666; border: 1px solid #444; }"
    " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: palette(button); }"
    " QPushButton:checked:focus { background-color: #2e7d32; border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; }"
)


def _row(label, *buttons):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 8, 0, 8)
    h.setSpacing(12)
    lbl = QLabel(label)
    lbl.setStyleSheet("color: #888; font-size: 11px; min-width: 200px;")
    h.addWidget(lbl)
    for b in buttons:
        h.addWidget(b)
    h.addStretch(1)
    return w


class ButtonShowcase(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Przyciski aplikacji")
        self.resize(600, 280)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.setSpacing(0)

        # Domyślny
        b1 = QPushButton("Continue →");      b1.setFixedHeight(42)
        b2 = QPushButton("New Session");     b2.setFixedHeight(42)
        b3 = QPushButton("Cancel");          b3.setFixedSize(90, 34)
        lay.addWidget(_row("domyślny  (APP_STYLE)", b1, b2, b3))

        # Czerwony
        b4 = QPushButton("■  STOP SESSION"); b4.setFixedHeight(48); b4.setStyleSheet(BTN_STYLE_RED)
        b5 = QPushButton("Format Card");     b5.setMinimumHeight(28); b5.setStyleSheet(BTN_STYLE_RED)
        lay.addWidget(_row("czerwony  (BTN_STYLE_RED)", b4, b5))

        # AUTO
        b6 = QPushButton("AUTO"); b6.setFixedSize(65, 45); b6.setCheckable(True); b6.setStyleSheet(BTN_STYLE_AUTO)
        b7 = QPushButton("AUTO"); b7.setFixedSize(65, 45); b7.setCheckable(True); b7.setChecked(True); b7.setStyleSheet(BTN_STYLE_AUTO)
        lay.addWidget(_row("AUTO  (zielony :checked)", b6, b7))

        lay.addStretch(1)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    w = ButtonShowcase()
    w.show()
    sys.exit(app.exec())
