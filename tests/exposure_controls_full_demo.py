#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Exposure Controls - PEŁNE DEMO
Wszystkie parametry aparatu Canon EOS RP z integracją cache + matrix

Features:
- Suwaki: ISO, Aperture, Shutter Speed, Exposure Compensation
- Combo: White Balance, Picture Style, Focus Mode, Image Format, Drive Mode
- Color Temperature (tylko gdy WB=Manual)
- Shooting Mode selector (M/Av/Tv/P/Auto) - zmienia dostępność kontrolek
- ParameterCache - śledzi zmiany
- ParameterMatrix - logika enable/disable
- Apply/Reset buttons
- Status bar
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSlider, QComboBox, QPushButton, QGroupBox, QFrame,
    QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from dataclasses import dataclass
from typing import Optional, Dict, Any
from copy import deepcopy


# ═══════════════════════════════════════════════════════════════
# MOCK MODULES (zastępują prawdziwe moduły dla demo)
# ═══════════════════════════════════════════════════════════════

class MockParameterCache:
    """Uproszczona wersja ParameterCache dla demo"""
    def __init__(self):
        self._original = {}
        self._current = {}
        self._dirty = False
    
    def load_from_dict(self, values: dict):
        self._original = deepcopy(values)
        self._current = deepcopy(values)
        self._dirty = False
    
    def set_parameter(self, param: str, value: Any) -> bool:
        old = self._current.get(param)
        if old == value:
            return False
        self._current[param] = value
        self._dirty = any(
            self._original.get(k) != v 
            for k, v in self._current.items()
        )
        return True
    
    def get_parameter(self, param: str, default=None):
        return self._current.get(param, default)
    
    def has_changes(self) -> bool:
        return self._dirty
    
    def get_bulk_update_dict(self) -> dict:
        changes = {}
        for param, new_val in self._current.items():
            orig_val = self._original.get(param)
            if orig_val != new_val:
                changes[param] = new_val
        return changes
    
    def rollback(self):
        self._current = deepcopy(self._original)
        self._dirty = False


class MockParameterMatrix:
    """Uproszczona wersja ParameterMatrix dla demo"""
    
    MODE_AVAILABILITY = {
        'Manual': {
            'iso', 'aperture', 'shutterspeed', 'whitebalance',
            'colortemperature', 'picturestyle', 'focusmode',
            'imageformat', 'drivemode', 'exposurecompensation'
        },
        'Av': {
            'iso', 'aperture', 'whitebalance', 'colortemperature',
            'picturestyle', 'focusmode', 'imageformat', 'drivemode',
            'exposurecompensation'
        },
        'Tv': {
            'iso', 'shutterspeed', 'whitebalance', 'colortemperature',
            'picturestyle', 'focusmode', 'imageformat', 'drivemode',
            'exposurecompensation'
        },
        'P': {
            'iso', 'whitebalance', 'colortemperature', 'picturestyle',
            'focusmode', 'imageformat', 'drivemode', 'exposurecompensation'
        },
        'Auto': {
            'imageformat'
        }
    }
    
    def __init__(self, shooting_mode: str, white_balance: str):
        self.mode = shooting_mode
        self.wb = white_balance
    
    def is_editable(self, param: str) -> tuple:
        """Returns (editable: bool, reason: str)"""
        # Color Temperature tylko gdy WB=Manual
        if param == 'colortemperature':
            if self.wb != 'Manual':
                return (False, "Available only when WB=Manual")
        
        # Sprawdź dostępność według trybu
        available = self.MODE_AVAILABILITY.get(self.mode, set())
        
        if param in available:
            # Dodatkowy check dla colortemperature
            if param == 'colortemperature' and self.wb != 'Manual':
                return (False, "Available only when WB=Manual")
            return (True, None)
        
        # Parametr niedostępny
        reasons = {
            'Manual': '',
            'Av': 'Shutter speed auto in Av mode',
            'Tv': 'Aperture auto in Tv mode',
            'P': 'Aperture and shutter auto in P mode',
            'Auto': 'All parameters locked in Auto mode'
        }
        return (False, reasons.get(self.mode, 'Not available in this mode'))


# ═══════════════════════════════════════════════════════════════
# SLIDER WITH SCALE (OFFSET = 7!)
# ═══════════════════════════════════════════════════════════════

