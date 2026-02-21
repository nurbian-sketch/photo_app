#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for camera control widgets.
Tests SliderWithScale and LabeledComboBox components.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent  # Go up from tests/ to project root
sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QGroupBox, QLabel
from PyQt6.QtCore import Qt
from ui.widgets.slider_with_scale import SliderWithScale
from ui.widgets.labeled_combo_box import LabeledComboBox


class WidgetTestWindow(QWidget):
    """Test window for camera control widgets"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Camera Widgets Test")
        self.setMinimumWidth(600)  # było 800
        self.setMinimumHeight(900)  # Widgets are now more compact vertically
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Build test interface"""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)  # było 20 - odległość między grupami
        
        # Title
        title = QLabel("Camera Control Widgets Test")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # ═══════════════════════════════════════════════════════
        # SLIDER WIDGETS GROUP
        # ═══════════════════════════════════════════════════════
        slider_group = QGroupBox("SliderWithScale Widgets")
        slider_layout = QVBoxLayout(slider_group)
        slider_layout.setSpacing(6)  # było 10 - odległość między suwakami
        
        # ISO Slider
        iso_values = ['100', '200', '400', '800', '1600', '3200', '6400']
        self.iso_slider = SliderWithScale("ISO Sensitivity", iso_values)
        self.iso_slider.set_value('800')
        self.iso_slider.valueChanged.connect(
            lambda v: print(f"ISO changed: {v}")
        )
        slider_layout.addWidget(self.iso_slider)
        
        # Aperture Slider
        aperture_values = ['f/1.4', 'f/2', 'f/2.8', 'f/4', 'f/5.6', 'f/8', 'f/11']
        self.aperture_slider = SliderWithScale("Aperture", aperture_values)
        self.aperture_slider.set_value('f/2.8')
        self.aperture_slider.valueChanged.connect(
            lambda v: print(f"Aperture changed: {v}")
        )
        slider_layout.addWidget(self.aperture_slider)
        
        # Shutter Speed Slider
        shutter_values = ['1/8000', '1/4000', '1/2000', '1/1000', '1/500', '1/250', '1/125', '1/60']
        self.shutter_slider = SliderWithScale("Shutter Speed", shutter_values)
        self.shutter_slider.set_value('1/125')
        self.shutter_slider.valueChanged.connect(
            lambda v: print(f"Shutter speed changed: {v}")
        )
        slider_layout.addWidget(self.shutter_slider)
        
        # Exposure Compensation (with negative values)
        ev_values = ['-3', '-2', '-1', '0', '+1', '+2', '+3']
        self.ev_slider = SliderWithScale("Exposure Compensation (EV)", ev_values)
        self.ev_slider.set_value('0')
        self.ev_slider.valueChanged.connect(
            lambda v: print(f"EV compensation changed: {v}")
        )
        slider_layout.addWidget(self.ev_slider)
        
        layout.addWidget(slider_group)
        
        # ═══════════════════════════════════════════════════════
        # COMBOBOX WIDGETS GROUP
        # ═══════════════════════════════════════════════════════
        combo_group = QGroupBox("LabeledComboBox Widgets")
        combo_layout = QVBoxLayout(combo_group)
        combo_layout.setSpacing(8)  # Reduced from 15
        
        # White Balance
        wb_items = ['Auto', 'Daylight', 'Cloudy', 'Tungsten', 'Fluorescent', 'Manual']
        self.wb_combo = LabeledComboBox("White Balance", wb_items)
        self.wb_combo.currentTextChanged.connect(
            lambda v: print(f"White Balance changed: {v}")
        )
        combo_layout.addWidget(self.wb_combo)
        
        # Picture Style
        ps_items = ['Standard', 'Portrait', 'Landscape', 'Neutral', 'Monochrome']
        self.ps_combo = LabeledComboBox("Picture Style", ps_items)
        self.ps_combo.currentTextChanged.connect(
            lambda v: print(f"Picture Style changed: {v}")
        )
        combo_layout.addWidget(self.ps_combo)
        
        # Focus Mode
        focus_items = ['One Shot', 'AI Servo', 'AI Focus', 'Manual']
        self.focus_combo = LabeledComboBox("Focus Mode", focus_items)
        self.focus_combo.currentTextChanged.connect(
            lambda v: print(f"Focus Mode changed: {v}")
        )
        combo_layout.addWidget(self.focus_combo)
        
        layout.addWidget(combo_group)
        
        # ═══════════════════════════════════════════════════════
        # STATUS
        # ═══════════════════════════════════════════════════════
        status = QLabel("Check console output for value changes")
        status.setStyleSheet("""
            QLabel {
                background-color: #E3F2FD;
                padding: 10px;
                border-radius: 4px;
                color: #1565C0;
                font-style: italic;
            }
        """)
        layout.addWidget(status)


def main():
    """Run the test"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    print("="*60)
    print("Camera Control Widgets Test")
    print("="*60)
    print()
    print("Testing SliderWithScale with OFFSET=7 alignment")
    print("Testing LabeledComboBox component")
    print()
    print("Interact with widgets and watch console output")
    print("="*60)
    print()
    
    window = WidgetTestWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
