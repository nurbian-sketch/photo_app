#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Widget Demo - SliderWithScale & LabeledComboBox

Pokazuje możliwości widgetów z różnymi konfiguracjami.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLabel, QScrollArea, QCheckBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from ui.widgets.slider_with_scale import SliderWithScale
from ui.widgets.labeled_combo_box import LabeledComboBox


class WidgetDemo(QMainWindow):
    """Main demo window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Widget Demo - SliderWithScale & LabeledComboBox")
        self.setGeometry(0, 0, 1920, 1080)  # Full HD
        
        # Central widget with scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        content = QWidget()
        scroll.setWidget(content)
        self.setCentralWidget(scroll)
        
        # Main layout - centered with max width
        main_layout = QHBoxLayout(content)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Content container - max 1200px for 2 columns
        container = QWidget()
        container.setMaximumWidth(1200)
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(20)
        container_layout.setContentsMargins(20, 20, 20, 20)
        
        # ═══════════════════════════════════════════════════════════
        # HEADER
        # ═══════════════════════════════════════════════════════════
        header = QLabel("Camera Control Widgets Demo - FSM States")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        header.setFont(font)
        container_layout.addWidget(header)
        
        subtitle = QLabel("Watch how parameters enable/disable based on shooting mode")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(subtitle)
        
        # ═══════════════════════════════════════════════════════════
        # SHOOTING MODE & FLASH (FULL WIDTH)
        # ═══════════════════════════════════════════════════════════
        mode_group = QGroupBox("Shooting Mode & Flash")
        mode_layout = QHBoxLayout(mode_group)
        mode_layout.setSpacing(20)
        
        # Shooting Mode ComboBox
        mode_items = ['Manual', 'AV', 'TV', 'P']
        self.mode_combo = LabeledComboBox("Shooting Mode", mode_items)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        
        # Flash Checkbox (affects shutter speed range)
        flash_widget = QWidget()
        flash_layout = QVBoxLayout(flash_widget)
        flash_layout.setSpacing(4)
        flash_layout.setContentsMargins(0, 0, 0, 0)
        flash_label = QLabel("Flash Enabled")
        self.flash_checkbox = QCheckBox()
        self.flash_checkbox.stateChanged.connect(self._on_flash_changed)
        flash_layout.addWidget(flash_label)
        flash_layout.addWidget(self.flash_checkbox)
        flash_layout.addStretch()
        mode_layout.addWidget(flash_widget)
        
        container_layout.addWidget(mode_group)
        
        # ═══════════════════════════════════════════════════════════
        # TWO COLUMN LAYOUT
        # ═══════════════════════════════════════════════════════════
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(20)
        
        # LEFT COLUMN
        left_column = QWidget()
        left_column.setMaximumWidth(580)
        left_layout = QVBoxLayout(left_column)
        left_layout.setSpacing(20)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # RIGHT COLUMN  
        right_column = QWidget()
        right_column.setMaximumWidth(580)
        right_layout = QVBoxLayout(right_column)
        right_layout.setSpacing(20)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # ═══════════════════════════════════════════════════════════
        # LEFT COLUMN: EXPOSURE TRIANGLE
        # ═══════════════════════════════════════════════════════════
        exposure_group = QGroupBox("Exposure Triangle")
        self.exposure_layout = QVBoxLayout(exposure_group)
        self.exposure_layout.setSpacing(15)
        
        # ISO Slider (from JSON - max 800)
        iso_values = ['Auto', '100', '125', '160', '200', '250', '320', '400', '500', '640', '800']
        self.iso_slider = SliderWithScale("ISO", iso_values)
        self.iso_slider.valueChanged.connect(lambda v: self._on_value_changed("ISO", v))
        self.exposure_layout.addWidget(self.iso_slider)
        
        # Aperture Slider (from JSON)
        aperture_values = ['2.8', '3.2', '3.5', '4', '4.5', '5', '5.6', '6.3', '7.1', '8', '9', '10', '11', '13', '14', '16', '18', '20', '22']
        self.aperture_slider = SliderWithScale("Aperture (f-stop)", aperture_values)
        self.aperture_slider.valueChanged.connect(lambda v: self._on_value_changed("Aperture", v))
        self.exposure_layout.addWidget(self.aperture_slider)
        
        # Shutter Speed Slider (from JSON - APP constraints applied)
        self.shutter_values_no_flash = [
            '1/10', '1/13', '1/15', '1/20', '1/25', '1/30', '1/40', '1/50', '1/60',
            '1/80', '1/100', '1/125', '1/160', '1/200', '1/250', '1/320', '1/400',
            '1/500', '1/640', '1/800', '1/1000'
        ]
        self.shutter_values_with_flash = ['1/125', '1/160']
        
        self.shutter_slider = SliderWithScale("Shutter Speed", self.shutter_values_no_flash)
        self.shutter_slider.valueChanged.connect(lambda v: self._on_value_changed("Shutter", v))
        self.shutter_slider_index = self.exposure_layout.count()  # Remember position in layout
        self.exposure_layout.addWidget(self.shutter_slider)
        
        # Exposure Compensation Slider (from JSON - AV mode)
        ev_values = ['-3', '-2.6', '-2.3', '-2', '-1.6', '-1.3', '-1', '-0.6', '-0.3', '0', '0.3', '0.6', '1', '1.3', '1.6', '2', '2.3', '2.6', '3']
        self.ev_slider = SliderWithScale("Exposure Compensation (EV)", ev_values)
        self.ev_slider.valueChanged.connect(lambda v: self._on_value_changed("EV", v))
        self.exposure_layout.addWidget(self.ev_slider)
        
        left_layout.addWidget(exposure_group)
        
        # ═══════════════════════════════════════════════════════════
        # RIGHT COLUMN: IMAGE SETTINGS
        # ═══════════════════════════════════════════════════════════
        image_group = QGroupBox("Image Settings")
        image_layout = QVBoxLayout(image_group)
        image_layout.setSpacing(15)
        
        # White Balance ComboBox (from JSON)
        wb_items = ['Auto', 'AWB White', 'Daylight', 'Shadow', 'Cloudy', 'Tungsten', 'Fluorescent', 'Flash', 'Manual', 'Color Temperature']
        self.wb_combo = LabeledComboBox("White Balance", wb_items)
        self.wb_combo.currentTextChanged.connect(self._on_wb_changed)
        image_layout.addWidget(self.wb_combo)
        
        # Color Temperature Slider (visible only for Manual/Color Temperature WB)
        ct_values = [str(i) for i in range(2500, 10100, 100)]  # 2500-10000K
        self.ct_slider = SliderWithScale("Color Temperature (K)", ct_values)
        self.ct_slider.valueChanged.connect(lambda v: self._on_value_changed("Color Temp", v))
        self.ct_slider.setEnabled(False)  # Disabled by default
        image_layout.addWidget(self.ct_slider)
        
        # Picture Style ComboBox (from JSON)
        style_items = ['Auto', 'Standard', 'Portrait', 'Landscape', 'Fine detail', 'Neutral', 'Faithful', 'Monochrome', 'User defined 1', 'User defined 2', 'User defined 3']
        self.style_combo = LabeledComboBox("Picture Style", style_items)
        self.style_combo.currentTextChanged.connect(lambda v: self._on_value_changed("Picture Style", v))
        image_layout.addWidget(self.style_combo)
        
        # Image Format ComboBox (APP constraints - 3 options)
        format_items = ['RAW', 'Large Fine JPEG', 'RAW + Large Fine JPEG']
        self.format_combo = LabeledComboBox("Image Format", format_items)
        self.format_combo.currentTextChanged.connect(lambda v: self._on_value_changed("Image Format", v))
        image_layout.addWidget(self.format_combo)
        
        # ALO Mode ComboBox (from JSON)
        alo_items = ['Standard (disabled in manual exposure)', 'x1', 'x2', 'x3']
        self.alo_combo = LabeledComboBox("Auto Lighting Optimizer", alo_items)
        self.alo_combo.currentTextChanged.connect(lambda v: self._on_value_changed("ALO Mode", v))
        image_layout.addWidget(self.alo_combo)
        
        right_layout.addWidget(image_group)
        
        # ═══════════════════════════════════════════════════════════
        # AUTOFOCUS
        # ═══════════════════════════════════════════════════════════
        af_group = QGroupBox("Autofocus & Drive")
        af_layout = QVBoxLayout(af_group)
        af_layout.setSpacing(15)
        
        # AF Method ComboBox (from JSON)
        af_items = ['LiveFace', 'LiveSpotAF', 'Live', 'LiveSingleExpandCross', 'LiveSingleExpandSurround', 'LiveZone']
        self.af_combo = LabeledComboBox("AF Method", af_items)
        self.af_combo.currentTextChanged.connect(lambda v: self._on_value_changed("AF Method", v))
        af_layout.addWidget(self.af_combo)
        
        # Continuous AF ComboBox
        caf_items = ['Off', 'On']
        self.caf_combo = LabeledComboBox("Continuous AF", caf_items)
        self.caf_combo.currentTextChanged.connect(lambda v: self._on_value_changed("Continuous AF", v))
        af_layout.addWidget(self.caf_combo)
        
        # Drive Mode ComboBox (from JSON)
        drive_items = ['Single', 'Continuous high speed', 'Continuous low speed', 'Timer 10 sec', 'Timer 2 sec', 'Continuous timer']
        self.drive_combo = LabeledComboBox("Drive Mode", drive_items)
        self.drive_combo.currentTextChanged.connect(lambda v: self._on_value_changed("Drive Mode", v))
        af_layout.addWidget(self.drive_combo)
        
        right_layout.addWidget(af_group)
        
        # ═══════════════════════════════════════════════════════════
        # FINISH TWO COLUMN LAYOUT
        # ═══════════════════════════════════════════════════════════
        columns_layout.addWidget(left_column)
        columns_layout.addWidget(right_column)
        container_layout.addLayout(columns_layout)
        
        # ═══════════════════════════════════════════════════════════
        # FSM RULES INFO
        # ═══════════════════════════════════════════════════════════
        fsm_info = QLabel(
            "FSM Rules:\n"
            "• Manual: ISO ✓, Aperture ✓, Shutter ✓, EV ✗\n"
            "• AV (Aperture Priority): ISO ✓, Aperture ✓, Shutter ✗, EV ✓\n"
            "• TV (Shutter Priority): ISO ✓, Aperture ✗, Shutter ✓, EV ✓\n"
            "• P (Program): ISO ✓, Aperture ✗, Shutter ✗, EV ✓"
        )
        container_layout.addWidget(fsm_info)
        
        # ═══════════════════════════════════════════════════════════
        # STATUS LABEL
        # ═══════════════════════════════════════════════════════════
        self.status_label = QLabel("Change any value to see updates here")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self.status_label)
        
        # Spacer
        container_layout.addStretch()
        
        # Add container to main layout
        main_layout.addWidget(container)
        
        # Set initial values
        self.mode_combo.setCurrentText('Manual')
        self.flash_checkbox.setChecked(False)
        self.iso_slider.set_value('800')
        self.aperture_slider.set_value('2.8')
        self.shutter_slider.set_value('1/30')
        self.ev_slider.set_value('0')
        self.wb_combo.setCurrentText('Color Temperature')
        self.ct_slider.set_value('5500')  # 5500K
        self.style_combo.setCurrentText('Landscape')
        self.format_combo.setCurrentText('Large Fine JPEG')
        self.af_combo.setCurrentText('LiveFace')
        self.caf_combo.setCurrentText('On')
        self.drive_combo.setCurrentText('Timer 2 sec')
        self.alo_combo.setCurrentText('Standard (disabled in manual exposure)')
        
        # Initial FSM update
        self._update_fsm_state()
    
    def _on_wb_changed(self, wb_mode: str):
        """Handle white balance change - enable/disable color temp slider"""
        # Enable CT slider only for Manual or Color Temperature
        enable_ct = wb_mode in ['Manual', 'Color Temperature']
        self.ct_slider.setEnabled(enable_ct)
        
        self._on_value_changed("White Balance", wb_mode)
    
    def _on_mode_changed(self, mode: str):
        """Handle shooting mode change - update FSM"""
        self._update_fsm_state()
        self.status_label.setText(f"✓ Shooting Mode changed to: {mode}")
    
    def _on_flash_changed(self, state):
        """Handle flash checkbox change - rebuild shutter slider with new range"""
        flash_enabled = self.flash_checkbox.isChecked()
        
        # Select appropriate shutter values
        if flash_enabled:
            new_values = self.shutter_values_with_flash
            range_text = "1/125 - 1/160 (flash sync)"
        else:
            new_values = self.shutter_values_no_flash
            range_text = "1/10 - 1/1000"
        
        # Remember current value
        old_value = self.shutter_slider.get_value()
        
        # Remove old slider
        self.exposure_layout.removeWidget(self.shutter_slider)
        self.shutter_slider.deleteLater()
        
        # Create new slider with new range
        self.shutter_slider = SliderWithScale("Shutter Speed", new_values)
        self.shutter_slider.valueChanged.connect(lambda v: self._on_value_changed("Shutter", v))
        
        # Try to restore old value if possible, otherwise use middle value
        if old_value in new_values:
            self.shutter_slider.set_value(old_value)
        else:
            middle_idx = len(new_values) // 2
            self.shutter_slider.set_value(new_values[middle_idx])
        
        # Insert at remembered position
        self.exposure_layout.insertWidget(self.shutter_slider_index, self.shutter_slider)
        
        # Update status
        flash_status = "Enabled" if flash_enabled else "Disabled"
        self.status_label.setText(f"✓ Flash {flash_status} - Shutter range: {range_text}")
    
    def _update_fsm_state(self):
        """Update widget enabled state based on FSM logic"""
        mode = self.mode_combo.currentText()
        
        # FSM Logic from ParameterMatrix
        # ISO - always editable
        self.iso_slider.setEnabled(True)
        
        # Aperture - editable in Manual and AV
        aperture_enabled = mode in ['Manual', 'AV']
        self.aperture_slider.setEnabled(aperture_enabled)
        
        # Shutter Speed - editable in Manual and TV
        shutter_enabled = mode in ['Manual', 'TV']
        self.shutter_slider.setEnabled(shutter_enabled)
        
        # EV Compensation - editable in AV, TV, P (not Manual)
        ev_enabled = mode in ['AV', 'TV', 'P']
        self.ev_slider.setEnabled(ev_enabled)
        
        # Image settings - always editable
        self.wb_combo.setEnabled(True)
        self.style_combo.setEnabled(True)
        self.format_combo.setEnabled(True)
        self.af_combo.setEnabled(True)
        self.caf_combo.setEnabled(True)
        self.drive_combo.setEnabled(True)
    
    def _on_value_changed(self, parameter: str, value: str):
        """Handle value changes from any widget"""
        self.status_label.setText(f"✓ {parameter} changed to: {value}")


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    
    # Fix slider colors - gray instead of blue
    app.setStyleSheet("""
        QSlider::sub-page:horizontal {
            background: #b0b0b0;  /* jasno szary dla aktywnego */
        }
        QSlider::sub-page:horizontal:disabled {
            background: #505050;  /* ciemny szary dla nieaktywnego */
        }
    """)
    
    window = WidgetDemo()
    window.show()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
