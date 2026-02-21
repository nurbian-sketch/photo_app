import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QGroupBox, QSlider, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QLinearGradient, QColor

class ColorTempGradient(QWidget):
    """Mały widget rysujący pasek gradientu"""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(12)
        self.setMinimumWidth(200)

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        
        # Kolory od 2500K do 10000K
        gradient.setColorAt(0.0, QColor(255, 60, 0))     # 2500K
        gradient.setColorAt(0.2, QColor(255, 190, 110))  # 3200K
        gradient.setColorAt(0.5, QColor(255, 255, 255))  # 5500K
        gradient.setColorAt(0.8, QColor(180, 210, 255))  # 7500K
        gradient.setColorAt(1.0, QColor(80, 150, 255))   # 10000K
        
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.rect(), 6, 6)

class StandaloneTest(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test Interfejsu - WB Gradient & Align")
        self.resize(800, 500)
        self._init_ui()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)

        # --- KOLUMNA 1 (Ekspozycja) ---
        col1 = QVBoxLayout()
        exp_group = QGroupBox("Exposure (Fv)")
        exp_lay = QVBoxLayout(exp_group)
        for i in range(4):
            row = QHBoxLayout()
            row.addWidget(QPushButton("AUTO"))
            s = QSlider(Qt.Orientation.Horizontal)
            row.addWidget(s)
            exp_lay.addLayout(row)
        col1.addWidget(exp_group)
        # UWAGA: Tu nie dajemy stretch, żeby góra była sztywna

        # --- KOLUMNA 2 (Image & Focus) ---
        col2 = QVBoxLayout()
        
        # Grupa Image Settings
        img_group = QGroupBox("Image Settings")
        img_lay = QVBoxLayout(img_group)
        img_lay.addWidget(QLabel("Quality: RAW"))
        img_lay.addWidget(QLabel("WB: Color Temperature"))
        
        # Nasz nowy gradient
        img_lay.addWidget(QLabel("Color Temp (K)"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        img_lay.addWidget(self.slider)
        
        self.gradient = ColorTempGradient()
        img_lay.addWidget(self.gradient)
        
        self.hint = QLabel("Info: Daylight (5500K)")
        self.hint.setStyleSheet("color: #aaa; font-style: italic;")
        img_lay.addWidget(self.hint)
        
        col2.addWidget(img_group)

        # KLUCZ: To wyrównuje dół AF z dołem Exposure
        col2.addStretch(1)

        # Grupa Focus Settings
        af_group = QGroupBox("Focus Settings")
        af_lay = QVBoxLayout(af_group)
        af_lay.addWidget(QLabel("AF Method: LiveFace"))
        af_lay.addWidget(QLabel("Focus Mode: One Shot"))
        col2.addWidget(af_group)

        main_layout.addLayout(col1)
        main_layout.addLayout(col2)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion") # Dla lepszego wyglądu
    window = StandaloneTest()
    window.show()
    sys.exit(app.exec())