class SliderWithScale(QWidget):
    """
    Suwak z opisaną skalą - idealnie wyrównany.
    
    CRITICAL: OFFSET = 7 dla perfekcyjnego wyrównania!
    """
    
    valueChanged = pyqtSignal(str)  # Emituje wybraną wartość (string)
    
    def __init__(self, title: str, values: list):
        super().__init__()
        self.values = values
        self.current_index = 0
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)  # Zwiększony spacing
        layout.setContentsMargins(10, 10, 10, 10)  # Dodane marginesy
        
        # Tytuł
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(self.title_label)
        
        # Kontener osi
        axis = QWidget()
        axis_layout = QVBoxLayout(axis)
        axis_layout.setContentsMargins(0, 0, 0, 0)
        axis_layout.setSpacing(8)  # Zwiększony spacing między skalą a suwakiem
        
        # SKALA (pełna szerokość)
        scale_row = QHBoxLayout()
        scale_row.setSpacing(0)
        scale_row.setContentsMargins(0, 0, 0, 0)
        
        for v in values:
            lbl = QLabel(str(v))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 13px;")  # Większa czcionka dla etykiet
            lbl.setMinimumHeight(25)  # Minimalna wysokość żeby nie przycinać
            scale_row.addWidget(lbl, stretch=1)
        
        axis_layout.addLayout(scale_row)
        
        # SUWAK (krótszy o pół etykiety z każdej strony)
        slider_row = QHBoxLayout()
        slider_row.setSpacing(0)
        slider_row.setContentsMargins(0, 0, 0, 0)
        
        # Obliczenia marginesów
        label_fraction = 1.0 / len(values)
        margin_fraction = label_fraction / 2
        slider_fraction = 1.0 - 2 * margin_fraction
        
        base = 1000
        OFFSET = 7  # ⚡ OFFSET = 7 - IDEALNA WARTOŚĆ!
        
        left_margin = int(margin_fraction * base) - OFFSET
        slider_width = int(slider_fraction * base) + 2 * OFFSET
        right_margin = left_margin
        
        # Suwak
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(values) - 1)
        self.slider.setValue(0)
        self.slider.setMinimumHeight(30)  # Większy suwak
        
        slider_row.addStretch(left_margin)
        slider_row.addWidget(self.slider, stretch=slider_width)
        slider_row.addStretch(right_margin)
        
        axis_layout.addLayout(slider_row)
        layout.addWidget(axis)
        
        # Wybrana wartość
        self.value_label = QLabel(str(values[0]))
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        self.value_label.setMinimumHeight(35)  # Minimalna wysokość
        layout.addWidget(self.value_label)
        
        # Połączenia
        self.slider.valueChanged.connect(self._on_slider_changed)
    
    def _on_slider_changed(self, index: int):
        self.current_index = index
        value = self.values[index]
        self.value_label.setText(str(value))
        self.valueChanged.emit(str(value))
    
    def set_value(self, value: str):
        """Ustaw wartość programatically"""
        try:
            index = self.values.index(value)
            self.slider.setValue(index)
        except ValueError:
            pass
    
    def get_value(self) -> str:
        """Pobierz obecną wartość"""
        return str(self.values[self.current_index])
    
    def setEnabled(self, enabled: bool):
        """Override setEnabled - disable całego widgetu"""
        super().setEnabled(enabled)
        self.slider.setEnabled(enabled)
        self.title_label.setEnabled(enabled)
        self.value_label.setEnabled(enabled)


# ═══════════════════════════════════════════════════════════════
# LABELED COMBO BOX
# ═══════════════════════════════════════════════════════════════

class LabeledComboBox(QWidget):
    """ComboBox z etykietą"""
    
    currentTextChanged = pyqtSignal(str)
    
    def __init__(self, label: str, items: list):
        super().__init__()
        
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Etykieta
        self.label = QLabel(label)
        self.label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.label)
        
        # ComboBox
        self.combo = QComboBox()
        self.combo.addItems(items)
        layout.addWidget(self.combo)
        
        # Połączenie
        self.combo.currentTextChanged.connect(self.currentTextChanged.emit)
    
    def currentText(self) -> str:
        return self.combo.currentText()
    
    def setCurrentText(self, text: str):
        index = self.combo.findText(text)
        if index >= 0:
            self.combo.setCurrentIndex(index)
    
    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.combo.setEnabled(enabled)
        self.label.setEnabled(enabled)
    
    def setToolTip(self, tooltip: str):
        self.combo.setToolTip(tooltip)


# ═══════════════════════════════════════════════════════════════
# GŁÓWNE OKNO DEMO
# ═══════════════════════════════════════════════════════════════

