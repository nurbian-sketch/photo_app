"""
ui/dialogs/session_from_files_dialog.py

Dialog tworzenia sesji z istniejących plików na dysku.
Otwierany z DarkroomView (F11 / przycisk "Session from selected…").
"""
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QGroupBox, QDialogButtonBox,
)
from PyQt6.QtCore import Qt
from core.session_context import SessionMode

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class SessionFromFilesDialog(QDialog):
    """Zbiera tryb sesji, opcjonalnie e-mail klienta i decyzję o plikach."""

    def __init__(self, files: list[str], parent=None):
        super().__init__(parent)
        self.files      = files
        self.mode       = SessionMode.HOME
        self.email      = ""
        self.move_files = True
        self.setWindowTitle(self.tr("Session from selected…"))
        self.setMinimumWidth(360)
        self.setWindowFlags(
            self.windowFlags()
            & ~__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.WindowType.WindowContextHelpButtonHint
        )
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Info
        layout.addWidget(QLabel(self.tr(f"{len(self.files)} file(s) selected.")))

        # Tryb sesji
        grp_mode = QGroupBox(self.tr("Session type"))
        row_mode = QHBoxLayout(grp_mode)
        self.rb_home   = QRadioButton(self.tr("Home"))
        self.rb_client = QRadioButton(self.tr("Client"))
        self.rb_home.setChecked(True)
        row_mode.addWidget(self.rb_home)
        row_mode.addWidget(self.rb_client)
        layout.addWidget(grp_mode)

        # E-mail
        grp_email = QGroupBox(self.tr("Client e-mail"))
        row_email = QHBoxLayout(grp_email)
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("client@example.com")
        self.email_edit.setEnabled(False)
        row_email.addWidget(self.email_edit)
        layout.addWidget(grp_email)

        # Pliki
        grp_files = QGroupBox(self.tr("Files"))
        col_files = QVBoxLayout(grp_files)
        self.rb_move = QRadioButton(self.tr("Move to session folder"))
        self.rb_copy = QRadioButton(self.tr("Copy to session folder"))
        self.rb_move.setChecked(True)
        col_files.addWidget(self.rb_move)
        col_files.addWidget(self.rb_copy)
        layout.addWidget(grp_files)

        # Przyciski
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Sygnały
        self.rb_client.toggled.connect(self.email_edit.setEnabled)

    def _on_accept(self):
        if self.rb_client.isChecked():
            email = self.email_edit.text().strip().lower()
            if not _EMAIL_RE.match(email):
                self.email_edit.setFocus()
                self.email_edit.setStyleSheet("border: 1px solid red;")
                return
            self.email = email
            self.mode  = SessionMode.CLIENT
        else:
            self.mode  = SessionMode.HOME
            self.email = ""
        self.move_files = self.rb_move.isChecked()
        self.accept()
