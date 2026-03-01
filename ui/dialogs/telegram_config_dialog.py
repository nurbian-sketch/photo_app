"""
Dialog konfiguracji Telegram.
Przechowuje bot token i chat ID w QSettings.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QGroupBox, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QSettings, Qt


class TelegramConfigDialog(QDialog):
    """Dialog do wprowadzenia bot tokenu i chat ID."""

    KEY_BOT_TOKEN = "telegram/bot_token"
    KEY_CHAT_ID   = "telegram/chat_id"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Telegram Configuration"))
        self.setMinimumWidth(500)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.settings = QSettings("Grzeza", "SessionsAssistant")
        self._init_ui()
        self._load()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # ── Instrukcja ────────────────────────────────────────────────
        info = QLabel(self.tr(
            "To send photos via Telegram you need a Telegram Bot.\n"
            "1. Open Telegram and message @BotFather → /newbot\n"
            "2. Copy the bot token below.\n"
            "3. Start a chat with your bot, then send /start.\n"
            "4. To get your Chat ID, message @userinfobot."
        ))
        info.setStyleSheet("color: #aaa; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # ── Bot Token ────────────────────────────────────────────────
        grp_token = QGroupBox(self.tr("Bot Token"))
        token_layout = QVBoxLayout(grp_token)
        self.edit_token = QLineEdit()
        self.edit_token.setPlaceholderText("123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
        self.edit_token.setEchoMode(QLineEdit.EchoMode.Password)
        show_row = QHBoxLayout()
        show_row.addWidget(self.edit_token)
        btn_show = QPushButton(self.tr("Show"))
        btn_show.setFixedWidth(55)
        btn_show.setCheckable(True)
        btn_show.toggled.connect(lambda checked: self.edit_token.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        ))
        show_row.addWidget(btn_show)
        token_layout.addLayout(show_row)
        layout.addWidget(grp_token)

        # ── Chat ID ──────────────────────────────────────────────────
        grp_chat = QGroupBox(self.tr("Recipient Chat ID"))
        chat_layout = QVBoxLayout(grp_chat)
        hint = QLabel(self.tr(
            "Enter your personal Chat ID (number) or a group Chat ID.\n"
            "The bot must be a member of the group to send there."
        ))
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        self.edit_chat = QLineEdit()
        self.edit_chat.setPlaceholderText("123456789")
        chat_layout.addWidget(hint)
        chat_layout.addWidget(self.edit_chat)
        layout.addWidget(grp_chat)

        layout.addStretch()

        # ── Przyciski ────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self):
        self.edit_token.setText(self.settings.value(self.KEY_BOT_TOKEN, ""))
        self.edit_chat.setText(self.settings.value(self.KEY_CHAT_ID, ""))

    def _save(self):
        token   = self.edit_token.text().strip()
        chat_id = self.edit_chat.text().strip()

        if not token or not chat_id:
            QMessageBox.warning(
                self, self.tr("Missing Data"),
                self.tr("Bot token and Chat ID are required.")
            )
            return

        self.settings.setValue(self.KEY_BOT_TOKEN, token)
        self.settings.setValue(self.KEY_CHAT_ID, chat_id)
        self.accept()

    @staticmethod
    def get_credentials() -> tuple[str, str]:
        """Zwraca (token, chat_id) z QSettings lub ('', '')."""
        s = QSettings("Grzeza", "SessionsAssistant")
        return (
            s.value(TelegramConfigDialog.KEY_BOT_TOKEN, ""),
            s.value(TelegramConfigDialog.KEY_CHAT_ID, ""),
        )
