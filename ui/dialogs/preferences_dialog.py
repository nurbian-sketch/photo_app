"""
Dialog preferencji aplikacji.
Pozwala użytkownikowi ustawić katalog sesji.
"""
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QGroupBox, QDialogButtonBox, QMessageBox, QComboBox, QSpinBox
)
from PyQt6.QtCore import QSettings, Qt

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
        self.setStyleSheet(
            "QPushButton { background-color: palette(button); }"
            " QPushButton:hover { background-color: palette(midlight); }"
            " QPushButton:focus { border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: palette(button); }"
            " QPushButton:focus:hover { background-color: palette(midlight); }"
        )
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # === Session Directory Group ===
        dir_group = QGroupBox(self.tr("Session Directory"))
        dir_group.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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

        # === Language Group ===
        lang_group = QGroupBox(self.tr("Language"))
        lang_group.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lang_layout = QVBoxLayout(lang_group)

        # (label, QSettings code) — "" = auto (system locale)
        self._lang_items = [
            (self.tr("Auto (system locale)"), ""),
            ("English",    "en"),
            ("Polski",     "pl"),
            ("Русский",    "ru"),
            ("Українська", "uk"),
        ]
        self.lang_combo = QComboBox()
        for label, _ in self._lang_items:
            self.lang_combo.addItem(label)

        lang_note = QLabel(self.tr("Language change takes effect after restarting the application."))
        lang_note.setStyleSheet("color: #888; font-size: 11px;")
        lang_note.setWordWrap(True)

        lang_layout.addWidget(self.lang_combo)
        lang_layout.addWidget(lang_note)
        layout.addWidget(lang_group)

        # === Telegram Bot Group ===
        tg_group = QGroupBox(self.tr("Telegram Bot"))
        tg_group.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tg_layout = QVBoxLayout(tg_group)

        # Bot Token
        token_label = QLabel(self.tr("Bot Token:"))
        token_row = QHBoxLayout()
        self.tg_token_edit = QLineEdit()
        self.tg_token_edit.setPlaceholderText("123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
        self.tg_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        token_row.addWidget(self.tg_token_edit, 1)
        btn_show = QPushButton(self.tr("Show"))
        btn_show.setFixedWidth(55)
        btn_show.setCheckable(True)
        btn_show.toggled.connect(lambda checked: self.tg_token_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        ))
        token_row.addWidget(btn_show)
        tg_layout.addWidget(token_label)
        tg_layout.addLayout(token_row)

        # Chat ID
        chat_label = QLabel(self.tr("Recipient Chat ID:"))
        self.tg_chat_edit = QLineEdit()
        self.tg_chat_edit.setPlaceholderText("123456789")
        tg_layout.addWidget(chat_label)
        tg_layout.addWidget(self.tg_chat_edit)

        layout.addWidget(tg_group)

        # === Sharing Group ===
        sharing_group = QGroupBox(self.tr("Sharing"))
        sharing_layout = QVBoxLayout(sharing_group)

        expiry_row = QHBoxLayout()
        expiry_label = QLabel(self.tr("Share code expiry (days):"))
        self.expiry_spin = QSpinBox()
        self.expiry_spin.setRange(1, 365)
        self.expiry_spin.setValue(14)
        expiry_row.addWidget(expiry_label)
        expiry_row.addWidget(self.expiry_spin)
        expiry_row.addStretch()
        sharing_layout.addLayout(expiry_row)
        layout.addWidget(sharing_group)

        layout.addStretch()

        # === Dialog Buttons ===
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        button_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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

        current_lang = self.settings.value("app/language", "")
        codes = [code for _, code in self._lang_items]
        idx = codes.index(current_lang) if current_lang in codes else 0
        self.lang_combo.setCurrentIndex(idx)

        self.tg_token_edit.setText(self.settings.value("telegram/bot_token", ""))
        self.tg_chat_edit.setText(self.settings.value("telegram/chat_id", ""))

        expiry = self.settings.value("sharing/code_expiry_days", 14, type=int)
        self.expiry_spin.setValue(expiry)

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

        lang_code = self._lang_items[self.lang_combo.currentIndex()][1]
        self.settings.setValue("app/language", lang_code)

        self.settings.setValue("telegram/bot_token", self.tg_token_edit.text().strip())
        self.settings.setValue("telegram/chat_id", self.tg_chat_edit.text().strip())

        self.settings.setValue("sharing/code_expiry_days", self.expiry_spin.value())

        self.accept()

    def _restore_defaults(self):
        self.dir_edit.setText(self.DEFAULT_SESSION_DIR)
        self.tg_token_edit.clear()
        self.tg_chat_edit.clear()

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

    @staticmethod
    def get_code_expiry_days() -> int:
        """Zwraca liczbę dni ważności kodu sesji."""
        settings = QSettings("Grzeza", "SessionsAssistant")
        return settings.value("sharing/code_expiry_days", 14, type=int)

    @staticmethod
    def get_captures_subdir() -> str:
        """Zwraca nazwę podkatalogu na zdjęcia z aparatu."""
        return "captures"
