import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QSizePolicy
)
from PyQt6.QtCore import Qt

class SliderWithScale(QWidget):
    def __init__(self, title, values):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        
        # Tytuł
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight:600;")
        layout.addWidget(title_label)
        
        # Kontener osi
        axis = QWidget()
        axis_layout = QVBoxLayout(axis)
        axis_layout.setContentsMargins(0, 0, 0, 0)
        axis_layout.setSpacing(2)
        
        # ===== SKALA (100% SZEROKOŚCI) =====
        scale_row = QHBoxLayout()
        scale_row.setSpacing(0)
        scale_row.setContentsMargins(0, 0, 0, 0)
        
        for v in values:
            lbl = QLabel(v)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scale_row.addWidget(lbl, stretch=1)
        
        axis_layout.addLayout(scale_row)
        
        # ===== SUWAK (KRÓTSZY O PÓŁ ETYKIETY Z KAŻDEJ STRONY) =====
        slider_row = QHBoxLayout()
        slider_row.setSpacing(0)
        slider_row.setContentsMargins(0, 0, 0, 0)
        
        # Obliczenia marginesów
        # Każda etykieta zajmuje 1/n szerokości
        # Suwak rozpoczyna się w środku pierwszej (margines = 0.5 etykiety)
        # i kończy w środku ostatniej (margines = 0.5 etykiety)
        label_fraction = 1.0 / len(values)
        margin_fraction = label_fraction / 2
        slider_fraction = 1.0 - 2 * margin_fraction
        
        # Przeliczenie na "jednostki stretch"
        # Używamy 1000 jako bazę dla precyzji
        base = 1000
        OFFSET = 7  
        
        left_margin = int(margin_fraction * base) - OFFSET   # ← ZMIEŃ
        slider_width = int(slider_fraction * base) + 2 * OFFSET  # ← ZMIEŃ
        right_margin = left_margin  # ← bez zmian
        
        # Suwak
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, len(values) - 1)
        
        # Layout z marginesami
        slider_row.addStretch(left_margin)
        slider_row.addWidget(slider, stretch=slider_width)
        slider_row.addStretch(right_margin)
        
        axis_layout.addLayout(slider_row)
        layout.addWidget(axis)
        
        # ===== WYBRANA WARTOŚĆ =====
        value_label = QLabel(values[0])
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet("font-size:18px; font-weight:600;")
        layout.addWidget(value_label)
        
        slider.valueChanged.connect(
            lambda i: value_label.setText(values[i])
        )


class Demo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wyrównanie suwaka ze skalą")
        self.setMinimumWidth(800)
        
        main = QVBoxLayout(self)
        main.setSpacing(30)
        
        # Przysłona
        aperture_values = ["f/1.8", "f/2.8", "f/4"]
        main.addWidget(SliderWithScale("Aperture", aperture_values))
        
        # Czas naświetlania
        shutter_values = ["1/8000", "1/4000", "1/2000", "1/1000", "1/500", "1/250", "1/125"]
        main.addWidget(SliderWithScale("Shutter Speed", shutter_values))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = Demo()
    w.show()
    sys.exit(app.exec())
