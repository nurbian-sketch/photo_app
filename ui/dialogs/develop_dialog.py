"""
DevelopDialog — dialog wyboru stylu darktable do wywołania RAW.
Wywoływany po zakończeniu sesji gdy w katalogu sesji są pliki RAW.
"""
import sqlite3
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QRadioButton,
    QButtonGroup, QComboBox,
    QLineEdit, QFileDialog, QDialogButtonBox, QMessageBox,
)

from ui.styles import (
    DIALOG_SPACING, DIALOG_MARGINS, DIALOG_MIN_WIDTH,
    DIALOG_BTN_H,
    center_on_parent,
)

_AUTO_PRESET = "__auto__"

DARKTABLE_DB = Path("~/.config/darktable/data.db").expanduser()


def _collect_styles(db_path: Path = DARKTABLE_DB) -> list[str]:
    """Zwraca posortowaną listę nazw stylów z bazy darktable."""
    if not db_path.exists():
        return []
    try:
        con = sqlite3.connect(str(db_path))
        cur = con.execute("SELECT name FROM styles ORDER BY name COLLATE NOCASE")
        names = [row[0] for row in cur.fetchall()]
        con.close()
        return names
    except Exception:
        return []


class DevelopDialog(QDialog):
    """
    Dialog wyboru stylu darktable.

    Zwraca po accept():
        selected_preset:
            str  — nazwa stylu z bazy darktable
            str  — ścieżka absolutna do pliku .dtstyle
            "__auto__" — bez stylu
        selected_kelvin:
            0     — WB z EXIF (domyślne)
            int>0 — ręczna wartość Kelvin
    """

    def __init__(self, session_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Develop RAW files?"))
        self.setMinimumWidth(DIALOG_MIN_WIDTH)
        self.setModal(True)

        self._session_path = session_path
        self._settings     = QSettings("Grzeza", "SessionsAssistant")

        self.selected_preset: str       = _AUTO_PRESET
        self.selected_kelvin: int|None  = 0

        self._loaded_dtstyle_path: Path | None = None

        self._build_ui()
        self._restore_settings()

    def showEvent(self, event):
        super().showEvent(event)
        center_on_parent(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(DIALOG_SPACING)
        layout.setContentsMargins(*DIALOG_MARGINS)

        # ── Sekcja: Styl ─────────────────────────────────────────────────────
        layout.addWidget(QLabel(self.tr("Style:")))

        self._rb_no_style = QRadioButton(self.tr("No style (darktable auto)"))
        self._rb_no_style.setChecked(True)
        layout.addWidget(self._rb_no_style)

        # "Use style" + combo w jednym wierszu
        use_row = QHBoxLayout()
        self._rb_use_style = QRadioButton(self.tr("Use style:"))
        use_row.addWidget(self._rb_use_style)
        self._combo = QComboBox()
        self._populate_combo()
        self._combo.setEnabled(False)
        use_row.addWidget(self._combo, stretch=1)
        layout.addLayout(use_row)

        # "Load .dtstyle" + etykieta pliku w jednym wierszu
        load_row = QHBoxLayout()
        self._rb_load_style = QRadioButton(self.tr("Load .dtstyle:"))
        load_row.addWidget(self._rb_load_style)
        self._load_path_label = QLabel(self.tr("(no file selected)"))
        self._load_path_label.setStyleSheet("color: gray;")
        load_row.addWidget(self._load_path_label, stretch=1)
        self._btn_browse = QPushButton(self.tr("Browse..."))
        self._btn_browse.setFixedHeight(DIALOG_BTN_H)
        self._btn_browse.setEnabled(False)
        self._btn_browse.clicked.connect(self._on_load_dtstyle)
        load_row.addWidget(self._btn_browse)
        layout.addLayout(load_row)

        # ButtonGroup dla sekcji stylu
        self._style_group = QButtonGroup(self)
        self._style_group.addButton(self._rb_no_style,   0)
        self._style_group.addButton(self._rb_use_style,  1)
        self._style_group.addButton(self._rb_load_style, 2)
        self._style_group.idToggled.connect(self._on_style_toggled)

        # ── Sekcja: White Balance ─────────────────────────────────────────────
        layout.addWidget(QLabel(self.tr("White Balance:")))

        self._rb_wb_exif   = QRadioButton(self.tr("From EXIF (camera)"))
        self._rb_wb_manual = QRadioButton(self.tr("Manual:"))
        self._rb_wb_exif.setChecked(True)
        layout.addWidget(self._rb_wb_exif)

        wb_manual_row = QHBoxLayout()
        wb_manual_row.addWidget(self._rb_wb_manual)
        self._kelvin_edit = QLineEdit("5500")
        self._kelvin_edit.setFixedWidth(70)
        self._kelvin_edit.setEnabled(False)
        wb_manual_row.addWidget(self._kelvin_edit)
        wb_manual_row.addWidget(QLabel("K"))
        wb_manual_row.addStretch()
        layout.addLayout(wb_manual_row)

        self._wb_group = QButtonGroup(self)
        self._wb_group.addButton(self._rb_wb_exif,   0)
        self._wb_group.addButton(self._rb_wb_manual, 1)
        self._wb_group.idToggled.connect(self._on_wb_toggled)

        # ── Przyciski OK/Cancel ───────────────────────────────────────────────
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        layout.addWidget(bb)

    def _populate_combo(self):
        """Wypełnia combo stylami z bazy darktable."""
        self._combo.clear()
        styles = _collect_styles()
        if not styles:
            self._combo.addItem(self.tr("(no styles in darktable DB)"), "")
            return
        for name in styles:
            self._combo.addItem(name, name)

    def _on_accept(self):
        sid = self._style_group.checkedId()

        if sid == 0:
            self.selected_preset = _AUTO_PRESET

        elif sid == 1:
            data = self._combo.currentData()
            if not data:
                QMessageBox.warning(
                    self, self.tr("No style"),
                    self.tr("No style selected.")
                )
                return
            self.selected_preset = data

        else:
            if self._loaded_dtstyle_path is None:
                QMessageBox.warning(
                    self, self.tr("No file"),
                    self.tr("Please select a .dtstyle file first.")
                )
                return
            self.selected_preset = str(self._loaded_dtstyle_path)

        # WB
        wid = self._wb_group.checkedId()
        if wid == 0:
            self.selected_kelvin = 0
        else:
            try:
                self.selected_kelvin = int(self._kelvin_edit.text())
            except ValueError:
                QMessageBox.warning(
                    self, self.tr("Invalid value"),
                    self.tr("Enter a valid Kelvin value (e.g. 5500).")
                )
                return

        # Zapamiętaj ustawienia
        src_map = {0: "no_style", 1: "use_style", 2: "load_style"}
        self._settings.setValue("developer/last_preset_src", src_map[sid])
        if sid == 1:
            self._settings.setValue("developer/last_preset", self.selected_preset)
        self._settings.setValue("developer/last_wb",
                                "exif" if wid == 0 else "manual")
        if wid == 1:
            self._settings.setValue("developer/last_kelvin", self.selected_kelvin)

        self.accept()

    def _on_style_toggled(self, btn_id: int, checked: bool):
        if not checked:
            return
        self._combo.setEnabled(btn_id == 1)
        self._btn_browse.setEnabled(btn_id == 2)
        self.adjustSize()

    def _on_wb_toggled(self, btn_id: int, checked: bool):
        if not checked:
            return
        self._kelvin_edit.setEnabled(btn_id == 1)

    def _on_load_dtstyle(self):
        """Otwiera file dialog do wyboru pliku .dtstyle."""
        start_dir = (
            str(Path(self._session_path).parent)
            if self._session_path else str(Path.home())
        )
        src, _ = QFileDialog.getOpenFileName(
            self, self.tr("Select .dtstyle file"), start_dir,
            self.tr("Darktable style files (*.dtstyle);;All files (*)")
        )
        if not src:
            return
        self._loaded_dtstyle_path = Path(src)
        self._load_path_label.setText(self._loaded_dtstyle_path.name)
        self._load_path_label.setToolTip(src)
        self._load_path_label.setStyleSheet("")

    def _restore_settings(self):
        """Przywraca ostatnie ustawienia z QSettings."""
        src = self._settings.value("developer/last_preset_src", "use_style")
        if src == "no_style":
            self._rb_no_style.setChecked(True)
        elif src == "load_style":
            self._rb_load_style.setChecked(True)
        else:
            name = self._settings.value("developer/last_preset", "")
            idx = self._combo.findData(name)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
            self._rb_use_style.setChecked(True)

        wb = self._settings.value("developer/last_wb", "exif")
        if wb == "manual":
            self._rb_wb_manual.setChecked(True)
            kelvin = self._settings.value("developer/last_kelvin", 5500)
            self._kelvin_edit.setText(str(kelvin))
