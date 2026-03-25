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
        selected_preset — nazwa presetu (str) lub "__auto__"
        selected_kelvin — int (0=EXIF) lub None (z presetu)
    """

    def __init__(self, session_path: str, presets_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Develop RAW files?"))
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setModal(True)

        self._presets_dir  = presets_dir
        self._session_path = session_path
        self._settings     = QSettings("Grzeza", "SessionsAssistant")

        # Wyniki wyboru
        self.selected_preset:   str        = PRESET_ORDER[0]
        self.selected_kelvin:   int | None = 0
        self.selected_xmp_path: Path | None = None

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

        # --- Nagłówek WB ---
        layout.addWidget(QLabel(self.tr("White balance:")))

        # Trzy opcje WB — wzajemnie wykluczające się
        self._rb_exif = QRadioButton(self.tr("From camera (EXIF)"))
        self._rb_exif.setChecked(True)
        layout.addWidget(self._rb_exif)

        self._rb_preset = QRadioButton(self.tr("Use preset"))
        layout.addWidget(self._rb_preset)

        self._rb_load = QRadioButton(self.tr("Load preset…"))
        layout.addWidget(self._rb_load)

        self._wb_group = QButtonGroup(self)
        self._wb_group.addButton(self._rb_exif,   0)
        self._wb_group.addButton(self._rb_preset, 1)
        self._wb_group.addButton(self._rb_load,   2)
        self._wb_group.idToggled.connect(self._update_wb_widgets)

        layout.addSpacing(4)

        # --- Widget dla trybu "Use preset" ---
        self._preset_widget = QWidget()
        pw = QVBoxLayout(self._preset_widget)
        pw.setContentsMargins(0, 0, 0, 0)
        pw.setSpacing(4)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel(self.tr("Preset:")))
        self._combo = QComboBox()
        for name in _collect_presets(self._presets_dir):
            label = _PRESET_LABELS.get(name, name)
            self._combo.addItem(label, name)
        preset_row.addWidget(self._combo, stretch=1)
        pw.addLayout(preset_row)

        edit_row = QHBoxLayout()
        edit_row.addStretch(1)
        self._btn_edit_xmp = QPushButton(self.tr("View / Edit"))
        self._btn_edit_xmp.setFixedHeight(DIALOG_BTN_H)
        self._btn_edit_xmp.setEnabled(False)   # TODO: włączyć gdy gotowe
        self._btn_edit_xmp.clicked.connect(self._on_edit_xmp)
        edit_row.addWidget(self._btn_edit_xmp)
        edit_row.addStretch(1)
        pw.addLayout(edit_row)

        layout.addWidget(self._preset_widget)

        # --- Widget dla trybu "Load preset" ---
        self._load_widget = QWidget()
        lw = QHBoxLayout(self._load_widget)
        lw.setContentsMargins(0, 0, 0, 0)
        lw.setSpacing(6)
        btn_browse = QPushButton(self.tr("Browse…"))
        btn_browse.setFixedHeight(DIALOG_BTN_H)
        btn_browse.clicked.connect(self._on_load_preset)
        lw.addWidget(btn_browse)
        self._load_path_label = QLabel(self.tr("No file selected"))
        self._load_path_label.setStyleSheet("color: #888; font-size: 11px;")
        lw.addWidget(self._load_path_label, stretch=1)
        layout.addWidget(self._load_widget)

        # --- Edytor XMP (ukryty — używany przez View/Edit gdy zostanie włączone) ---
        self._xmp_editor = QTextEdit()
        self._xmp_editor.setVisible(False)
        self._xmp_editor.setMinimumHeight(160)
        self._xmp_editor.setFontFamily("Monospace")
        self._xmp_editor.setFontPointSize(9)
        layout.addWidget(self._xmp_editor)

        save_row = QHBoxLayout()
        self._btn_save_xmp = QPushButton(self.tr("Save XMP"))
        self._btn_save_xmp.setFixedHeight(DIALOG_BTN_H)
        self._btn_save_xmp.setVisible(False)
        self._btn_save_xmp.clicked.connect(self._on_save_xmp)
        save_row.addStretch(1)
        save_row.addWidget(self._btn_save_xmp)
        save_row.addStretch(1)
        layout.addLayout(save_row)

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

        # Ustaw początkową widoczność
        self._update_wb_widgets(0, True)

    def _restore_settings(self):
        """Przywraca ostatni wybór z QSettings."""
        wb_source = self._settings.value("developer/last_wb_source", "exif")
        if wb_source == "preset":
            self._rb_preset.setChecked(True)
        else:
            # "load" też przywracamy jako exif — to wybór per-sesja
            self._rb_exif.setChecked(True)

        last_preset = self._settings.value("developer/last_preset", "")
        if last_preset:
            for i in range(self._combo.count()):
                if self._combo.itemData(i) == last_preset:
                    self._combo.setCurrentIndex(i)
                    break

    def _on_develop(self):
        """Zatwierdza wybór, zapisuje ustawienia."""
        if self._rb_exif.isChecked():
            # EXIF = brak presetu, darktable domyślne
            self.selected_preset   = _AUTO_PRESET
            self.selected_kelvin   = 0
            self.selected_xmp_path = None
            wb_source = "exif"
        elif self._rb_preset.isChecked():
            self.selected_preset   = self._combo.currentData()
            self.selected_kelvin   = None
            self.selected_xmp_path = None
            wb_source = "preset"
        else:
            # Load preset — ścieżka absolutna przekazana jako selected_preset
            if self._loaded_xmp_path is None:
                QMessageBox.warning(self, self.tr("No file"),
                    self.tr("Please select an XMP file first."))
                return
            self.selected_preset   = str(self._loaded_xmp_path)
            self.selected_kelvin   = None
            self.selected_xmp_path = self._loaded_xmp_path
            wb_source = "load"

        self._settings.setValue("developer/last_wb_source", wb_source)
        if wb_source == "preset":
            self._settings.setValue("developer/last_preset", self.selected_preset)

        self.accept()

    def _update_wb_widgets(self, btn_id: int = -1, checked: bool = True):
        """Pokazuje/ukrywa widgety zależnie od wybranego radio."""
        if not checked:
            return
        active = self._wb_group.checkedId()
        self._preset_widget.setVisible(active == 1)
        self._load_widget.setVisible(active == 2)
        self.adjustSize()

    def _on_load_preset(self):
        """Otwiera file dialog do wyboru pliku XMP."""
        from pathlib import Path as _Path
        start_dir = (
            str(_Path(self._session_path).parent)
            if self._session_path
            else str(_Path.home())
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