class ExposureControlsDemo(QWidget):
    """
    Kompletne demo wszystkich parametrów Canon EOS RP.
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Canon EOS RP - All Parameters Demo")
        self.setMinimumWidth(1000)
        self.setMinimumHeight(800)
        
        # Cache i Matrix
        self.cache = MockParameterCache()
        self.matrix = None
        
        # Domyślne wartości
        self.default_values = {
            'shootingmode': 'Manual',
            'iso': '800',
            'aperture': 'f/2.8',
            'shutterspeed': '1/125',
            'whitebalance': 'Auto',
            'colortemperature': '5600',
            'picturestyle': 'Standard',
            'focusmode': 'One Shot',
            'imageformat': 'RAW + JPEG',
            'drivemode': 'Single',
            'exposurecompensation': '0'
        }
        
        self.cache.load_from_dict(self.default_values)
        self.matrix = MockParameterMatrix('Manual', 'Auto')
        
        # UI
        self._setup_ui()
        self._connect_signals()
        self._update_ui_state()
        self._update_status()
    
    def _setup_ui(self):
        """Buduje interfejs"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # ═══════════════════════════════════════════════════════
        # SHOOTING MODE SELECTOR (na górze!)
        # ═══════════════════════════════════════════════════════
        mode_group = QGroupBox("Shooting Mode")
        mode_layout = QHBoxLayout(mode_group)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['Manual', 'Av', 'Tv', 'P', 'Auto'])
        self.mode_combo.setCurrentText('Manual')
        mode_layout.addWidget(QLabel("Mode:"))
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        
        mode_info = QLabel("Change mode to see how parameters become available/locked")
        mode_info.setStyleSheet("color: #666; font-style: italic;")
        mode_layout.addWidget(mode_info)
        
        main_layout.addWidget(mode_group)
        
        # ═══════════════════════════════════════════════════════
        # EXPOSURE GROUP (suwaki)
        # ═══════════════════════════════════════════════════════
        exposure_group = QGroupBox("Exposure Triangle")
        exposure_layout = QVBoxLayout(exposure_group)
        exposure_layout.setSpacing(20)
        
        # ISO
        iso_values = ['100', '200', '400', '800', '1600', '3200', '6400', '12800']
        self.iso_slider = SliderWithScale("ISO", iso_values)
        self.iso_slider.set_value('800')
        exposure_layout.addWidget(self.iso_slider)
        
        # Aperture
        aperture_values = ['f/1.4', 'f/2', 'f/2.8', 'f/4', 'f/5.6', 'f/8', 'f/11', 'f/16']
        self.aperture_slider = SliderWithScale("Aperture", aperture_values)
        self.aperture_slider.set_value('f/2.8')
        exposure_layout.addWidget(self.aperture_slider)
        
        # Shutter Speed
        shutter_values = ['1/8000', '1/4000', '1/2000', '1/1000', '1/500', '1/250', '1/125', '1/60', '1/30']
        self.shutter_slider = SliderWithScale("Shutter Speed", shutter_values)
        self.shutter_slider.set_value('1/125')
        exposure_layout.addWidget(self.shutter_slider)
        
        # Exposure Compensation
        ev_values = ['-3', '-2', '-1', '0', '+1', '+2', '+3']
        self.ev_slider = SliderWithScale("Exposure Compensation", ev_values)
        self.ev_slider.set_value('0')
        exposure_layout.addWidget(self.ev_slider)
        
        main_layout.addWidget(exposure_group)
        
        # ═══════════════════════════════════════════════════════
        # IMAGE SETTINGS GROUP (combo boxy)
        # ═══════════════════════════════════════════════════════
        image_group = QGroupBox("Image Settings")
        image_grid = QGridLayout(image_group)
        image_grid.setSpacing(15)
        
        # White Balance
        wb_items = ['Auto', 'Daylight', 'Cloudy', 'Tungsten', 'Fluorescent', 'Flash', 'Manual']
        self.wb_combo = LabeledComboBox("White Balance", wb_items)
        self.wb_combo.setCurrentText('Auto')
        image_grid.addWidget(self.wb_combo, 0, 0)
        
        # Color Temperature (tylko gdy WB=Manual)
        ct_items = ['2800', '3200', '4000', '5000', '5600', '6500', '7500', '10000']
        self.ct_combo = LabeledComboBox("Color Temperature (K)", ct_items)
        self.ct_combo.setCurrentText('5600')
        image_grid.addWidget(self.ct_combo, 0, 1)
        
        # Picture Style
        ps_items = ['Standard', 'Portrait', 'Landscape', 'Neutral', 'Faithful', 'Monochrome']
        self.ps_combo = LabeledComboBox("Picture Style", ps_items)
        self.ps_combo.setCurrentText('Standard')
        image_grid.addWidget(self.ps_combo, 1, 0)
        
        # Image Format
        format_items = ['RAW', 'JPEG Large Fine', 'RAW + JPEG']
        self.format_combo = LabeledComboBox("Image Format", format_items)
        self.format_combo.setCurrentText('RAW + JPEG')
        image_grid.addWidget(self.format_combo, 1, 1)
        
        main_layout.addWidget(image_group)
        
        # ═══════════════════════════════════════════════════════
        # CAMERA SETTINGS GROUP
        # ═══════════════════════════════════════════════════════
        camera_group = QGroupBox("Camera Settings")
        camera_grid = QGridLayout(camera_group)
        camera_grid.setSpacing(15)
        
        # Focus Mode
        focus_items = ['One Shot', 'AI Servo', 'AI Focus', 'Manual']
        self.focus_combo = LabeledComboBox("Focus Mode", focus_items)
        self.focus_combo.setCurrentText('One Shot')
        camera_grid.addWidget(self.focus_combo, 0, 0)
        
        # Drive Mode
        drive_items = ['Single', 'Continuous L', 'Continuous H', 'Self-timer']
        self.drive_combo = LabeledComboBox("Drive Mode", drive_items)
        self.drive_combo.setCurrentText('Single')
        camera_grid.addWidget(self.drive_combo, 0, 1)
        
        main_layout.addWidget(camera_group)
        
        # ═══════════════════════════════════════════════════════
        # PRZYCISKI
        # ═══════════════════════════════════════════════════════
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        self.apply_btn = QPushButton("Apply Changes")
        self.apply_btn.setMinimumHeight(40)
        self.apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
        """)
        button_layout.addWidget(self.apply_btn)
        
        self.reset_btn = QPushButton("Reset to Saved")
        self.reset_btn.setMinimumHeight(40)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
        """)
        button_layout.addWidget(self.reset_btn)
        
        main_layout.addLayout(button_layout)
        
        # ═══════════════════════════════════════════════════════
        # STATUS BAR
        # ═══════════════════════════════════════════════════════
        self.status_label = QLabel()
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #E0E0E0;
                padding: 10px;
                border-radius: 4px;
                font-family: monospace;
            }
        """)
        main_layout.addWidget(self.status_label)
    
    def _connect_signals(self):
        """Łączy sygnały"""
        # Shooting mode
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        
        # Exposure sliders
        self.iso_slider.valueChanged.connect(lambda v: self._on_param_changed('iso', v))
        self.aperture_slider.valueChanged.connect(lambda v: self._on_param_changed('aperture', v))
        self.shutter_slider.valueChanged.connect(lambda v: self._on_param_changed('shutterspeed', v))
        self.ev_slider.valueChanged.connect(lambda v: self._on_param_changed('exposurecompensation', v))
        
        # Image settings
        self.wb_combo.currentTextChanged.connect(lambda v: self._on_param_changed('whitebalance', v))
        self.ct_combo.currentTextChanged.connect(lambda v: self._on_param_changed('colortemperature', v))
        self.ps_combo.currentTextChanged.connect(lambda v: self._on_param_changed('picturestyle', v))
        self.format_combo.currentTextChanged.connect(lambda v: self._on_param_changed('imageformat', v))
        
        # Camera settings
        self.focus_combo.currentTextChanged.connect(lambda v: self._on_param_changed('focusmode', v))
        self.drive_combo.currentTextChanged.connect(lambda v: self._on_param_changed('drivemode', v))
        
        # Buttons
        self.apply_btn.clicked.connect(self._on_apply)
        self.reset_btn.clicked.connect(self._on_reset)
    
    def _on_mode_changed(self, mode: str):
        """Zmiana trybu aparatu - aktualizuj dostępność kontrolek"""
        self.cache.set_parameter('shootingmode', mode)
        
        # Utwórz nową matrix
        wb = self.cache.get_parameter('whitebalance', 'Auto')
        self.matrix = MockParameterMatrix(mode, wb)
        
        # Aktualizuj UI
        self._update_ui_state()
        self._update_status()
    
    def _on_param_changed(self, param: str, value: str):
        """Zmiana parametru"""
        self.cache.set_parameter(param, value)
        
        # Jeśli zmiana WB - może się zmienić dostępność Color Temperature
        if param == 'whitebalance':
            mode = self.cache.get_parameter('shootingmode', 'Manual')
            self.matrix = MockParameterMatrix(mode, value)
            self._update_ui_state()
        
        self._update_status()
    
    def _update_ui_state(self):
        """Aktualizuje enable/disable kontrolek według matrix"""
        controls = {
            'iso': self.iso_slider,
            'aperture': self.aperture_slider,
            'shutterspeed': self.shutter_slider,
            'whitebalance': self.wb_combo,
            'colortemperature': self.ct_combo,
            'picturestyle': self.ps_combo,
            'focusmode': self.focus_combo,
            'imageformat': self.format_combo,
            'drivemode': self.drive_combo,
            'exposurecompensation': self.ev_slider,
        }
        
        for param, widget in controls.items():
            editable, reason = self.matrix.is_editable(param)
            widget.setEnabled(editable)
            
            if reason:
                widget.setToolTip(f"🔒 {reason}")
            else:
                widget.setToolTip("")
    
    def _update_status(self):
        """Aktualizuje status bar"""
        if self.cache.has_changes():
            changes = self.cache.get_bulk_update_dict()
            changes_str = ", ".join([f"{k}={v}" for k, v in changes.items()])
            self.status_label.setText(
                f"🔴 DIRTY - Changes: {changes_str}"
            )
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #FFEBEE;
                    color: #C62828;
                    padding: 10px;
                    border-radius: 4px;
                    font-family: monospace;
                    font-weight: bold;
                }
            """)
            self.apply_btn.setEnabled(True)
            self.reset_btn.setEnabled(True)
        else:
            self.status_label.setText("✅ CLEAN - No changes")
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #E8F5E9;
                    color: #2E7D32;
                    padding: 10px;
                    border-radius: 4px;
                    font-family: monospace;
                    font-weight: bold;
                }
            """)
            self.apply_btn.setEnabled(False)
            self.reset_btn.setEnabled(False)
    
    def _on_apply(self):
        """Apply changes - symulacja zapisu do aparatu"""
        changes = self.cache.get_bulk_update_dict()
        
        print("\n" + "="*60)
        print("📸 APPLYING TO CAMERA:")
        print("="*60)
        for param, value in changes.items():
            print(f"  {param:20s} → {value}")
        print("="*60)
        print("✅ Successfully applied!")
        print()
        
        # Commit cache (nowy baseline)
        self.cache.load_from_dict(self.cache._current)
        self._update_status()
    
    def _on_reset(self):
        """Reset changes - rollback do saved"""
        print("\n" + "="*60)
        print("🔄 ROLLING BACK CHANGES")
        print("="*60)
        
        self.cache.rollback()
        
        # Odśwież wszystkie kontrolki
        self.iso_slider.set_value(self.cache.get_parameter('iso'))
        self.aperture_slider.set_value(self.cache.get_parameter('aperture'))
        self.shutter_slider.set_value(self.cache.get_parameter('shutterspeed'))
        self.ev_slider.set_value(self.cache.get_parameter('exposurecompensation'))
        self.wb_combo.setCurrentText(self.cache.get_parameter('whitebalance'))
        self.ct_combo.setCurrentText(self.cache.get_parameter('colortemperature'))
        self.ps_combo.setCurrentText(self.cache.get_parameter('picturestyle'))
        self.format_combo.setCurrentText(self.cache.get_parameter('imageformat'))
        self.focus_combo.setCurrentText(self.cache.get_parameter('focusmode'))
        self.drive_combo.setCurrentText(self.cache.get_parameter('drivemode'))
        
        self._update_status()
        
        print("✅ Rolled back to saved state")
        print()


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Style aplikacji
    app.setStyle('Fusion')
    
    # Okno
    window = ExposureControlsDemo()
    window.show()
    
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Canon EOS RP - Full Parameters Demo                    ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print("📌 Instructions:")
    print("   1. Change Shooting Mode (M/Av/Tv/P/Auto)")
    print("   2. Move sliders and change combos")
    print("   3. Watch status bar (CLEAN/DIRTY)")
    print("   4. Click 'Apply' to see bulk update dict")
    print("   5. Click 'Reset' to rollback changes")
    print()
    print("🔍 Key features:")
    print("   • OFFSET = 7 for perfect slider alignment")
    print("   • ParameterCache tracks changes")
    print("   • ParameterMatrix controls enable/disable")
    print("   • Color Temperature only when WB=Manual")
    print("   • Shutter locked in Av mode")
    print("   • Aperture locked in Tv mode")
    print("   • Everything locked in Auto mode")
    print()
    
    sys.exit(app.exec())
