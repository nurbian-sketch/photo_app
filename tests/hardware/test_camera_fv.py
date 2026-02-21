import sys
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QPushButton, QGroupBox, QScrollArea, QFrame, 
    QCheckBox, QFileDialog, QSplitter
)
from PyQt6.QtCore import Qt

# Automatyczne wykrywanie ścieżki projektu
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from ui.widgets.slider_with_scale import SliderWithScale
from ui.widgets.labeled_combo_box import LabeledComboBox

class CameraViewFv(QWidget):
    def __init__(self, camera_service=None):
        super().__init__()
        self.cs = camera_service
        self.controls = {}
        
        # --- KONFIGURACJA EOS RP ---
        self.shutter_all = [
            '1/4', '1/5', '1/6', '1/8', '1/10', '1/13', '1/15', '1/20', '1/25', '1/30', 
            '1/40', '1/50', '1/60', '1/80', '1/100', '1/125', '1/160', '1/200', 
            '1/250', '1/320', '1/400', '1/500', '1/640', '1/800', '1/1000'
        ]
        self.shutter_flash = ['1/30', '1/40', '1/50', '1/60', '1/80', '1/100', '1/125', '1/160']
        self.iso_values = ['Auto', '100', '200', '400', '800', '1600']
        
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        
        # Używamy QSplitter do dynamicznej zmiany proporcji
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # --- LEWA STRONA: PANEL STEROWANIA ---
        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        scroll_inner_layout = QHBoxLayout(scroll_content)

        # [KOLUMNA 1: EKSPOZYCJA Fv]
        left_col = QVBoxLayout()
        exp_group = QGroupBox("Exposure (Fv)")
        exp_lay = QVBoxLayout(exp_group)
        
        fv_configs = [
            ("Shutter Speed", "shutterspeed", self.shutter_all),
            ("Aperture", "aperture", ['2.8', '4', '5.6', '8', '11', '16', '22']),
            ("ISO Speed", "iso", self.iso_values),
            ("Exp. Compensation", "exposurecompensation", ['-3', '-2', '-1', '0', '+1', '+2', '+3'])
        ]

        for label, key, values in fv_configs:
            row = QHBoxLayout()
            btn_auto = QPushButton("AUTO")
            btn_auto.setCheckable(True)
            btn_auto.setFixedSize(65, 45)
            slider = SliderWithScale(label, values)
            btn_auto.toggled.connect(lambda checked, s=slider: s.setEnabled(not checked))
            btn_auto.setChecked(True)
            row.addWidget(btn_auto)
            row.addWidget(slider)
            exp_lay.addLayout(row)
            self.controls[key] = {"slider": slider, "auto": btn_auto}
        
        left_col.addWidget(exp_group)
        left_col.addStretch()

        # [KOLUMNA 2: OBRAZ I AF]
        mid_col = QVBoxLayout()
        img_group = QGroupBox("Image & Quality")
        img_lay = QVBoxLayout(img_group)
        self.quality_combo = LabeledComboBox("Quality", ['RAW', 'Large Fine JPG', 'Medium Fine JPG', 'Small Fine JPG'])
        self.wb_combo = LabeledComboBox("WB", ['Auto', 'Daylight', 'Cloudy', 'Flash', 'Color Temperature'])
        self.ct_slider = SliderWithScale("Color Temp (K)", [str(i) for i in range(2500, 10100, 100)])
        self.ct_slider.setEnabled(False)
        self.alo_combo = LabeledComboBox("ALO", ['Off', 'Low', 'Standard', 'High'])
        self.meter_combo = LabeledComboBox("Metering", ['Evaluative', 'Partial', 'Spot', 'Center-weighted'])
        
        for w in [self.quality_combo, self.wb_combo, self.ct_slider, self.alo_combo, self.meter_combo]:
            img_lay.addWidget(w)
        mid_col.addWidget(img_group)

        af_group = QGroupBox("Focus Settings")
        af_lay = QVBoxLayout(af_group)
        self.af_method = LabeledComboBox("AF Method", [
            'LiveFace', 'LiveSpotAF', 'Live', 'LiveSingleExpandCross', 
            'LiveSingleExpandSurround', 'LiveZone'
        ])
        self.focus_mode = LabeledComboBox("Focus Mode", ['One Shot', 'AI Servo'])
        self.cont_af = LabeledComboBox("Continuous AF", ['On', 'Off'])
        self.cont_af.setCurrentText('Off')
        
        for w in [self.af_method, self.focus_mode, self.cont_af]:
            af_lay.addWidget(w)
        mid_col.addWidget(af_group)
        mid_col.addStretch()

        scroll_inner_layout.addLayout(left_col, 1)
        scroll_inner_layout.addLayout(mid_col, 1)
        scroll.setWidget(scroll_content)
        ctrl_layout.addWidget(scroll)

        # [PANEL SYSTEMOWY]
        sys_group = QGroupBox("System Actions")
        sys_lay = QHBoxLayout(sys_group)
        self.btn_update = QPushButton("UPDATE PARAMETERS")
        self.btn_update.setStyleSheet("background-color: #2e7d32; font-weight: bold; height: 45px;")
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setStyleSheet("background-color: #c62828; height: 45px;")
        self.btn_save = QPushButton("Save Settings")
        self.btn_load = QPushButton("Load Settings")
        
        for b in [self.btn_update, self.btn_cancel, self.btn_save, self.btn_load]:
            sys_lay.addWidget(b)
        ctrl_layout.addWidget(sys_group)

        # --- PRAWA STRONA: PREVIEW PANEL ---
        view_widget = QWidget()
        view_layout = QVBoxLayout(view_widget)
        view_layout.setContentsMargins(0, 0, 0, 0)
        
        view_group = QGroupBox("Camera Preview")
        view_inner_lay = QVBoxLayout(view_group)
        
        self.lv_screen = QLabel("LIVE VIEW OFF")
        self.lv_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lv_screen.setStyleSheet("background: #000; border: 2px solid #444;")
        
        self.btn_lv_toggle = QPushButton("START LIVE VIEW")
        self.btn_lv_toggle.setFixedHeight(40)
        
        self.flash_check = QCheckBox("Flash Sync Active (1/30 - 1/160)")
        self.flash_check.stateChanged.connect(self._on_flash_changed)

        self.btn_test_shot = QPushButton("TEST SHOT (CAPTURE)")
        self.btn_test_shot.setStyleSheet("background-color: #1565c0; height: 60px; font-weight: bold;")
        
        view_inner_lay.addWidget(self.lv_screen, 1)
        view_inner_lay.addWidget(self.btn_lv_toggle)
        view_inner_lay.addWidget(self.flash_check)
        view_inner_lay.addWidget(self.btn_test_shot)
        view_layout.addWidget(view_group)

        # Dodanie paneli do splittera
        self.splitter.addWidget(ctrl_widget)
        self.splitter.addWidget(view_widget)
        
        # Ustawienie początkowych proporcji (np. 65% lewa, 35% prawa)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(self.splitter)

        # --- SYGNAŁY ---
        self.wb_combo.currentTextChanged.connect(self._on_wb_changed)
        self.btn_save.clicked.connect(self.save_settings)
        self.btn_load.clicked.connect(self.load_settings)

    def _on_flash_changed(self, state):
        active = (state == 2)
        new_v = self.shutter_flash if active else self.shutter_all
        s = self.controls["shutterspeed"]["slider"]
        s.values = new_v
        s.slider.setRange(0, len(new_v)-1)
        if active:
            try: s.slider.setValue(new_v.index('1/125'))
            except: s.slider.setValue(0)
        s._update_labels()

    def _on_wb_changed(self, val):
        self.ct_slider.setEnabled(val == "Color Temperature")

    def save_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Profile", "", "JSON Files (*.json)")
        if path:
            data = {
                "exposure": {k: v["slider"].slider.value() for k, v in self.controls.items()},
                "auto": {k: v["auto"].isChecked() for k, v in self.controls.items()}
            }
            with open(path, 'w') as f: json.dump(data, f)

    def load_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Profile", "", "JSON Files (*.json)")
        if path:
            with open(path, 'r') as f:
                data = json.load(f)
                for k, v in data.get("exposure", {}).items():
                    if k in self.controls:
                        self.controls[k]["auto"].setChecked(data.get("auto", {}).get(k, True))
                        self.controls[k]["slider"].slider.setValue(v)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = CameraViewFv()
    win.resize(1400, 900)
    win.show()
    sys.exit(app.exec())