"""
DevelopDialog — dialog wyboru ustawień wywołania RAW.
Wywoływany po zakończeniu sesji gdy w katalogu sesji są pliki RAW.
"""
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QRadioButton,
    QButtonGroup, QComboBox,
)

from ui.styles import (
    DIALOG_SPACING, DIALOG_MARGINS, DIALOG_MIN_WIDTH,
    DIALOG_BTN_H, DIALOG_BTN_W,
    center_on_parent,
)

# Stała kolejność presetów — niezależna od sortowania plików
PRESET_ORDER = [
    "black_bg_greyscale",
    "black_bg_color_natural",
    "black_bg_color_fashion",
    "grey_bg_greyscale",
    "grey_bg_color_natural",
    "grey_bg_color_fashion",
    "white_bg_greyscale",
    "white_bg_color_natural",
    "white_bg_color_fashion",
]

_AUTO_PRESET = "__auto__"

# Etykiety wyświetlane w combo
_PRESET_LABELS = {
    "black_bg_greyscale":       "Black BG — Greyscale",
    "black_bg_color_natural":   "Black BG — Color (natural)",
    "black_bg_color_fashion":   "Black BG — Color (fashion)",
    "grey_bg_greyscale":        "Grey BG — Greyscale",
    "grey_bg_color_natural":    "Grey BG — Color (natural)",
    "grey_bg_color_fashion":    "Grey BG — Color (fashion)",
    "white_bg_greyscale":       "White BG — Greyscale",
    "white_bg_color_natural":   "White BG — Color (natural)",
    "white_bg_color_fashion":   "White BG — Color (fashion)",
    _AUTO_PRESET:               "Auto (darktable defaults)",
}


def _collect_presets(presets_dir: Path) -> list[str]:
    """Zwraca presety w ustalonej kolejności + presety użytkownika + __auto__ na końcu."""
    names = [n for n in PRESET_ORDER if (presets_dir / f"{n}.xmp").exists()]
    # Presety użytkownika z podkatalogu
    user_dir = presets_dir / "user"
    if user_dir.is_dir():
        for p in sorted(user_dir.glob("*.xmp")):
            names.append(p.stem)
    names.append(_AUTO_PRESET)
    return names


class DevelopDialog(QDialog):
    """
    Dialog wywołania RAW.

    Zwraca po accept():
        selected_preset — nazwa presetu (str) lub "__auto__"
        selected_kelvin — int (0=EXIF) lub None (z presetu)
    """

    def __init__(self, session_path: str, presets_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Develop RAW files?"))
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setModal(True)

        self._presets_dir = presets_dir
        self._settings    = QSettings("Grzeza", "SessionsAssistant")

        # Wyniki wyboru
        self.selected_preset: str        = PRESET_ORDER[0]
        self.selected_kelvin: int | None = 0

        self._build_ui()
        self._restore_settings()

    def showEvent(self, event):
        super().showEvent(event)
        center_on_parent(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(DIALOG_SPACING)
        layout.setContentsMargins(*DIALOG_MARGINS)

        # --- Nagłówek WB ---
        layout.addWidget(QLabel(self.tr("White balance:")))

        # Radio: From camera (EXIF)
        self._rb_exif = QRadioButton(self.tr("From camera (EXIF)"))
        self._rb_exif.setChecked(True)
        layout.addWidget(self._rb_exif)

        # Radio: From preset
        self._rb_preset = QRadioButton(self.tr("From preset"))
        layout.addWidget(self._rb_preset)

        # Grupa — wzajemne wykluczenie
        self._wb_group = QButtonGroup(self)
        self._wb_group.addButton(self._rb_exif,   0)
        self._wb_group.addButton(self._rb_preset, 1)

        layout.addSpacing(4)

        # --- Wybór presetu ---
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel(self.tr("Preset:")))

        self._combo = QComboBox()
        for name in _collect_presets(self._presets_dir):
            label = _PRESET_LABELS.get(name, name)
            self._combo.addItem(label, name)
        preset_row.addWidget(self._combo, stretch=1)

        layout.addLayout(preset_row)

        layout.addSpacing(8)

        # --- Przyciski ---
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        btn_develop = QPushButton(self.tr("Develop"))
        btn_develop.setFixedHeight(DIALOG_BTN_H)
        btn_develop.setFixedWidth(DIALOG_BTN_W)
        btn_develop.setDefault(True)
        btn_develop.setAutoDefault(True)
        btn_develop.clicked.connect(self._on_develop)
        btn_row.addWidget(btn_develop)

        btn_row.addSpacing(8)

        btn_skip = QPushButton(self.tr("Skip"))
        btn_skip.setFixedHeight(DIALOG_BTN_H)
        btn_skip.setFixedWidth(DIALOG_BTN_W)
        btn_skip.setDefault(False)
        btn_skip.setAutoDefault(False)
        btn_skip.clicked.connect(self.reject)
        btn_row.addWidget(btn_skip)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _restore_settings(self):
        """Przywraca ostatni wybór z QSettings."""
        wb_source = self._settings.value("developer/last_wb_source", "exif")
        if wb_source == "preset":
            self._rb_preset.setChecked(True)
        else:
            self._rb_exif.setChecked(True)

        last_preset = self._settings.value("developer/last_preset", "")
        if last_preset:
            for i in range(self._combo.count()):
                if self._combo.itemData(i) == last_preset:
                    self._combo.setCurrentIndex(i)
                    break

    def _on_develop(self):
        """Zatwierdza wybór, zapisuje ustawienia."""
        self.selected_preset = self._combo.currentData()
        if self._rb_exif.isChecked():
            self.selected_kelvin = 0
            wb_source = "exif"
        else:
            self.selected_kelvin = None
            wb_source = "preset"

        # Zapamiętaj wybór
        self._settings.setValue("developer/last_wb_source", wb_source)
        self._settings.setValue("developer/last_preset", self.selected_preset)

        self.accept()
