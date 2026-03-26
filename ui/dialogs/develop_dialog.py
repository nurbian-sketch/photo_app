"""
DevelopDialog — dialog wyboru ustawień wywołania RAW.
Wywoływany po zakończeniu sesji gdy w katalogu sesji są pliki RAW.
"""
from pathlib import Path

import shutil

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QRadioButton,
    QButtonGroup, QComboBox, QWidget,
    QLineEdit, QFileDialog, QTextEdit, QDialogButtonBox, QMessageBox,
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
        selected_preset — nazwa presetu (str), ścieżka absolutna XMP lub "__auto__"
        selected_kelvin — 0 (EXIF) | int>0 (Kelvin) | None (z presetu XMP)
    """

    def __init__(self, session_path: str, presets_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Develop RAW files?"))
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setModal(True)

        self._presets_dir  = presets_dir
        self._session_path = session_path
        self._settings     = QSettings("Grzeza", "SessionsAssistant")

        # Wyniki wyboru (odczytywane przez caller po accept())
        self.selected_preset:   str        = _AUTO_PRESET
        self.selected_kelvin:   int | None = 0

        # Stan wewnętrzny
        self._loaded_xmp_path: Path | None = None

        self._build_ui()
        self._restore_settings()

    def showEvent(self, event):
        super().showEvent(event)
        center_on_parent(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(DIALOG_SPACING)
        layout.setContentsMargins(*DIALOG_MARGINS)

        # ── Sekcja 1: Preset ─────────────────────────────────────────────────
        layout.addWidget(QLabel(self.tr("Preset:")))

        self._rb_no_preset = QRadioButton(self.tr("No preset"))
        self._rb_no_preset.setChecked(True)
        layout.addWidget(self._rb_no_preset)

        # "Use preset" + combo w jednym wierszu
        use_row = QHBoxLayout()
        self._rb_use_preset = QRadioButton(self.tr("Use preset:"))
        use_row.addWidget(self._rb_use_preset)
        self._combo = QComboBox()
        for name in _collect_presets(self._presets_dir):
            label = _PRESET_LABELS.get(name, name)
            self._combo.addItem(label, name)
        self._combo.setEnabled(False)
        use_row.addWidget(self._combo, stretch=1)
        layout.addLayout(use_row)

        # "Load preset" + etykieta pliku w jednym wierszu
        load_row = QHBoxLayout()
        self._rb_load_preset = QRadioButton(self.tr("Load preset…"))
        load_row.addWidget(self._rb_load_preset)
        self._btn_browse = QPushButton(self.tr("Browse…"))
        self._btn_browse.setFixedHeight(DIALOG_BTN_H)
        self._btn_browse.setEnabled(False)
        self._btn_browse.clicked.connect(self._on_load_preset)
        load_row.addWidget(self._btn_browse)
        self._load_path_label = QLabel(self.tr("No file selected"))
        self._load_path_label.setStyleSheet("color: #888; font-size: 11px;")
        load_row.addWidget(self._load_path_label, stretch=1)
        layout.addLayout(load_row)

        # Grupa preset — wzajemne wykluczenie
        self._preset_group = QButtonGroup(self)
        self._preset_group.addButton(self._rb_no_preset,   0)
        self._preset_group.addButton(self._rb_use_preset,  1)
        self._preset_group.addButton(self._rb_load_preset, 2)
        self._preset_group.idToggled.connect(self._on_preset_toggled)

        layout.addSpacing(8)

        # ── Sekcja 2: White balance ───────────────────────────────────────────
        layout.addWidget(QLabel(self.tr("White balance:")))

        self._rb_wb_exif = QRadioButton(self.tr("From camera (EXIF)"))
        self._rb_wb_exif.setChecked(True)
        layout.addWidget(self._rb_wb_exif)

        # Manual K — wiersz z polem
        manual_row = QHBoxLayout()
        self._rb_wb_manual = QRadioButton(self.tr("Manual:"))
        manual_row.addWidget(self._rb_wb_manual)
        self._kelvin_edit = QLineEdit()
        self._kelvin_edit.setPlaceholderText("5500")
        self._kelvin_edit.setFixedWidth(70)
        self._kelvin_edit.setEnabled(False)
        manual_row.addWidget(self._kelvin_edit)
        manual_row.addWidget(QLabel("K"))
        manual_row.addStretch(1)
        layout.addLayout(manual_row)

        self._rb_wb_preset = QRadioButton(self.tr("From preset XMP"))
        self._rb_wb_preset.setEnabled(False)   # aktywny tylko gdy preset wybrany
        layout.addWidget(self._rb_wb_preset)

        # Grupa WB — wzajemne wykluczenie
        self._wb_group = QButtonGroup(self)
        self._wb_group.addButton(self._rb_wb_exif,   0)
        self._wb_group.addButton(self._rb_wb_manual, 1)
        self._wb_group.addButton(self._rb_wb_preset, 2)
        self._wb_group.idToggled.connect(self._on_wb_toggled)

        layout.addSpacing(8)

        # ── Przyciski ─────────────────────────────────────────────────────────
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
        """Przywraca ostatni wybór presetu z QSettings."""
        last_preset_src = self._settings.value("developer/last_preset_src", "no_preset")
        if last_preset_src == "use_preset":
            self._rb_use_preset.setChecked(True)
            last_preset = self._settings.value("developer/last_preset", "")
            if last_preset:
                for i in range(self._combo.count()):
                    if self._combo.itemData(i) == last_preset:
                        self._combo.setCurrentIndex(i)
                        break
        else:
            self._rb_no_preset.setChecked(True)

        last_wb = self._settings.value("developer/last_wb", "exif")
        if last_wb == "manual":
            self._rb_wb_manual.setChecked(True)
            k = self._settings.value("developer/last_kelvin", "5500")
            self._kelvin_edit.setText(str(k))
        else:
            self._rb_wb_exif.setChecked(True)

    def _on_develop(self):
        """Zbiera wybory i wywołuje accept()."""
        # Preset
        pid = self._preset_group.checkedId()
        if pid == 0:
            self.selected_preset = _AUTO_PRESET
        elif pid == 1:
            self.selected_preset = self._combo.currentData()
        else:
            if self._loaded_xmp_path is None:
                QMessageBox.warning(self, self.tr("No file"),
                    self.tr("Please select an XMP file first."))
                return
            self.selected_preset = str(self._loaded_xmp_path)

        # WB
        wid = self._wb_group.checkedId()
        if wid == 0:
            self.selected_kelvin = 0       # EXIF
        elif wid == 1:
            try:
                self.selected_kelvin = int(self._kelvin_edit.text())
            except ValueError:
                QMessageBox.warning(self, self.tr("Invalid value"),
                    self.tr("Enter a valid Kelvin value (e.g. 5500)."))
                return
        else:
            self.selected_kelvin = None    # z presetu XMP

        # Zapamiętaj
        src_map = {0: "no_preset", 1: "use_preset", 2: "load_preset"}
        self._settings.setValue("developer/last_preset_src", src_map[pid])
        if pid == 1:
            self._settings.setValue("developer/last_preset", self.selected_preset)
        wb_map = {0: "exif", 1: "manual", 2: "from_preset"}
        self._settings.setValue("developer/last_wb", wb_map[wid])
        if wid == 1:
            self._settings.setValue("developer/last_kelvin", self.selected_kelvin)

        self.accept()

    def _on_preset_toggled(self, btn_id: int, checked: bool):
        """Reaguje na zmianę sekcji Preset — włącza/wyłącza widgety."""
        if not checked:
            return
        pid = self._preset_group.checkedId()
        has_preset = pid in (1, 2)

        self._combo.setEnabled(pid == 1)
        self._btn_browse.setEnabled(pid == 2)

        # "From preset XMP" dostępne tylko gdy mamy preset
        self._rb_wb_preset.setEnabled(has_preset)
        if not has_preset and self._rb_wb_preset.isChecked():
            self._rb_wb_exif.setChecked(True)

        self.adjustSize()

    def _on_wb_toggled(self, btn_id: int, checked: bool):
        """Włącza/wyłącza pole Kelvin zależnie od wyboru WB."""
        if not checked:
            return
        self._kelvin_edit.setEnabled(self._wb_group.checkedId() == 1)

    def _on_load_preset(self):
        """Otwiera file dialog do wyboru pliku XMP."""
        start_dir = (
            str(Path(self._session_path).parent)
            if self._session_path
            else str(Path.home())
        )
        src, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select XMP preset"), start_dir,
            self.tr("XMP files (*.xmp);;All files (*)")
        )
        if not src:
            return
        self._loaded_xmp_path = Path(src)
        self._load_path_label.setText(self._loaded_xmp_path.name)
        self._load_path_label.setToolTip(src)
        self._load_path_label.setStyleSheet("")

    def _current_preset_path(self) -> Path | None:
        """Zwraca ścieżkę XMP aktualnie wybranego presetu lub None dla __auto__."""
        name = self._combo.currentData()
        if name == _AUTO_PRESET:
            return None
        user = self._presets_dir / "user" / f"{name}.xmp"
        if user.exists():
            return user
        base = self._presets_dir / f"{name}.xmp"
        return base if base.exists() else None

    def _on_edit_xmp(self):
        """Pokazuje/ukrywa edytor inline z zawartością aktualnego XMP."""
        path = self._current_preset_path()
        if path is None:
            QMessageBox.information(self, self.tr("View / Edit XMP"),
                self.tr("Auto preset has no XMP file to edit."))
            return
        visible = self._xmp_editor.isVisible()
        if not visible:
            try:
                self._xmp_editor.setPlainText(path.read_text(encoding="utf-8"))
            except OSError as e:
                QMessageBox.warning(self, self.tr("Read error"), str(e))
                return
            self._xmp_editor.setProperty("_editing_path", str(path))
        self._xmp_editor.setVisible(not visible)
        self._btn_save_xmp.setVisible(not visible)
        self.adjustSize()

    def _on_save_xmp(self):
        """Zapisuje zawartość edytora do pliku XMP."""
        path_str = self._xmp_editor.property("_editing_path")
        if not path_str:
            return
        path = Path(path_str)
        try:
            path.write_text(self._xmp_editor.toPlainText(), encoding="utf-8")
            QMessageBox.information(self, self.tr("Saved"),
                self.tr(f"Saved: {path.name}"))
        except OSError as e:
            QMessageBox.warning(self, self.tr("Save error"), str(e))

    def _on_import_xmp(self):
        """Browse → wybierz XMP → dialog z nazwą → zapisz do presets/user/."""
        src, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select XMP preset"), "",
            self.tr("XMP files (*.xmp);;All files (*)")
        )
        if not src:
            return
        src_path = Path(src)

        name_dlg = QDialog(self)
        name_dlg.setWindowTitle(self.tr("Save preset as"))
        name_dlg.setMinimumWidth(360)
        vlay = QVBoxLayout(name_dlg)
        vlay.addWidget(QLabel(self.tr("Preset name (without .xmp):")))
        name_edit = QLineEdit(src_path.stem)
        name_edit.selectAll()
        vlay.addWidget(name_edit)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(name_dlg.accept)
        bb.rejected.connect(name_dlg.reject)
        vlay.addWidget(bb)
        name_edit.setFocus()
        if name_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        preset_name = name_edit.text().strip()
        if not preset_name:
            return

        user_dir = self._presets_dir / "user"
        user_dir.mkdir(parents=True, exist_ok=True)
        dest = user_dir / f"{preset_name}.xmp"
        try:
            shutil.copy2(src, dest)
        except OSError as e:
            QMessageBox.warning(self, self.tr("Import error"), str(e))
            return

        for i in range(self._combo.count()):
            if self._combo.itemData(i) == preset_name:
                self._combo.setCurrentIndex(i)
                return
        insert_pos = self._combo.count() - 1
        self._combo.insertItem(insert_pos, preset_name, preset_name)
        self._combo.setCurrentIndex(insert_pos)

    def _on_duplicate_preset(self):
        """Tworzy kopię presetu w presets/user/. Domyślna nazwa = '<oryginał> copy'."""
        src_path = self._current_preset_path()
        if src_path is None:
            QMessageBox.information(self, self.tr("Duplicate preset"),
                self.tr("Auto preset cannot be duplicated."))
            return

        default_name = f"{src_path.stem} copy"
        name_dlg = QDialog(self)
        name_dlg.setWindowTitle(self.tr("Duplicate preset"))
        name_dlg.setMinimumWidth(360)
        vlay = QVBoxLayout(name_dlg)
        vlay.addWidget(QLabel(self.tr("New preset name:")))
        name_edit = QLineEdit(default_name)
        name_edit.selectAll()
        vlay.addWidget(name_edit)
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(name_dlg.accept)
        bb.rejected.connect(name_dlg.reject)
        vlay.addWidget(bb)
        name_edit.setFocus()
        if name_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_name = name_edit.text().strip()
        if not new_name:
            return

        user_dir = self._presets_dir / "user"
        user_dir.mkdir(parents=True, exist_ok=True)
        dest = user_dir / f"{new_name}.xmp"
        try:
            shutil.copy2(src_path, dest)
        except OSError as e:
            QMessageBox.warning(self, self.tr("Duplicate error"), str(e))
            return

        for i in range(self._combo.count()):
            if self._combo.itemData(i) == new_name:
                self._combo.setCurrentIndex(i)
                return
        insert_pos = self._combo.count() - 1
        self._combo.insertItem(insert_pos, new_name, new_name)
        self._combo.setCurrentIndex(insert_pos)
