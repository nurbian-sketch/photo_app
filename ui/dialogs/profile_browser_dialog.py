"""
Dialog przeglądarki profili aparatu.
Czyta pliki JSON z camera_profiles/, pozwala Load / Delete.
"""
import os
import json

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QListWidget, QLabel, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal

_SETTINGS_KEY = "profiles/last_selected"


class ProfileBrowserDialog(QDialog):
    """Przeglądarka profili aparatu z camera_profiles/."""

    profile_selected = pyqtSignal(dict)

    def __init__(self, profiles_dir: str, parent=None):
        super().__init__(parent)
        self._profiles_dir = profiles_dir
        self.setWindowTitle("Camera Profiles")
        self.setMinimumSize(480, 360)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )
        self._init_ui()
        self._refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._on_load)
        self._list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        # Podgląd zawartości profilu
        self._detail = QLabel("")
        self._detail.setStyleSheet(
            "color: #aaa; font-size: 11px; padding: 4px;"
        )
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

        row = QHBoxLayout()
        self.btn_load = QPushButton("Load")
        self.btn_load.setEnabled(False)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setEnabled(False)
        btn_cancel = QPushButton("Cancel")
        self.btn_load.clicked.connect(self._on_load)
        self.btn_delete.clicked.connect(self._on_delete)
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_load)
        row.addWidget(self.btn_delete)
        row.addStretch()
        row.addWidget(btn_cancel)
        layout.addLayout(row)

    def _refresh(self):
        self._list.clear()
        self._detail.setText("")
        if not os.path.isdir(self._profiles_dir):
            return
        files = sorted(
            f for f in os.listdir(self._profiles_dir) if f.endswith(".json")
        )
        for fname in files:
            self._list.addItem(fname[:-5])  # bez .json
        self.btn_load.setEnabled(False)
        self.btn_delete.setEnabled(False)

        # Przywróć ostatnio wybrany profil
        last = QSettings("Grzeza", "SessionsAssistant").value(_SETTINGS_KEY, "")
        if last:
            items = self._list.findItems(last, Qt.MatchFlag.MatchExactly)
            if items:
                self._list.setCurrentItem(items[0])
                self._list.scrollToItem(items[0])

    def _selected_path(self) -> str | None:
        item = self._list.currentItem()
        if not item:
            return None
        return os.path.join(self._profiles_dir, item.text() + ".json")

    def _on_selection_changed(self, current, _prev):
        has = current is not None
        self.btn_load.setEnabled(has)
        self.btn_delete.setEnabled(has)
        if not has:
            self._detail.setText("")
            return
        path = os.path.join(self._profiles_dir, current.text() + ".json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            s = data.get("settings", {})
            parts = [f"{k}: {v}" for k, v in s.items()]
            self._detail.setText("   •   ".join(parts[:8]))
        except Exception:
            self._detail.setText("")

    def _on_load(self):
        path = self._selected_path()
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            item = self._list.currentItem()
            if item:
                QSettings("Grzeza", "SessionsAssistant").setValue(
                    _SETTINGS_KEY, item.text()
                )
            self.profile_selected.emit(data.get("settings", {}))
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Load Profile", f"Error loading profile:\n{e}")

    def _on_delete(self):
        path = self._selected_path()
        if not path:
            return
        item = self._list.currentItem()
        ans = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ans == QMessageBox.StandardButton.Yes:
            try:
                os.unlink(path)
                self._refresh()
            except Exception as e:
                QMessageBox.warning(self, "Delete Profile", f"Error:\n{e}")
