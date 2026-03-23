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

# Rozszerzenia plików presetów
_PRESET_EXT = ".xmp"


def _collect_presets(presets_dir: Path) -> list[str]:
    """
    Zwraca listę nazw presetów (bez .xmp) z presets/ i presets/user/.
    User presety pojawiają się na końcu.
    """
    names: list[str] = []
    # Bazowe presety (read-only)
    for p in sorted(presets_dir.glob(f"*{_PRESET_EXT}")):
        names.append(p.stem)
    # Presety użytkownika
    user_dir = presets_dir / "user"
    if user_dir.is_dir():
        for p in sorted(user_dir.glob(f"*{_PRESET_EXT}")):
            names.append(p.stem)
    return names


class DevelopDialog(QDialog):
    """
    Dialog wywołania RAW.

    Zwraca po accept():
        preset  — nazwa presetu (str)
        kelvin  — int (0=EXIF) lub None (z presetu)
    """

    def __init__(self, session_path: str, presets_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Develop RAW files?"))
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setModal(True)

        self._presets_dir = presets_dir
        self._settings    = QSettings("Grzeza", "SessionsAssistant")

        # Wyniki wyboru
        self.selected_preset: str       = "white_bg"
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
        names = _collect_presets(self._presets_dir)
        self._combo.addItems(names if names else ["white_bg"])
        preset_row.addWidget(self._combo, stretch=1)

        layout.addLayout(preset_row)

        layout.addSpacing(8)

        # --- Przyciski ---
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        btn_develop = QPushButton(self.tr("Develop"))
        btn_develop.setFixedHeight(DIALOG_BTN_H)
        btn_develop.setMinimumWidth(DIALOG_BTN_W)
        btn_develop.setDefault(True)
        btn_develop.clicked.connect(self._on_develop)
        btn_row.addWidget(btn_develop)

        btn_row.addSpacing(8)

        btn_skip = QPushButton(self.tr("Skip"))
        btn_skip.setFixedHeight(DIALOG_BTN_H)
        btn_skip.setMinimumWidth(DIALOG_BTN_W)
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
            idx = self._combo.findText(last_preset)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)

    def _on_develop(self):
        """Zatwierdza wybór, zapisuje ustawienia."""
        # Odczyt wartości
        self.selected_preset = self._combo.currentText()
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
