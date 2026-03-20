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

from ui.styles import DIALOG_HINT_STYLE, DIALOG_BTN_H_SMALL

class PreferencesDialog(QDialog):
    """Dialog ustawień aplikacji."""

    # Klucz QSettings — taki sam jak w CameraView
    KEY_SESSION_DIR    = "session/directory"
    KEY_RCLONE_REMOTE  = "rclone/remote"
    KEY_RCLONE_DEST    = "rclone/destination"
    KEY_ARCHIVE_PATH   = "archive/path"
    KEY_ARCHIVE_DAYS   = "archive/days"
    KEY_GDRIVE_WARN_MB = "rclone/warn_free_mb"

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
        dir_group.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dir_layout = QVBoxLayout(dir_group)

        description = QLabel(self.tr(
            "Photos captured in Camera view will be saved to:\n"
            "{directory}/captures/"
        ))
        description.setStyleSheet(DIALOG_HINT_STYLE)
        dir_layout.addWidget(description)

        # Directory input row
        row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText(self.DEFAULT_SESSION_DIR)
        row.addWidget(self.dir_edit, 1)

        self.btn_browse = QPushButton(self.tr("Browse..."))
        self.btn_browse.setFixedHeight(DIALOG_BTN_H_SMALL)
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
        lang_note.setStyleSheet(DIALOG_HINT_STYLE)
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
        btn_show.setFixedHeight(DIALOG_BTN_H_SMALL)
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

        # === Cloud Sync Group ===
        sync_group = QGroupBox(self.tr("Cloud Sync (rclone)"))
        sync_group.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        sync_layout = QVBoxLayout(sync_group)

        sync_hint = QLabel(self.tr(
            "Sync client sessions to remote storage after import.\n"
            "Remote name must match a configured rclone remote (e.g. gdrive)."
        ))
        sync_hint.setStyleSheet(DIALOG_HINT_STYLE)
        sync_hint.setWordWrap(True)
        sync_layout.addWidget(sync_hint)

        remote_row = QHBoxLayout()
        remote_row.addWidget(QLabel(self.tr("Remote name:")))
        self.rclone_remote_edit = QLineEdit()
        self.rclone_remote_edit.setPlaceholderText("gdrive")
        remote_row.addWidget(self.rclone_remote_edit, 1)
        sync_layout.addLayout(remote_row)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel(self.tr("Destination path:")))
        self.rclone_dest_edit = QLineEdit()
        self.rclone_dest_edit.setPlaceholderText("Sessions")
        dest_row.addWidget(self.rclone_dest_edit, 1)
        sync_layout.addLayout(dest_row)

        space_row = QHBoxLayout()
        space_row.addWidget(QLabel(self.tr("Warn when free space below (MB):")))
        self.gdrive_warn_spin = QSpinBox()
        self.gdrive_warn_spin.setRange(100, 10000)
        self.gdrive_warn_spin.setSingleStep(100)
        self.gdrive_warn_spin.setValue(500)
        space_row.addWidget(self.gdrive_warn_spin)
        space_row.addStretch()
        sync_layout.addLayout(space_row)

        layout.addWidget(sync_group)

        # === Archive Group ===
        arch_group = QGroupBox(self.tr("Session Archive"))
        arch_group.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        arch_layout = QVBoxLayout(arch_group)

        arch_hint = QLabel(self.tr(
            "CLIENT sessions older than the specified number of days will be moved\n"
            "to the archive path on startup. Folder is removed from Google Drive automatically."
        ))
        arch_hint.setStyleSheet(DIALOG_HINT_STYLE)
        arch_hint.setWordWrap(True)
        arch_layout.addWidget(arch_hint)

        arch_path_row = QHBoxLayout()
        arch_path_row.addWidget(QLabel(self.tr("Archive path:")))
        self.archive_path_edit = QLineEdit()
        self.archive_path_edit.setPlaceholderText(self.tr("(disabled — leave empty)"))
        arch_path_row.addWidget(self.archive_path_edit, 1)
        btn_arch_browse = QPushButton(self.tr("Browse..."))
        btn_arch_browse.setFixedHeight(DIALOG_BTN_H_SMALL)
        btn_arch_browse.clicked.connect(self._browse_archive_path)
        arch_path_row.addWidget(btn_arch_browse)
        arch_layout.addLayout(arch_path_row)

        arch_days_row = QHBoxLayout()
        arch_days_row.addWidget(QLabel(self.tr("Archive after (days):")))
        self.archive_days_spin = QSpinBox()
        self.archive_days_spin.setRange(1, 3650)
        self.archive_days_spin.setValue(30)
        arch_days_row.addWidget(self.archive_days_spin)
        arch_days_row.addStretch()
        arch_layout.addLayout(arch_days_row)

        layout.addWidget(arch_group)

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
        for btn in button_box.buttons():
            btn.setFixedHeight(DIALOG_BTN_H_SMALL)
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

        self.rclone_remote_edit.setText(
            self.settings.value(self.KEY_RCLONE_REMOTE, "")
        )
        self.rclone_dest_edit.setText(
            self.settings.value(self.KEY_RCLONE_DEST, "Sessions")
        )
        self.gdrive_warn_spin.setValue(
            self.settings.value(self.KEY_GDRIVE_WARN_MB, 500, type=int)
        )
        self.archive_path_edit.setText(
            self.settings.value(self.KEY_ARCHIVE_PATH, "")
        )
        self.archive_days_spin.setValue(
            self.settings.value(self.KEY_ARCHIVE_DAYS, 30, type=int)
        )

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

        self.settings.setValue(
            self.KEY_RCLONE_REMOTE, self.rclone_remote_edit.text().strip()
        )
        self.settings.setValue(
            self.KEY_RCLONE_DEST, self.rclone_dest_edit.text().strip() or "Sessions"
        )
        self.settings.setValue(self.KEY_GDRIVE_WARN_MB, self.gdrive_warn_spin.value())
        self.settings.setValue(self.KEY_ARCHIVE_PATH, self.archive_path_edit.text().strip())
        self.settings.setValue(self.KEY_ARCHIVE_DAYS, self.archive_days_spin.value())

        self.accept()

    def _restore_defaults(self):
        self.dir_edit.setText(self.DEFAULT_SESSION_DIR)
        self.tg_token_edit.clear()
        self.tg_chat_edit.clear()
        self.rclone_remote_edit.clear()
        self.rclone_dest_edit.setText("Sessions")
        self.gdrive_warn_spin.setValue(500)
        self.archive_path_edit.clear()
        self.archive_days_spin.setValue(30)

    def _browse_archive_path(self):
        current = self.archive_path_edit.text() or os.path.expanduser("~")
        directory = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Archive Directory"),
            current,
            QFileDialog.Option.ShowDirsOnly,
        )
        if directory:
            self.archive_path_edit.setText(directory)

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
