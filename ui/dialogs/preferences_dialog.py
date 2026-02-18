"""
Dialog preferencji aplikacji.
Pozwala użytkownikowi ustawić katalog sesji.
"""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QGroupBox, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QSettings


class PreferencesDialog(QDialog):
    """Dialog ustawień aplikacji."""

    # Klucz QSettings — taki sam jak w CameraView
    KEY_SESSION_DIR = "session/directory"

    # Domyślna ścieżka
    DEFAULT_SESSION_DIR = os.path.expanduser("~/Obrazy/sessions")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Preferences"))
        self.setMinimumWidth(520)
        self.setWindowFlags(
            self.windowFlags() & ~__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.WindowType.WindowContextHelpButtonHint
        )
        self.settings = QSettings("Grzeza", "SessionsAssistant")
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # === Session Directory Group ===
        dir_group = QGroupBox(self.tr("Session Directory"))
        dir_layout = QVBoxLayout(dir_group)

        description = QLabel(self.tr(
            "Photos captured in Camera view will be saved to:\n"
            "{directory}/captures/"
        ))
        description.setStyleSheet("color: #888; font-size: 11px;")
        dir_layout.addWidget(description)

        # Directory input row
        row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText(self.DEFAULT_SESSION_DIR)
        row.addWidget(self.dir_edit, 1)

        self.btn_browse = QPushButton(self.tr("Browse..."))
        self.btn_browse.clicked.connect(self._browse_directory)
        row.addWidget(self.btn_browse)

        dir_layout.addLayout(row)
        layout.addWidget(dir_group)

        # === Language Group (TODO) ===
        lang_group = QGroupBox(self.tr("Language"))
        lang_layout = QVBoxLayout(lang_group)

        from PyQt6.QtWidgets import QComboBox
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["English", "Polski"])
        self.lang_combo.setEnabled(False)  # TODO: not yet implemented

        lang_note = QLabel(self.tr("Language support coming soon."))
        lang_note.setStyleSheet("color: #888; font-size: 11px;")

        lang_layout.addWidget(self.lang_combo)
        lang_layout.addWidget(lang_note)
        layout.addWidget(lang_group)

        layout.addStretch()

        # === Dialog Buttons ===
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        button_box.accepted.connect(self._save_and_accept)
        button_box.rejected.connect(self.reject)
        button_box.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self._restore_defaults)
        layout.addWidget(button_box)

    def _load_settings(self):
        session_dir = self.settings.value(
            self.KEY_SESSION_DIR, self.DEFAULT_SESSION_DIR
        )
        self.dir_edit.setText(session_dir)

    def _save_and_accept(self):
        directory = self.dir_edit.text().strip() or self.DEFAULT_SESSION_DIR
        directory = os.path.expanduser(directory)

        # Utwórz katalog jeśli nie istnieje
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(
                self,
                self.tr("Cannot Create Directory"),
                self.tr("Could not create directory:\n{}\n\n{}").format(directory, e)
            )
            return

        self.settings.setValue(self.KEY_SESSION_DIR, directory)
        self.accept()

    def _restore_defaults(self):
        self.dir_edit.setText(self.DEFAULT_SESSION_DIR)

    def _browse_directory(self):
        current = self.dir_edit.text() or self.DEFAULT_SESSION_DIR
        current = os.path.expanduser(current)
        directory = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Session Directory"),
            current,
            QFileDialog.Option.ShowDirsOnly
        )
        if directory:
            self.dir_edit.setText(directory)

    @staticmethod
    def get_session_directory() -> str:
        """Zwraca aktualny katalog sesji z QSettings."""
        settings = QSettings("Grzeza", "SessionsAssistant")
        return settings.value(
            PreferencesDialog.KEY_SESSION_DIR,
            PreferencesDialog.DEFAULT_SESSION_DIR
        )
