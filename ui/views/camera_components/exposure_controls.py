from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QCheckBox, QSizePolicy, QSpacerItem
from PyQt6.QtCore import QTimer, QSettings
from ui.widgets.slider_with_scale import SliderWithScale

class ExposureControls(QWidget):
    # Stała skala exp comp dla Canon EOS RP (tryb Fv, 1/3 EV)
    EXP_COMP_SCALE = [
        '-3', '-2.6', '-2.3', '-2', '-1.6', '-1.3', '-1',
        '-0.6', '-0.3', '0',
        '0.3', '0.6', '1', '1.3', '1.6', '2',
        '2.3', '2.6', '3'
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.controls = {}
        self.gphoto = None 
        self.shutter_all = [] 
        self.shutter_flash = ['1/30', '1/40', '1/50', '1/60', '1/80', '1/100', '1/125', '1/160']
        self._pending_commands = {}  # key -> value (ostatnia wartość)
        self._throttle_timer = QTimer()
        self._throttle_timer.setSingleShot(True)
        self._throttle_timer.setInterval(150)  # 150ms debounce
        self._throttle_timer.timeout.connect(self._flush_pending)
        self._settings = QSettings("Grzeza", "SessionsAssistant")
        self._init_ui()
        self._restore_state()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        group = QGroupBox("Exposure (Fv)")
        grid = QVBoxLayout(group)

        self.flash_check = QCheckBox("Flash Sync Mode (1/30 - 1/160)")
        grid.addWidget(self.flash_check)

        configs = [
            ("shutterspeed", "Shutter Speed", True),
            ("aperture", "Aperture", True),
            ("iso", "ISO Speed", True),
            ("exposurecompensation", "Exp. Comp.", False)
        ]

        for key, label, has_auto in configs:
            grid.addStretch(1)
            row = QHBoxLayout()
            
            if has_auto:
                btn_auto = QPushButton("AUTO")
                btn_auto.setFixedSize(65, 45)
                btn_auto.setCheckable(True)
                btn_auto.setStyleSheet(
                    "QPushButton:checked { background-color: #2e7d32; color: white; font-weight: bold; }"
                    "QPushButton:disabled { background-color: #3a3a3a; color: #666; border: 1px solid #444; }"
                    "QPushButton:checked:disabled { background-color: #3a3a3a; color: #666; border: 1px solid #444; }"
                )
                btn_auto.clicked.connect(lambda _, k=key: self._handle_auto_press(k))
                row.addWidget(btn_auto)
                self.controls[key] = {"slider": None, "auto": btn_auto}
            else:
                row.addSpacerItem(QSpacerItem(72, 45, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum))
                self.controls[key] = {"slider": None, "auto": None}

            slider = SliderWithScale(label, ["Auto"])
            slider.valueChanged.connect(lambda val, k=key: self._on_slider_moved(k, val))
            row.addWidget(slider)
            self.controls[key]["slider"] = slider
            grid.addLayout(row)

        layout.addWidget(group, 1)
        self.flash_check.toggled.connect(self._on_flash_toggled)

    # ─────────────────────────────── EXP COMP LOCK

    def _is_all_manual(self) -> bool:
        """True gdy shutter, aperture i ISO sa wszystkie NIE-Auto."""
        for key in ('shutterspeed', 'aperture', 'iso'):
            if key in self.controls:
                val = self.controls[key]["slider"].get_value()
                if val == "Auto" or val == "":
                    return False
        return True

    def _update_exp_comp_lock(self):
        """Blokuje/odblokowuje suwak exp comp na podstawie stanu Auto."""
        ctrl = self.controls.get("exposurecompensation")
        if not ctrl:
            return
        locked = self._is_all_manual()
        slider = ctrl["slider"]
        if locked:
            slider.setLocked(True)
        else:
            # Odblokowany — upewnij się że ma pełną skalę
            if len(slider.values) <= 1:
                slider.update_values(self.EXP_COMP_SCALE)
                slider.set_value('0')
            slider.setLocked(False)

    # ─────────────────────────────── HANDLERS

    def _handle_auto_press(self, key):
        ctrl = self.controls[key]
        ctrl["auto"].blockSignals(True)
        ctrl["auto"].setChecked(True)
        ctrl["auto"].blockSignals(False)
        ctrl["slider"].set_value("Auto")
        if self.gphoto:
            self.gphoto.update_camera_param(key, "Auto")
        self._update_exp_comp_lock()
        self._save_state()

    def _on_slider_moved(self, key, value):
        if self.controls[key]["auto"]:
            self._update_auto_visuals(key, value == "Auto")
        # Zapamiętaj ostatnią wartość — wyślij po 150ms ciszy
        self._pending_commands[key] = value
        self._throttle_timer.start()  # restart timer
        if key in ('shutterspeed', 'aperture', 'iso'):
            self._update_exp_comp_lock()

    def _flush_pending(self):
        """Wysyła tylko ostatnią wartość każdego parametru."""
        if not self.gphoto:
            self._pending_commands.clear()
            return
        for key, value in self._pending_commands.items():
            self.gphoto.update_camera_param(key, value)
        self._pending_commands.clear()
        self._save_state()

    def _update_auto_visuals(self, key, is_auto):
        btn = self.controls[key]["auto"]
        if btn:
            btn.blockSignals(True)
            btn.setChecked(is_auto)
            btn.blockSignals(False)

    def sync_with_camera(self, settings):
        if not settings: return
        
        for key, data in settings.items():
            if key in self.controls:
                ctrl = self.controls[key]
                new_choices = data.get("choices", [])
                
                if not new_choices: 
                    continue 

                # Exp comp: aparat zwraca choices=['0'], ignorujemy — 
                # skala zarządzana przez UI (EXP_COMP_SCALE)
                if key == "exposurecompensation":
                    continue
                
                if key == "shutterspeed":
                    self.shutter_all = new_choices
                    if self.flash_check.isChecked():
                        new_choices = [c for c in new_choices if c in self.shutter_flash or c == 'Auto']
                
                ctrl["slider"].update_values(new_choices)
                ctrl["slider"].set_value(data["current"])
                if ctrl["auto"]:
                    self._update_auto_visuals(key, data["current"] == "Auto")

        # Po sync sprawdź stan blokady exp comp
        self._update_exp_comp_lock()
        self._save_state()

    def _on_flash_toggled(self, checked):
        if "shutterspeed" not in self.controls:
            return
        ctrl = self.controls["shutterspeed"]
        if not self.shutter_all:
            return
        current_val = ctrl["slider"].get_value()
        new_choices = [c for c in self.shutter_all if c in self.shutter_flash or c == 'Auto'] if checked else self.shutter_all
        if not new_choices:
            return
        ctrl["slider"].update_values(new_choices)
        val_to_set = current_val if current_val in new_choices else "Auto"
        ctrl["slider"].set_value(val_to_set)

    # ─────────────────────────────── PERSISTENCE

    def _save_state(self):
        """Zapisuje aktualny stan suwaków do QSettings."""
        for key, ctrl in self.controls.items():
            slider = ctrl["slider"]
            self._settings.setValue(f"exposure/{key}/choices", slider.values)
            self._settings.setValue(f"exposure/{key}/value", slider.get_value())

    def _restore_state(self):
        """Przywraca ostatni zapisany stan suwaków (wyłącznie wizualnie)."""
        for key, ctrl in self.controls.items():
            choices = self._settings.value(f"exposure/{key}/choices")
            value = self._settings.value(f"exposure/{key}/value")
            if choices and len(choices) > 1:
                slider = ctrl["slider"]
                slider.update_values(choices)
                if value and value in choices:
                    slider.set_value(value)
                if ctrl["auto"]:
                    self._update_auto_visuals(key, value == "Auto")
        self._update_exp_comp_lock()
