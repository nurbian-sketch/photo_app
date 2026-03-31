from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QMessageBox, QFileDialog, QInputDialog, QSizePolicy,
    QSplitter, QStyledItemDelegate, QStyle, QStyleOptionButton, QApplication,
    QMenu, QGroupBox, QToolButton
)
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import Qt, QSize, QTimer, QRect, QProcess, QFileSystemWatcher, pyqtSignal

import os
from pathlib import Path

from ui.styles import BTN_STYLE_RED

from core.darkcache.cache_manager import PreviewCache
from core.darkcache.preview_generator import PreviewGenerator
from core.darkcache.thumbnail_reader import ExifThumbnailReader
from core.darkcache.service import DarkCacheService
from ui.widgets.preview_panel import PreviewPanel
from ui.widgets.photo_preview_dialog import PhotoPreviewDialog
from core.image_io import ImageLoader
from core.camera_card_browser import CameraCardBrowserWorker
from core.telegram_sender import TelegramSender
from ui.dialogs.telegram_config_dialog import TelegramConfigDialog


# Rola ścieżki pliku (dla plików dyskowych = UserRole)
_ITEM_PATH_ROLE      = Qt.ItemDataRole.UserRole
# Rola typu elementu listy: 'file', 'folder', 'parent'
_ITEM_TYPE_ROLE      = Qt.ItemDataRole.UserRole + 2
# Rola przechowująca folder PTP (tylko w trybie SD card)
_PTP_FOLDER_ROLE     = Qt.ItemDataRole.UserRole + 3
# Rola przechowująca lokalną ścieżkę do pliku tymczasowego (tryb SD card)
_SD_LOCAL_PATH_ROLE  = Qt.ItemDataRole.UserRole + 4


class CheckboxDelegate(QStyledItemDelegate):
    """Custom delegate z checkboxem w rogu miniatury (tylko dla plików)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkbox_size     = 20
        self.checkbox_margin_x = 16
        self.checkbox_margin_y = 8

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(_ITEM_TYPE_ROLE) != 'file':
            return
        checkbox_rect = QRect(
            option.rect.left() + 12,
            option.rect.top() + 5,
            self.checkbox_size,
            self.checkbox_size
        )
        checkbox_option = QStyleOptionButton()
        checkbox_option.rect = checkbox_rect
        is_checked = index.data(Qt.ItemDataRole.UserRole + 1)
        checkbox_option.state |= (
            QStyle.StateFlag.State_On if is_checked else QStyle.StateFlag.State_Off
        )
        checkbox_option.state |= QStyle.StateFlag.State_Enabled
        self.parent().style().drawControl(
            QStyle.ControlElement.CE_CheckBox, checkbox_option, painter
        )

    def editorEvent(self, event, model, option, index):
        if index.data(_ITEM_TYPE_ROLE) != 'file':
            return super().editorEvent(event, model, option, index)
        if event.type() == event.Type.MouseButtonRelease:
            checkbox_rect = QRect(
                option.rect.left() + self.checkbox_margin_x,
                option.rect.top() + self.checkbox_margin_y,
                self.checkbox_size,
                self.checkbox_size
            )
            if checkbox_rect.contains(event.pos()):
                current_state = index.data(Qt.ItemDataRole.UserRole + 1)
                model.setData(index, not current_state, Qt.ItemDataRole.UserRole + 1)
                widget = self.parent()
                while widget and not isinstance(widget, DarkroomView):
                    widget = widget.parent()
                if widget:
                    widget.update_selection_count()
                    widget._refresh_select_toggle_label()
                return True
        return super().editorEvent(event, model, option, index)


class DarkroomView(QWidget):

    # Emitowany po zaakceptowaniu WB picker
    wb_apply_requested = pyqtSignal(int)   # kelvin
    # Emitowany gdy użytkownik chce wywołać RAW developer
    develop_requested  = pyqtSignal(str)   # session_path (katalog bieżący)

    JPEG_EXTENSIONS      = ('.jpg', '.jpeg')
    RAW_EXTENSIONS_TUPLE = ('.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng')

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_dir           = None
        self.current_image_path    = None
        self._current_summary_path = None
        self.large_thumbs          = False
        self._hide_raw          = False
        self._hide_jpeg         = False
        self._filter_state      = 'all'
        self._sort_key          = 'name'   # 'name' | 'date' | 'type'
        self._sd_card_ready     = False
        self._sd_mode           = False
        self._loader            = None
        self._browser_worker    = None

        # Stan edycji GIMP
        self._gimp_process:       QProcess | None = None
        self._gimp_jpg_path:      str | None = None
        self._gimp_watcher:       QFileSystemWatcher | None = None
        self._gimp_export_timer:  QTimer | None = None
        self._format_worker     = None
        self._list_file_offset  = 0

        # Cache miniatur
        cache_dir = os.path.expanduser("~/.cache/photo_app/previews")
        os.makedirs(cache_dir, exist_ok=True)
        self.darkcache = DarkCacheService(
            PreviewCache(Path(cache_dir)),
            PreviewGenerator(),
            ExifThumbnailReader(),
        )

        # Lazy loading miniatur z dysku
        self.files      = []
        self.load_index = 0
        self.timer      = QTimer(self)
        self.timer.timeout.connect(self.load_next_thumbnails)

        # Obserwator zmian w katalogu — auto-odświeżanie po developer/rclone
        self._dir_watcher = QFileSystemWatcher(self)
        self._dir_watcher.directoryChanged.connect(self._on_dir_changed)
        self._dir_watcher_timer = QTimer(self)
        self._dir_watcher_timer.setSingleShot(True)
        self._dir_watcher_timer.setInterval(1500)
        self._dir_watcher_timer.timeout.connect(self._on_dir_watcher_fired)

        self.setup_ui()
        QTimer.singleShot(500, self.open_last_session)

    # ─────────────────────────── UI

    def setup_ui(self):
        BTN_H = 28

        # Panel lewy: ścieżka + miniatury
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        # Ścieżka nad miniaturami
        self.lbl_path = QLabel("")
        self.lbl_path.setStyleSheet(
            "color: #999; font-size: 11px; padding: 3px 6px;"
            "background: #1a1a1a; border-bottom: 1px solid #333;"
        )
        self.lbl_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        left_layout.addWidget(self.lbl_path)

        # Lista miniatur
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_widget.setIconSize(QSize(120, 120))
        self.list_widget.setGridSize(QSize(140, 155))
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: #1e1e1e; }"
            "QToolTip { background-color: #2d2d2d; color: #dddddd;"
            "           border: 1px solid #555; padding: 3px; }"
        )
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.itemClicked.connect(self.show_image)
        self.list_widget.currentItemChanged.connect(
            lambda cur, prev: self.show_image(cur) if cur else None
        )
        self.list_widget.itemDoubleClicked.connect(self._open_preview_dialog)
        self.list_widget.setItemDelegate(CheckboxDelegate(self.list_widget))
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_list_context_menu)
        left_layout.addWidget(self.list_widget, 1)

        # Dolny pasek lewego panelu: File + View
        left_bottom = QHBoxLayout()
        left_bottom.setSpacing(6)
        left_bottom.setContentsMargins(4, 4, 4, 4)

        # ── Grupa File (dawniej Location) ────────────────────────────────────
        grp_file = QGroupBox(self.tr("File"))
        grp_file.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_file = QHBoxLayout(grp_file)
        row_file.setContentsMargins(6, 4, 6, 4)
        row_file.setSpacing(4)

        self.btn_sessions     = QPushButton(self.tr("Sessions"))
        self.btn_last_session = QPushButton(self.tr("Last Session"))
        self.btn_open_folder  = QPushButton(self.tr("Open Folder…"))
        self.btn_sd_card      = QPushButton(self.tr("SD Card"))
        self.btn_sd_card.setVisible(False)

        for btn in [self.btn_sessions, self.btn_last_session,
                    self.btn_open_folder, self.btn_sd_card]:
            btn.setMinimumHeight(BTN_H)
            row_file.addWidget(btn)

        left_bottom.addWidget(grp_file)

        # ── Grupa View ───────────────────────────────────────────────────────
        grp_view_left = QGroupBox(self.tr("View"))
        grp_view_left.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_view_left = QHBoxLayout(grp_view_left)
        row_view_left.setContentsMargins(6, 4, 6, 4)
        row_view_left.setSpacing(4)

        # Dropdown filtru — klik = cykliczne, strzałka = menu z checkmarkami
        self.btn_filter = QToolButton()
        self.btn_filter.setMinimumHeight(BTN_H)
        self.btn_filter.setMinimumWidth(90)
        self.btn_filter.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_filter.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        from PyQt6.QtGui import QActionGroup
        filter_menu = QMenu(self)
        self._action_filter_all  = filter_menu.addAction(self.tr("All Files"))
        self._action_filter_jpeg = filter_menu.addAction(self.tr("JPEG Only"))
        self._action_filter_raw  = filter_menu.addAction(self.tr("RAW Only"))
        _filter_group = QActionGroup(self)
        _filter_group.setExclusive(True)
        for a in [self._action_filter_all, self._action_filter_jpeg, self._action_filter_raw]:
            a.setCheckable(True)
            _filter_group.addAction(a)
        self._action_filter_all.setChecked(True)
        self.btn_filter.setMenu(filter_menu)
        self.btn_filter.setText(self.tr("All Files"))
        self.btn_filter.clicked.connect(self._cycle_filter)
        self._action_filter_all.triggered.connect(lambda: self._set_filter('all'))
        self._action_filter_jpeg.triggered.connect(lambda: self._set_filter('jpeg'))
        self._action_filter_raw.triggered.connect(lambda: self._set_filter('raw'))

        # Toggle rozmiar miniatur
        self.btn_toggle_size = QPushButton(self.tr("Large Thumbs"))
        self.btn_toggle_size.setMinimumHeight(BTN_H)
        self.btn_toggle_size.clicked.connect(self.toggle_thumb_size)

        row_view_left.addWidget(self.btn_filter)
        row_view_left.addWidget(self.btn_toggle_size)

        left_bottom.addWidget(grp_view_left)
        left_bottom.addStretch()
        left_layout.addLayout(left_bottom)

        # Panel prawy: podgląd + kontrolki
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(6)

        self.preview = PreviewPanel()
        right_layout.addWidget(self.preview, 1)

        # Grupy przycisków — dwa rzędy (patrz niżej po definicji grup)
        # ── Grupa Image — wrappuje control_bar PreviewPanel ─────────────────
        grp_image = QGroupBox(self.tr("Image"))
        grp_image.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_image = QHBoxLayout(grp_image)
        row_image.setContentsMargins(0, 0, 0, 0)
        row_image.setSpacing(0)
        row_image.addWidget(self.preview.control_bar)

        # ── Grupa Edit ───────────────────────────────────────────────────────
        grp_edit = QGroupBox(self.tr("Edit"))
        grp_edit.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_edit = QHBoxLayout(grp_edit)
        row_edit.setContentsMargins(6, 4, 6, 4)
        row_edit.setSpacing(4)

        # Pulldown Select — klik = toggle, strzałka = menu
        self.btn_select = QToolButton()
        self.btn_select.setText(self.tr("Select"))
        self.btn_select.setMinimumHeight(BTN_H)
        self.btn_select.setMinimumWidth(75)
        self.btn_select.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_select.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        select_menu = QMenu(self)
        self._action_select_all   = select_menu.addAction(self.tr("Select All"))
        self._action_deselect_all = select_menu.addAction(self.tr("Deselect All"))
        self.btn_select.setMenu(select_menu)
        self.btn_select.clicked.connect(self._toggle_select_all)
        self._action_select_all.triggered.connect(self._select_all)
        self._action_deselect_all.triggered.connect(self._deselect_all)

        self.btn_delete = QPushButton(self.tr("Delete Selected"))
        self.btn_delete.setMinimumHeight(BTN_H)
        self.btn_delete.setEnabled(False)

        # SD card only — domyślnie ukryte
        self.btn_copy_to_disk = QPushButton(self.tr("Copy to Disk"))
        self.btn_copy_to_disk.setMinimumHeight(BTN_H)
        self.btn_copy_to_disk.setEnabled(False)
        self.btn_copy_to_disk.setVisible(False)

        # Disk only
        self.btn_copy_folder = QPushButton(self.tr("Copy to…"))
        self.btn_copy_folder.setMinimumHeight(BTN_H)
        self.btn_copy_folder.setEnabled(False)
        self.btn_copy_folder.clicked.connect(lambda: self._copy_or_move_selected(move=False))

        self.btn_move_folder = QPushButton(self.tr("Move to…"))
        self.btn_move_folder.setMinimumHeight(BTN_H)
        self.btn_move_folder.setEnabled(False)
        self.btn_move_folder.clicked.connect(lambda: self._copy_or_move_selected(move=True))

        for w in [self.btn_select, self.btn_delete,
                  self.btn_copy_to_disk,
                  self.btn_copy_folder, self.btn_move_folder]:
            row_edit.addWidget(w)

        # ── Grupa Dir ────────────────────────────────────────────────────────
        grp_dir = QGroupBox(self.tr("Dir"))
        grp_dir.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_dir = QHBoxLayout(grp_dir)
        row_dir.setContentsMargins(6, 4, 6, 4)
        row_dir.setSpacing(4)

        # Disk only
        self.btn_make_dir = QPushButton(self.tr("Make Dir"))
        self.btn_make_dir.setMinimumHeight(BTN_H)

        self.btn_delete_dir = QPushButton(self.tr("Delete Dir"))
        self.btn_delete_dir.setMinimumHeight(BTN_H)

        # SD card only — domyślnie ukryty; zastępuje Make/Delete Dir w trybie SD
        self.btn_format_card = QPushButton(self.tr("Format Card"))
        self.btn_format_card.setMinimumHeight(BTN_H)
        self.btn_format_card.setStyleSheet(BTN_STYLE_RED)
        self.btn_format_card.setVisible(False)

        for w in [self.btn_make_dir, self.btn_delete_dir, self.btn_format_card]:
            row_dir.addWidget(w)

        # ── Grupa External ───────────────────────────────────────────────────
        grp_external = QGroupBox(self.tr("External"))
        grp_external.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_external = QHBoxLayout(grp_external)
        row_external.setContentsMargins(6, 4, 6, 4)
        row_external.setSpacing(4)

        self.btn_develop = QPushButton(self.tr("Develop…"))
        self.btn_develop.setMinimumHeight(BTN_H)
        self.btn_develop.setIcon(QIcon.fromTheme("darktable"))
        self.btn_develop.setEnabled(False)
        self.btn_develop.clicked.connect(self._on_develop_requested)

        self.btn_edit_gimp = QPushButton(self.tr("Edit…"))
        self.btn_edit_gimp.setMinimumHeight(BTN_H)
        self.btn_edit_gimp.setIcon(QIcon.fromTheme("gimp"))
        self.btn_edit_gimp.setEnabled(False)
        self.btn_edit_gimp.clicked.connect(self._edit_in_gimp)

        # Telegram — klik = wyślij, strzałka = konfiguracja
        self.btn_send = QToolButton()
        self.btn_send.setText(self.tr("Send…"))
        self.btn_send.setMinimumHeight(BTN_H)
        self.btn_send.setMinimumWidth(90)
        self.btn_send.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_send.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_send.setIcon(QIcon.fromTheme("telegram"))
        self.btn_send.setEnabled(False)
        send_menu = QMenu(self)
        self._action_telegram_config = send_menu.addAction(self.tr("Configure Telegram…"))
        self.btn_send.setMenu(send_menu)
        self.btn_send.clicked.connect(lambda: self._send_via_telegram())
        self._action_telegram_config.triggered.connect(self._configure_telegram)

        for w in [self.btn_develop, self.btn_edit_gimp, self.btn_send]:
            row_external.addWidget(w)

        # Wiersz 1: kontrolki obrazu
        row_image_bar = QHBoxLayout()
        row_image_bar.setSpacing(8)
        row_image_bar.setContentsMargins(0, 0, 0, 0)
        row_image_bar.addWidget(grp_image)
        row_image_bar.addStretch()
        right_layout.addLayout(row_image_bar)

        # Wiersz 2: Edit + Dir + External
        row_action_bar = QHBoxLayout()
        row_action_bar.setSpacing(8)
        row_action_bar.setContentsMargins(0, 0, 0, 0)
        row_action_bar.addWidget(grp_edit)
        row_action_bar.addWidget(grp_dir)
        row_action_bar.addWidget(grp_external)
        row_action_bar.addStretch()
        right_layout.addLayout(row_action_bar)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left_panel)
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.addWidget(self.splitter)

        # Sygnały
        self.btn_sessions.clicked.connect(self._open_sessions_dir)
        self.btn_last_session.clicked.connect(self.open_last_session)
        self.btn_open_folder.clicked.connect(self.open_folder)
        self.btn_sd_card.clicked.connect(self._open_sd_card)

        self.btn_delete.clicked.connect(self.delete_images)
        self.btn_copy_to_disk.clicked.connect(self._copy_to_disk)
        self.btn_format_card.clicked.connect(self._format_card)
        self.btn_make_dir.clicked.connect(self._make_dir)
        self.btn_delete_dir.clicked.connect(self._delete_dir)

        self.preview.wb_applied.connect(self._on_wb_applied)

    # ─────────────────────────── Filtr widoku

    # Stany filtru: 'all' → 'jpeg' → 'raw' → 'all'
    _FILTER_STATES = ('all', 'jpeg', 'raw')
    _FILTER_LABELS = {'all': 'All Files', 'jpeg': 'JPEG Only', 'raw': 'RAW Only'}

    def _cycle_filter(self):
        """Klik na główny obszar — przełącza cyklicznie."""
        states = self._FILTER_STATES
        idx = states.index(self._filter_state)
        self._set_filter(states[(idx + 1) % len(states)])

    def _set_filter(self, state: str):
        """Ustawia filtr i aktualizuje UI."""
        self._filter_state = state
        self._hide_raw  = (state == 'jpeg')
        self._hide_jpeg = (state == 'raw')
        label = self.tr(self._FILTER_LABELS[state])
        self.btn_filter.setText(label)
        # Checkmarki w menu
        self._action_filter_all.setChecked(state == 'all')
        self._action_filter_jpeg.setChecked(state == 'jpeg')
        self._action_filter_raw.setChecked(state == 'raw')
        self._reload_current()

    def _reload_current(self):
        if self._sd_mode:
            self._apply_sd_filter()
        elif self.current_dir:
            self.load_images(self.current_dir)

    def _apply_sd_filter(self):
        """Ukrywa/pokazuje elementy listy SD wg aktywnego filtru."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_TYPE_ROLE) != 'file':
                continue
            name = item.text().lower()
            hide = (
                (self._hide_raw  and name.endswith(self.RAW_EXTENSIONS_TUPLE))
                or
                (self._hide_jpeg and name.endswith(self.JPEG_EXTENSIONS))
            )
            item.setHidden(hide)

    @property
    def _active_extensions(self) -> tuple:
        if self._hide_raw:
            return self.JPEG_EXTENSIONS
        if self._hide_jpeg:
            return self.RAW_EXTENSIONS_TUPLE
        return self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE

    # ─────────────────────────── Nawigacja / sesje

    def _open_in_darktable(self):
        """Otwiera bieżący folder lub zaznaczony plik w darktable."""
        import subprocess
        import shutil
        target = self.current_image_path or self.current_dir
        if not target:
            self._show_status(self.tr("No file or folder selected."), 3000)
            return
        if not shutil.which('darktable'):
            QMessageBox.warning(
                self, self.tr("Open in Darktable"),
                self.tr("darktable not found. Install darktable and try again.")
            )
            return
        # Darktable jest single-instance — druga próba kończy się błędem DB lock
        already_running = subprocess.run(
            ['pgrep', '-x', 'darktable'], capture_output=True
        ).returncode == 0
        if already_running:
            QMessageBox.information(
                self, self.tr("Open in Darktable"),
                self.tr("Darktable is already running.\nOpen the file from within the running instance.")
            )
            return
        subprocess.Popen(['darktable', target])

    def _open_sessions_dir(self):
        from ui.dialogs.preferences_dialog import PreferencesDialog
        base = PreferencesDialog.get_session_directory()
        if base:
            self.load_images(base)
        else:
            folder = QFileDialog.getExistingDirectory(
                self, self.tr("Select sessions folder"), os.path.expanduser("~")
            )
            if folder:
                self.load_images(folder)

    def open_last_session(self):
        """Otwiera najnowszy folder sesji w cloud/ lub home/."""
        from ui.dialogs.preferences_dialog import PreferencesDialog
        base_path = PreferencesDialog.get_session_directory()
        if not base_path:
            return
        os.makedirs(base_path, exist_ok=True)
        try:
            all_ext = self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE
            candidates = []
            # Szukaj w cloud/ i home/
            for subdir in ("cloud", "home"):
                scan = os.path.join(base_path, subdir)
                if not os.path.isdir(scan):
                    continue
                for d in os.listdir(scan):
                    full = os.path.join(scan, d)
                    if not os.path.isdir(full) or d.startswith("."):
                        continue
                    # Pliki bezpośrednio w folderze sesji
                    if any(f.lower().endswith(all_ext) for f in os.listdir(full)):
                        candidates.append(full)
                        continue
                    # Fallback: jpg/ po reorganizacji przez developer
                    jpg_sub = os.path.join(full, "jpg")
                    if os.path.isdir(jpg_sub) and any(
                        f.lower().endswith(all_ext) for f in os.listdir(jpg_sub)
                    ):
                        candidates.append(jpg_sub)
            # Fallback: bezpośrednie podfoldery base_dir
            if not candidates:
                for d in os.listdir(base_path):
                    full = os.path.join(base_path, d)
                    if not os.path.isdir(full) or d.startswith("."):
                        continue
                    if d in ("cloud", "home", "captures"):
                        continue
                    if any(f.lower().endswith(all_ext) for f in os.listdir(full)):
                        candidates.append(full)
            target = max(candidates, key=os.path.getmtime) if candidates else base_path
            self.load_images(target)
        except Exception as e:
            print(f"Error loading last session: {e}")

    def open_folder(self):
        from ui.dialogs.preferences_dialog import PreferencesDialog
        default = PreferencesDialog.get_session_directory()
        folder  = QFileDialog.getExistingDirectory(
            self, self.tr("Select photo folder"), default
        )
        if folder:
            self.load_images(folder)

    # ─────────────────────────── Ładowanie z dysku

    def load_images(self, folder: str, select_path: str = None):
        self._exit_sd_mode()
        self.current_dir           = folder
        self._current_summary_path = None
        self.timer.stop()
        self.list_widget.clear()
        self.preview.clear()
        self.current_image_path = None
        self._list_file_offset  = 0

        # Aktualizuj obserwowany katalog
        for _d in self._dir_watcher.directories():
            self._dir_watcher.removePath(_d)
        self._dir_watcher.addPath(folder)

        self.lbl_path.setText(folder)
        self.lbl_path.setTextFormat(Qt.TextFormat.PlainText)

        # Nawigacja w górę (..)
        parent = os.path.dirname(folder.rstrip("/"))
        if parent and parent != folder:
            self._add_nav_item("..", parent)
            self._list_file_offset += 1

        # Podfoldery (zawsze — nawigacja niezależna od filtru)
        try:
            subdirs = sorted(
                d for d in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, d)) and not d.startswith('.')
            )
        except PermissionError:
            subdirs = []

        for d in subdirs:
            self._add_folder_item(d, os.path.join(folder, d))
            self._list_file_offset += 1

        # Podsumowanie sesji — jeśli istnieje w katalogu
        summary_path = os.path.join(folder, "session_summary.json")
        if os.path.exists(summary_path):
            self._add_summary_item(summary_path)

        # Pliki obrazów wg filtru i sortowania
        try:
            raw_files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if f.lower().endswith(self._active_extensions)
            ]
            if self._sort_key == 'date':
                self.files = sorted(raw_files, key=lambda p: os.path.getmtime(p))
            elif self._sort_key == 'type':
                self.files = sorted(raw_files, key=lambda p: (
                    os.path.splitext(p)[1].lower(), os.path.basename(p).lower()
                ))
            else:  # name
                self.files = sorted(raw_files, key=lambda p: os.path.basename(p).lower())
        except PermissionError:
            self.files = []

        if not self.files:
            # Sprawdź czy są pliki ukryte przez aktywny filtr
            if self._hide_raw or self._hide_jpeg:
                try:
                    all_files = [
                        f for f in os.listdir(folder)
                        if f.lower().endswith(
                            self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE
                        )
                    ]
                except PermissionError:
                    all_files = []
                if all_files:
                    active_filter = "RAW" if self._hide_raw else "JPEG"
                    self._show_status(
                        self.tr(
                            f"Folder contains {len(all_files)} {active_filter} file(s) — hidden by active filter"
                        ),
                        6000
                    )
            return

        select_index = 0
        if select_path and select_path in self.files:
            select_index = self.files.index(select_path)

        for i in range(select_index + 1):
            self._add_thumbnail_item(i)

        self._select_and_show(select_index)

        self.load_index = select_index + 1
        if self.load_index < len(self.files):
            self.timer.start(30)

        self.update_selection_count()  # wyczyść duchy w status bar

    def _add_nav_item(self, label: str, path: str):
        icon = QApplication.style().standardIcon(
            QStyle.StandardPixmap.SP_FileDialogToParent
        )
        item = QListWidgetItem(icon, label)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE, 'parent')
        item.setToolTip(path)
        self.list_widget.addItem(item)

    def _add_folder_item(self, name: str, path: str):
        import re as _re
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        # Katalog sesji (email_YYYY-MM-DD_codeXXXXXX) — skróć do "KOD  YYYY-MM-DD"
        m = _re.search(r'(\d{4}-\d{2}-\d{2})_code([A-Z0-9]{6})$', name)
        label = f"{m.group(2)}  {m.group(1)}" if m else name
        item = QListWidgetItem(icon, label)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE, 'folder')
        item.setToolTip(name)
        self.list_widget.addItem(item)

    def _add_summary_item(self, path: str) -> None:
        """Dodaje session_summary.json jako element listy z własną ikoną."""
        icon_path = os.path.join("assets", "icons", "session-summary.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else \
               QApplication.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        item = QListWidgetItem(icon, "session_summary.json")
        item.setData(_ITEM_PATH_ROLE, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE, 'summary')
        item.setToolTip(path)
        self.list_widget.addItem(item)
        self._list_file_offset += 1

    def _add_thumbnail_item(self, index: int):
        path     = self.files[index]
        ext      = os.path.splitext(path)[1].lower()
        is_image = ext in (self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE)
        pixmap   = self.darkcache.get_pixmap(Path(path), self.large_thumbs) if is_image else None
        icon     = QIcon(pixmap) if pixmap and not pixmap.isNull() else QIcon()
        item     = QListWidgetItem(icon, os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE, 'file')
        self.list_widget.addItem(item)

    def load_next_thumbnails(self):
        if self.load_index >= len(self.files):
            self.timer.stop()
            return
        self._add_thumbnail_item(self.load_index)
        self.load_index += 1

    # ─────────────────────────── SD Card — przeglądanie

    def set_sd_card_ready(self, ready: bool):
        self._sd_card_ready = ready
        self.btn_sd_card.setVisible(ready)
        # Synchronizuj akcję SD Card — aktywna w menu tylko gdy widok Darkroom
        mw = self.window()
        if hasattr(mw, '_action_file_sd_card'):
            in_darkroom = getattr(mw, '_current_view_name', 'Darkroom') == 'Darkroom'
            mw._action_file_sd_card.setEnabled(ready and in_darkroom)

    def _open_sd_card(self):
        self._sd_mode = True
        self.timer.stop()
        self.list_widget.clear()
        self.preview.clear()
        self.current_image_path = None
        self.files              = []
        self._list_file_offset  = 0

        self.lbl_path.setText(self.tr("📷 Camera Card  —  scanning…"))
        self.btn_sd_card.setEnabled(False)
        # Ukryj przyciski disk-only
        self.btn_copy_folder.setVisible(False)
        self.btn_move_folder.setVisible(False)
        self.btn_develop.setVisible(False)
        self.btn_edit_gimp.setVisible(False)
        self.btn_make_dir.setVisible(False)
        self.btn_delete_dir.setVisible(False)
        # Pokaż przyciski SD-only
        self.btn_copy_to_disk.setVisible(True)
        self.btn_format_card.setVisible(True)
        # Blokuj do zakończenia skanowania
        self.btn_copy_to_disk.setEnabled(False)
        self.btn_delete.setEnabled(False)

        # Nawigacja powrotna
        self._add_nav_item("← Sessions", '__sessions__')
        self._list_file_offset += 1

        self._browser_worker = CameraCardBrowserWorker()
        self._browser_worker.file_found.connect(self._on_card_file_found)
        self._browser_worker.scan_finished.connect(self._on_card_scan_finished)
        self._browser_worker.start()

    def _on_card_file_found(self, ptp_folder: str, filename: str, local_path: str):
        """Identyczny pipeline co _add_thumbnail_item — DarkCacheService robi resztę."""
        ext      = os.path.splitext(filename)[1].lower()
        is_image = ext in (self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE)
        pixmap   = None
        if is_image:
            try:
                pixmap = self.darkcache.get_pixmap(Path(local_path), self.large_thumbs)
            except Exception:
                pixmap = None

        icon = QIcon(pixmap) if pixmap and not pixmap.isNull() else QIcon()

        item = QListWidgetItem(icon, filename)
        item.setData(Qt.ItemDataRole.UserRole,     filename)
        item.setData(_PTP_FOLDER_ROLE,             ptp_folder)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE,              'file')
        item.setData(_SD_LOCAL_PATH_ROLE,          local_path)

        # Ukryj natychmiast jeśli aktywny filtr wyklucza ten typ pliku
        name_lower = filename.lower()
        hidden = (
            (self._hide_raw  and name_lower.endswith(self.RAW_EXTENSIONS_TUPLE))
            or
            (self._hide_jpeg and name_lower.endswith(self.JPEG_EXTENSIONS))
        )
        item.setHidden(hidden)

        self.list_widget.addItem(item)

        # Zaznacz i pokaż pierwszy widoczny plik
        visible_count = sum(
            1 for i in range(self.list_widget.count())
            if not self.list_widget.item(i).isHidden()
               and self.list_widget.item(i).data(_ITEM_TYPE_ROLE) == 'file'
        )
        if visible_count == 1:
            self.list_widget.setCurrentItem(item)

    def _on_card_scan_finished(self, total: int, error: str):
        self.btn_sd_card.setEnabled(True)
        self._sort_sd_list()
        # btn_copy_to_disk i btn_delete odblokuje update_selection_count gdy coś zaznaczone
        self.update_selection_count()
        if error:
            self._show_status(self.tr(f"⚠ SD Card scan error: {error}"), 8000)
        else:
            self.lbl_path.setText(self.tr(f"📷 Camera Card  —  {total} files"))

    def _exit_sd_mode(self):
        if self._browser_worker:
            # Rozłącz PRZED abort+wait — kolejka Qt może zawierać jeszcze
            # sygnały file_found wyemitowane tuż przed abort; bez disconnect
            # dotrą do slotu już po cleanup_temp i crashują na brakującym pliku
            try:
                self._browser_worker.file_found.disconnect()
            except RuntimeError:
                pass
            if self._browser_worker.isRunning():
                self._browser_worker.abort()
                self._browser_worker.wait()
        self._browser_worker = None
        self._sd_mode = False
        # Ukryj przyciski SD-only, przywróć disk-only
        self.btn_copy_to_disk.setVisible(False)
        self.btn_format_card.setVisible(False)
        self.btn_copy_folder.setVisible(True)
        self.btn_move_folder.setVisible(True)
        self.btn_develop.setVisible(True)
        self.btn_edit_gimp.setVisible(True)
        self.btn_make_dir.setVisible(True)
        self.btn_delete_dir.setVisible(True)
        CameraCardBrowserWorker.cleanup_temp()

    # ─────────────────────────── Selekcja

    def _select_all(self):
        """Zaznacza wszystkie pliki w liście."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_TYPE_ROLE) == 'file':
                item.setData(Qt.ItemDataRole.UserRole + 1, True)
        self.list_widget.update()
        self.update_selection_count()

    def _deselect_all(self):
        """Odznacza wszystkie pliki."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_TYPE_ROLE) == 'file':
                item.setData(Qt.ItemDataRole.UserRole + 1, False)
        self.list_widget.update()
        self.update_selection_count()

    def _toggle_select_all(self):
        """Klik na główny obszar przycisku Select — przełącza zaznaczenie."""
        file_items = [
            self.list_widget.item(i)
            for i in range(self.list_widget.count())
            if self.list_widget.item(i).data(_ITEM_TYPE_ROLE) == 'file'
        ]
        all_checked = bool(file_items) and all(
            item.data(Qt.ItemDataRole.UserRole + 1) for item in file_items
        )
        if all_checked:
            self._deselect_all()
        else:
            self._select_all()

    def _refresh_select_toggle_label(self):
        """Bez btn_select_toggle — zostawione dla kompatybilności z CheckboxDelegate."""
        pass

    def _get_selected_sd_files(self) -> list:
        """Zwraca listę (ptp_folder, filename) zaznaczonych plików z karty SD."""
        result = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if (item.data(_ITEM_TYPE_ROLE) == 'file'
                    and item.data(Qt.ItemDataRole.UserRole + 1)):
                result.append((
                    item.data(_PTP_FOLDER_ROLE),
                    item.data(Qt.ItemDataRole.UserRole),
                ))
        return result

    # ─────────────────────────── SD Card — kopiowanie

    def _copy_to_disk(self):
        from ui.dialogs.camera_import_dialog import CameraImportDialog
        from ui.dialogs.preferences_dialog import PreferencesDialog

        selected = self._get_selected_sd_files()
        if not selected:
            QMessageBox.information(
                self, self.tr("Copy to Disk"),
                self.tr("No files selected. Use checkboxes to select files.")
            )
            return

        sessions_dir = (
            PreferencesDialog.get_session_directory()
            or os.path.expanduser("~/Pictures")
        )

        dialog = CameraImportDialog(selected, sessions_dir, parent=self)
        dialog.import_finished.connect(self._on_import_finished)
        dialog.exec()

    def _on_import_finished(self, dest_dir: str):
        self.load_images(dest_dir)

    # ─────────────────────────── SD Card — formatowanie

    def _format_card(self):
        reply = QMessageBox.warning(
            self,
            self.tr("Format Card"),
            self.tr(
                "This will PERMANENTLY DELETE all files on the camera card.\n"
                "This operation cannot be undone.\n\n"
                "Are you sure you want to format the card?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        reply2 = QMessageBox.critical(
            self,
            self.tr("Format Card — Final Confirmation"),
            self.tr(
                "⚠️  LAST WARNING  ⚠️\n\n"
                "All photos on the card will be PERMANENTLY lost.\n"
                "Confirm format?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return

        from core.camera_card_service import FormatCardWorker

        self.btn_format_card.setEnabled(False)
        self.btn_format_card.setText(self.tr("Formatting…"))

        self._format_worker = FormatCardWorker()
        self._format_worker.finished.connect(self._on_format_finished)
        self._format_worker.start()

    def _on_format_finished(self, success: bool, error: str):
        self.btn_format_card.setEnabled(True)
        self.btn_format_card.setText(self.tr("Format Card"))
        if success:
            QMessageBox.information(
                self, self.tr("Format Card"),
                self.tr("Card formatted successfully.")
            )
            self._open_sd_card()
        else:
            QMessageBox.critical(
                self, self.tr("Format Card"),
                self.tr(f"Format failed:\n{error}")
            )

    # ─────────────────────────── Podgląd / nawigacja

    def show_image(self, item):
        if item is None:
            return
        item_type = item.data(_ITEM_TYPE_ROLE)
        path      = item.data(Qt.ItemDataRole.UserRole)

        if item_type == 'parent':
            if path == '__sessions__':
                self.open_last_session()
            else:
                self._navigate_to(path)
            return

        if item_type == 'folder':
            self._navigate_to(path)
            return

        if item_type == 'summary':
            self._show_session_summary(path)
            return

        # Plik
        self.current_image_path = path if not self._sd_mode else None
        self.update_selection_count()  # przyciski i menu reagują na zmianę bieżącego pliku

        # Aktualizuj label ścieżki: folder / NAZWA.EXT
        if not self._sd_mode and path:
            folder_part = os.path.dirname(path)
            file_part   = os.path.basename(path)
            self.lbl_path.setText(f"{folder_part}/  <b>{file_part}</b>")
            self.lbl_path.setTextFormat(Qt.TextFormat.RichText)
        elif self._sd_mode:
            file_part = item.text()
            self.lbl_path.setText(f"📷  <b>{file_part}</b>")
            self.lbl_path.setTextFormat(Qt.TextFormat.RichText)
        if self._loader and self._loader.isRunning():
            try:
                self._loader.loaded.disconnect()
            except RuntimeError:
                pass
            self._loader.wait()
        self._loader = None

        if self._sd_mode:
            local_path = item.data(_SD_LOCAL_PATH_ROLE)
            if local_path and os.path.exists(local_path):
                self.preview.set_message(self.tr("Loading…"))
                self._loader = ImageLoader(local_path)
                self._loader.loaded.connect(self._on_image_loaded)
                self._loader.start()
            else:
                self.preview.set_message(self.tr("File not yet downloaded"))
        else:
            self.preview.set_message(self.tr("Loading…"))
            self._loader = ImageLoader(path)
            self._loader.loaded.connect(self._on_image_loaded)
            self._loader.start()

    def _show_session_summary(self, json_path: str) -> None:
        """Czyta session_summary.json i wyświetla dane jako czytelną listę par klucz: wartość."""
        import json as _json
        try:
            data = _json.loads(open(json_path, encoding="utf-8").read())
        except Exception as e:
            self.preview.set_message(self.tr(f"Cannot read session summary:\n{e}"))
            return

        # Pola pominięte w widoku
        SKIP = {"camera_time_offset", "session_path", "captures_path", "mode"}

        def _fmt_value(key, val) -> str:
            """Formatuje wartość pola do czytelnej postaci."""
            if val is None:
                return "—"
            if isinstance(val, list):
                if key == "imported_files":
                    return f"{len(val)} files"
                if key == "develop_errors":
                    return ", ".join(val) if val else "none"
                return f"{len(val)} items"
            if isinstance(val, dict):
                return ""   # sekcja — obsłużona osobno
            return str(val)

        def _row(label: str, value: str, bold_val: bool = False,
                 color: str = "") -> str:
            """Jeden wiersz tabeli: etykieta + wartość."""
            val_style = f"color:{color};" if color else ""
            val_html  = f"<b>{value}</b>" if bold_val else value
            return (
                f"<tr>"
                f"<td style='color:#888; padding-right:16px; white-space:nowrap;"
                f"vertical-align:top'>{label}</td>"
                f"<td style='{val_style}vertical-align:top'>{val_html}</td>"
                f"</tr>"
            )

        rows = []

        # ── Pola główne ──────────────────────────────────────────────────────
        order = [
            "session_id", "share_code", "email",
            "started_at", "ended_at", "duration_min",
        ]
        for key in order:
            if key not in data:
                continue
            bold = key in ("share_code",)
            rows.append(_row(key + ":", _fmt_value(key, data[key]), bold_val=bold))

        rows.append("<tr><td colspan='2'><hr style='border-color:#333'/></td></tr>")

        # ── Ustawienia aparatu ───────────────────────────────────────────────
        cs = data.get("camera_settings", {})
        if cs:
            for k, v in cs.items():
                if v:
                    rows.append(_row(f"  {k}:", str(v)))
            rows.append("<tr><td colspan='2'><hr style='border-color:#333'/></td></tr>")

        # ── Import ───────────────────────────────────────────────────────────
        imported = data.get("imported_files", [])
        rows.append(_row("imported_files:", f"{len(imported)} files"))
        rows.append("<tr><td colspan='2'><hr style='border-color:#333'/></td></tr>")

        # ── Development ──────────────────────────────────────────────────────
        dev_style  = data.get("develop_style")
        dev_count  = data.get("developed_count")
        total_raw  = data.get("total_raw")
        dev_errors = data.get("develop_errors") or []
        dev_time   = data.get("develop_time_sec")
        dev_per    = data.get("develop_sec_per_photo")

        if dev_style is None and dev_count is None:
            rows.append(_row("development:", "not processed"))
        else:
            rows.append(_row("develop_style:", dev_style or "auto"))
            count_str = f"{dev_count}/{total_raw}" if dev_count is not None else "—"
            rows.append(_row("developed_count:", count_str))
            if dev_time is not None:
                rows.append(_row("develop_time_sec:", f"{dev_time}s"))
                rows.append(_row("develop_sec_per_photo:", f"{dev_per}s"))
            if dev_errors:
                rows.append(_row(
                    "develop_errors:",
                    ", ".join(dev_errors),
                    color="#e07070"
                ))
            else:
                rows.append(_row("develop_errors:", "none"))

        rows.append("<tr><td colspan='2'><hr style='border-color:#333'/></td></tr>")

        # ── Sync ─────────────────────────────────────────────────────────────
        sync_status = data.get("sync_status", "pending")
        synced_at   = data.get("synced_at", "—")
        sync_color  = "#80c080" if sync_status == "done" else "#e07070"
        rows.append(_row("sync_status:", sync_status,
                         bold_val=True, color=sync_color))
        rows.append(_row("synced_at:", synced_at,
                         bold_val=(sync_status == "done")))

        # Dwie kolumny: dane sesji po lewej, QR po prawej
        qr_path = os.path.join(os.path.dirname(json_path), "qr_code.png")
        qr_col = ""
        if os.path.exists(qr_path):
            qr_col = (
                "<td style='vertical-align:top; text-align:center;"
                " width:260px; padding-left:16px'>"
                f"<img src='file://{qr_path}' width='240' height='240'/>"
                "</td>"
            )

        data_col = (
            "<td style='vertical-align:top'>"
            "<table cellspacing='4'>"
            + "".join(rows)
            + "</table></td>"
        )

        html = (
            "<div style='font-family:monospace; font-size:12px; padding:8px'>"
            "<table width='100%' cellspacing='0' cellpadding='0'><tr>"
            + data_col
            + qr_col
            + "</tr></table></div>"
        )
        self.preview.set_message(html)
        if self._loader and self._loader.isRunning():
            self._loader.wait()
        self._loader = None
        self.current_image_path    = None
        self._current_summary_path = json_path
        self.update_selection_count()

    def _navigate_to(self, path: str):
        self.load_images(path)

    def _on_dir_changed(self, path: str):
        """Katalog sesji zmieniony (developer/rclone) — debounce przed odświeżeniem."""
        self._dir_watcher_timer.start()

    def _on_dir_watcher_fired(self):
        """Odśwież widok po ustabilizowaniu zmian w katalogu."""
        if not (self.current_dir and not self._sd_mode and os.path.isdir(self.current_dir)):
            return
        summary_was = self._current_summary_path
        self.load_images(self.current_dir, select_path=self.current_image_path)
        # Jeśli pokazywano summary — przywróć po przeładowaniu listy
        if summary_was and os.path.exists(summary_was):
            self._show_session_summary(summary_was)
            # Zaznacz element summary w liście
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item.data(_ITEM_TYPE_ROLE) == 'summary':
                    self.list_widget.setCurrentItem(item)
                    break

    def _on_image_loaded(self, pixmap: QPixmap, exif: dict):
        self.preview.set_pixmap(pixmap, exif.get('orientation', 0))
        self.preview.set_exif(exif)

    def _select_and_show(self, index: int):
        item = self.list_widget.item(self._list_file_offset + index)
        if item:
            self.list_widget.setCurrentItem(item)
            self.show_image(item)

    def _open_preview_dialog(self, item):
        item_type = item.data(_ITEM_TYPE_ROLE)
        path      = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        if item_type == 'summary':
            return
        if item_type == 'parent':
            if path == '__sessions__':
                self.open_last_session()
            else:
                self._navigate_to(path)
            return
        if item_type == 'folder':
            self._navigate_to(path)
            return
        if not self._sd_mode:
            dialog = PhotoPreviewDialog(path, parent=None)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.wb_applied.connect(self._on_wb_applied)
            dialog.show()

    def _on_wb_applied(self, kelvin: int):
        self.wb_apply_requested.emit(kelvin)

    # ─────────────────────────── Usuwanie

    def delete_images(self):
        """Usuwa zaznaczone pliki — z dysku lub z karty SD (PTP)."""
        eff_paths = set(self._effective_files())
        if not eff_paths:
            return
        to_delete = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_TYPE_ROLE) != 'file':
                continue
            if self._sd_mode:
                p = item.data(_SD_LOCAL_PATH_ROLE)
            else:
                p = item.data(_ITEM_PATH_ROLE) or item.data(Qt.ItemDataRole.UserRole)
            if p in eff_paths:
                to_delete.append((i, item))
        if not to_delete:
            return

        reply = QMessageBox.question(
            self,
            self.tr("Delete"),
            self.tr("Delete {0} file(s)?").format(len(to_delete)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self._sd_mode:
            self._delete_from_card(to_delete)
        else:
            self._delete_from_disk(to_delete)

        self.update_selection_count()

    def _delete_from_disk(self, to_delete: list):
        """Usuwa pliki z dysku."""
        errors = []
        for i, item in reversed(to_delete):
            path = item.data(Qt.ItemDataRole.UserRole)
            try:
                os.remove(path)
                self.list_widget.takeItem(i)
                if path == self.current_image_path:
                    self.preview.clear()
                    self.current_image_path = None
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
        if errors:
            QMessageBox.warning(self, self.tr("Delete"), "\n".join(errors[:5]))

    def _delete_from_card(self, to_delete: list):
        """Usuwa pliki z karty SD przez PTP i z /tmp."""
        import gphoto2 as gp

        context = gp.Context()
        camera  = None
        errors  = []
        deleted = 0

        try:
            camera = gp.Camera()
            camera.init(context)
            for i, item in reversed(to_delete):
                ptp_folder = item.data(_PTP_FOLDER_ROLE)
                filename   = item.data(Qt.ItemDataRole.UserRole)
                local_path = item.data(_SD_LOCAL_PATH_ROLE)
                try:
                    camera.file_delete(ptp_folder, filename, context)
                    try:
                        if local_path and os.path.exists(local_path):
                            os.unlink(local_path)
                    except OSError:
                        pass
                    self.list_widget.takeItem(i)
                    deleted += 1
                except Exception as e:
                    errors.append(f"{filename}: {e}")
        except Exception as e:
            self._show_status(self.tr(f"⚠ Camera connection error: {e}"), 8000)
            return
        finally:
            if camera:
                try:
                    camera.exit(context)
                except Exception:
                    pass

        msg = (self.tr(f"⚠ Deleted {deleted}, errors: {len(errors)}")
               if errors else self.tr(f"Deleted {deleted} file(s) from card."))
        self._show_status(msg, 6000)

    def _show_status(self, msg: str, timeout: int = 4000):
        """Wyświetla komunikat w pasku stanu głównego okna."""
        main_window = self.window()
        if hasattr(main_window, 'status_bar'):
            main_window.status_bar.showMessage(msg, timeout)

    def _on_list_context_menu(self, pos):
        """Menu kontekstowe listy miniatur — pełny zestaw operacji."""
        item = self.list_widget.itemAt(pos)
        menu = QMenu(self)

        # ── Operacje na pliku XMP ────────────────────────────────────────────
        if item and item.data(_ITEM_TYPE_ROLE) == 'file':
            path = item.data(_ITEM_PATH_ROLE) or ""
            if path.lower().endswith(".xmp"):
                menu.addAction(
                    self.tr("Develop all RAW files in this folder…"),
                    self._on_develop_requested
                )
                menu.addAction(
                    self.tr("Edit XMP…"),
                    lambda: self._on_edit_xmp_file(path)
                )
                menu.addSeparator()

        eff = self._effective_files()
        count = len(eff)
        raw_count = len(self._effective_raw_files())

        # ── Develop ─────────────────────────────────────────────────────────
        if not self._sd_mode:
            act_develop = menu.addAction(
                self.tr(f"Develop {raw_count} RAW file(s)…") if raw_count > 1
                else self.tr("Develop RAW…"),
                self._on_develop_requested
            )
            act_develop.setEnabled(raw_count > 0)

            act_darktable = menu.addAction(
                self.tr("Open in Darktable"),
                self._open_in_darktable
            )
            act_edit_gimp = menu.addAction(
                self.tr("Edit in GIMP…"),
                self._edit_in_gimp
            )
            act_edit_gimp.setEnabled(bool(self._effective_jpeg_files()))
            menu.addSeparator()

        # ── Copy / Move ──────────────────────────────────────────────────────
        if not self._sd_mode:
            act_copy = menu.addAction(
                self.tr(f"Copy {count} file(s) to…") if count > 1
                else self.tr("Copy to…"),
                lambda: self._copy_or_move_selected(move=False)
            )
            act_copy.setEnabled(count > 0)

            act_move = menu.addAction(
                self.tr(f"Move {count} file(s) to…") if count > 1
                else self.tr("Move to…"),
                lambda: self._copy_or_move_selected(move=True)
            )
            act_move.setEnabled(count > 0)
            menu.addSeparator()

        # ── SD: Copy to Disk ─────────────────────────────────────────────────
        if self._sd_mode:
            act_copy_disk = menu.addAction(
                self.tr("Copy to Disk"),
                self._copy_to_disk
            )
            act_copy_disk.setEnabled(count > 0)
            menu.addSeparator()

        # ── Send / Delete ────────────────────────────────────────────────────
        act_send = menu.addAction(
            self.tr("Send via Telegram…"),
            lambda: self._send_via_telegram()
        )
        act_send.setEnabled(count > 0)

        act_delete = menu.addAction(
            self.tr(f"Delete {count} file(s)…") if count > 1
            else self.tr("Delete…"),
            self.delete_images
        )
        act_delete.setEnabled(count > 0)
        menu.addSeparator()

        # ── Selekcja ─────────────────────────────────────────────────────────
        menu.addAction(self.tr("Select All"),   self._select_all)
        menu.addAction(self.tr("Deselect All"), self._deselect_all)
        menu.addSeparator()

        # ── Sortowanie ───────────────────────────────────────────────────────
        for key, label in [
            ('name', self.tr("Sort by Name")),
            ('date', self.tr("Sort by Date")),
            ('type', self.tr("Sort by Type")),
        ]:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._sort_key == key)
            action.triggered.connect(lambda checked, k=key: self.set_sort(k))

        menu.exec(self.list_widget.mapToGlobal(pos))

    def set_sort(self, key: str):
        """Ustawia klucz sortowania i przeładowuje widok."""
        if key == self._sort_key:
            return
        self._sort_key = key
        if self._sd_mode:
            self._sort_sd_list()
        elif self.current_dir:
            self.load_images(self.current_dir, select_path=self.current_image_path)

    def _sort_sd_list(self):
        """Sortuje elementy listy SD card w miejscu (bez ponownego skanowania)."""
        count = self.list_widget.count()
        all_items = [self.list_widget.takeItem(0) for _ in range(count)]

        nav_items  = [it for it in all_items if it.data(_ITEM_TYPE_ROLE) != 'file']
        file_items = [it for it in all_items if it.data(_ITEM_TYPE_ROLE) == 'file']

        if self._sort_key == 'date':
            def _mtime(it):
                p = it.data(_SD_LOCAL_PATH_ROLE)
                try:
                    return os.path.getmtime(p) if p and os.path.exists(p) else 0
                except OSError:
                    return 0
            file_items.sort(key=_mtime)
        elif self._sort_key == 'type':
            file_items.sort(key=lambda it: (
                os.path.splitext(it.text())[1].lower(), it.text().lower()
            ))
        else:  # name
            file_items.sort(key=lambda it: it.text().lower())

        for it in nav_items + file_items:
            self.list_widget.addItem(it)

    # ─────────────────────────── Rozmiar miniatur

    def toggle_thumb_size(self):
        self._set_thumb_size(not self.large_thumbs)

    def _set_thumb_size(self, large: bool):
        self.large_thumbs = large
        if large:
            self.list_widget.setIconSize(QSize(240, 240))
            self.list_widget.setGridSize(QSize(260, 280))
            self.btn_toggle_size.setText(self.tr("Small Thumbs"))  # etykieta = następny krok
        else:
            self.list_widget.setIconSize(QSize(120, 120))
            self.list_widget.setGridSize(QSize(140, 155))
            self.btn_toggle_size.setText(self.tr("Large Thumbs"))

        if self._sd_mode:
            self._open_sd_card()
        elif self.current_dir:
            self.load_images(self.current_dir,
                             select_path=self.current_image_path)

    # ─────────────────────────── Telegram

    def _get_selected_file_paths(self) -> list[str]:
        """Zwraca ścieżki plików do wysyłki (efektywna selekcja)."""
        return self._effective_files()

    def _configure_telegram(self):
        """Otwiera dialog konfiguracji Telegrama."""
        TelegramConfigDialog(parent=self).exec()

    def _send_via_telegram(self):
        """Wysyła zaznaczone pliki przez Telegram Bot API jako dokumenty (bezstratnie)."""
        from PyQt6.QtWidgets import QProgressDialog

        # Pobierz ścieżki
        paths = self._get_selected_file_paths()
        if not paths:
            QMessageBox.information(
                self, self.tr("Send…"),
                self.tr("No files selected. Use checkboxes to select files.")
            )
            return

        # Sprawdź konfigurację — jeśli brak, otwórz dialog
        token, chat_id = TelegramConfigDialog.get_credentials()
        if not token or not chat_id:
            dlg = TelegramConfigDialog(parent=self)
            if dlg.exec() != TelegramConfigDialog.DialogCode.Accepted:
                return
            token, chat_id = TelegramConfigDialog.get_credentials()

        # Dialog postępu
        progress_dlg = QProgressDialog(
            self.tr("Sending {0} file(s)…").format(len(paths)),
            self.tr("Cancel"),
            0, len(paths), self
        )
        progress_dlg.setWindowTitle(self.tr("Send via Telegram"))
        progress_dlg.setMinimumWidth(400)
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.setValue(0)

        # Worker — zawsze as_photos=False (bezstratnie)
        self._telegram_worker = TelegramSender(
            token=token,
            chat_id=chat_id,
            file_paths=paths,
            as_photos=False,
        )

        def on_progress(idx, total, filename):
            progress_dlg.setLabelText(
                self.tr("Sending {0}/{1}: {2}").format(idx, total, filename)
            )
            progress_dlg.setValue(idx - 1)

        def on_file_done(idx, filename, ok):
            progress_dlg.setValue(idx)

        def on_finished(sent, skipped, errors):
            progress_dlg.close()
            parts = [self.tr("Sent: {0}").format(sent)]
            if skipped:
                parts.append(self.tr("Skipped (too large): {0}").format(skipped))
            if errors:
                parts.append(self.tr("Errors: {0}").format(errors))
            msg = "\n".join(parts)
            if errors or skipped:
                QMessageBox.warning(self, self.tr("Send via Telegram"), msg)
            else:
                QMessageBox.information(self, self.tr("Send via Telegram"), msg)

        def on_error(message):
            progress_dlg.close()
            reply = QMessageBox.critical(
                self, self.tr("Telegram Error"),
                message + "\n\n" + self.tr("Open Telegram configuration?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                TelegramConfigDialog(parent=self).exec()

        self._telegram_worker.progress.connect(on_progress)
        self._telegram_worker.file_done.connect(on_file_done)
        self._telegram_worker.finished_all.connect(on_finished)
        self._telegram_worker.error.connect(on_error)
        progress_dlg.canceled.connect(self._telegram_worker.stop)

        self.btn_send.setEnabled(False)
        self._telegram_worker.finished.connect(
            lambda: self.btn_send.setEnabled(True)
        )

        self._telegram_worker.start()
        progress_dlg.exec()

    # ─────────────────────────── Selekcja / status

    def update_selection_count(self):
        count = sum(
            1 for i in range(self.list_widget.count())
            if self.list_widget.item(i).data(_ITEM_TYPE_ROLE) == 'file'
            and self.list_widget.item(i).data(Qt.ItemDataRole.UserRole + 1)
        )
        main_window = self.window()
        if hasattr(main_window, 'status_bar'):
            if count > 0:
                main_window.status_bar.showMessage(
                    self.tr("Selected: {0} file(s)").format(count)
                )
            else:
                main_window.status_bar.showMessage(self.tr("Ready"))

        # Efektywna selekcja: checkbox lub bieżący plik
        has_any = count > 0 or bool(self.current_image_path)
        # btn_delete aktywny gdy coś wybrane
        self.btn_delete.setEnabled(has_any)
        # btn_copy_to_disk — aktywny w SD mode
        if self._sd_mode:
            self.btn_copy_to_disk.setEnabled(has_any)
        if not self._sd_mode:
            self.btn_copy_folder.setEnabled(has_any)
            self.btn_move_folder.setEnabled(has_any)
            has_raw = bool(self._effective_raw_files())
            self.btn_develop.setEnabled(has_raw)
            has_jpg = bool(self._effective_jpeg_files())
            self.btn_edit_gimp.setEnabled(has_jpg)
        # btn_send — aktywny gdy coś wybrane (oba tryby)
        self.btn_send.setEnabled(has_any)

        # Synchronizuj dynamiczne akcje menu w głównym oknie
        mw = main_window
        for attr in ('_action_mw_copy', '_action_mw_move', '_action_mw_delete', '_action_mw_send'):
            if hasattr(mw, attr):
                getattr(mw, attr).setEnabled(has_any)
        if hasattr(mw, '_action_mw_develop'):
            has_raw = has_raw if not self._sd_mode else False
            mw._action_mw_develop.setEnabled(has_raw)
        if hasattr(mw, '_action_mw_edit_gimp'):
            mw._action_mw_edit_gimp.setEnabled(
                has_jpg if not self._sd_mode else False
            )

    # ─────────────────────────── Cleanup

    def closeEvent(self, event):
        self._exit_sd_mode()
        if self._loader and self._loader.isRunning():
            self._loader.wait()
        super().closeEvent(event)

    # ─────────────────────────── Copy / Move / Develop

    def _selected_raw_files(self) -> list[str]:
        """Zwraca ścieżki zaznaczonych plików RAW (lub bieżącego jeśli brak zaznaczonych)."""
        return self._effective_raw_files()

    def _effective_files(self) -> list[str]:
        """Zwraca zaznaczone pliki (checkbox) lub bieżący plik jeśli brak zaznaczonych.
        W trybie SD: używa _SD_LOCAL_PATH_ROLE dla bieżącego pliku."""
        paths = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_TYPE_ROLE) != 'file':
                continue
            if not item.data(Qt.ItemDataRole.UserRole + 1):
                continue
            if self._sd_mode:
                local = item.data(_SD_LOCAL_PATH_ROLE)
                if local and os.path.isfile(local):
                    paths.append(local)
            else:
                p = item.data(_ITEM_PATH_ROLE) or item.data(Qt.ItemDataRole.UserRole)
                if p and os.path.isfile(p):
                    paths.append(p)
        if paths:
            return paths
        # Fallback: bieżący podglądany plik
        if self.current_image_path and os.path.isfile(self.current_image_path):
            return [self.current_image_path]
        return []

    def _effective_raw_files(self) -> list[str]:
        """Zwraca pliki RAW z efektywnej selekcji."""
        from core.image_io import RAW_EXTENSIONS
        return [p for p in self._effective_files()
                if os.path.splitext(p)[1].lower() in RAW_EXTENSIONS]

    def _effective_jpeg_files(self) -> list[str]:
        """Zwraca ścieżki efektywnych plików JPEG (zaznaczone lub bieżący)."""
        return [p for p in self._effective_files()
                if os.path.splitext(p)[1].lower() in {'.jpg', '.jpeg'}]

    # ─────────────────────────── Edycja w GIMP

    def _edit_in_gimp(self) -> None:
        """Otwiera wybrany JPG w GIMP (tryb interaktywny).
        User zapisuje przez File > Export As / Overwrite.
        QFileSystemWatcher na JPG odświeża miniaturę przy każdym eksporcie.
        """
        if self._sd_mode:
            return
        jpgs = self._effective_jpeg_files()
        if not jpgs:
            return
        if (self._gimp_process and
                self._gimp_process.state() != QProcess.ProcessState.NotRunning):
            from ui.dialogs.gimp_running_dialog import GimpRunningDialog
            GimpRunningDialog(self).exec()
            return

        jpg_path = jpgs[0]
        self._gimp_jpg_path = jpg_path
        self.btn_edit_gimp.setEnabled(False)

        self._gimp_process = QProcess(self)
        self._gimp_process.finished.connect(self._on_gimp_finished)
        # Otwórz JPG bezpośrednio — user zapisuje przez File > Export As / Overwrite
        self._gimp_process.start('gimp', ['--new-instance', '--no-splash', jpg_path])

        if not self._gimp_process.waitForStarted(3000):
            self._show_status(self.tr("⚠ Cannot start GIMP"), 6000)
            self._gimp_process  = None
            self._gimp_jpg_path = None
            self.update_selection_count()
            return

        # Obserwuj oryginalny JPG — miniatura aktualizuje się przy File > Export w trakcie
        self._gimp_watcher = QFileSystemWatcher([jpg_path], self)
        self._gimp_watcher.fileChanged.connect(self._on_gimp_jpg_changed)

    def _on_gimp_jpg_changed(self, path: str) -> None:
        """JPG zmieniony przez GIMP (File > Export) — debounce 500 ms, odśwież miniaturę.

        QFileSystemWatcher traci obserwację gdy plik zostaje usunięty i odtworzony
        (atomiczny zapis) — przywracamy addPath po 300 ms.
        """
        QTimer.singleShot(300, lambda: (
            self._gimp_watcher.addPath(path)
            if self._gimp_watcher and path not in self._gimp_watcher.files()
            else None
        ))
        # Debounce — odśwież miniaturę 500 ms po ostatniej zmianie pliku
        if self._gimp_export_timer:
            self._gimp_export_timer.stop()
        else:
            self._gimp_export_timer = QTimer(self)
            self._gimp_export_timer.setSingleShot(True)
            self._gimp_export_timer.timeout.connect(
                lambda: self._refresh_thumbnail(path)
            )
        self._gimp_export_timer.start(500)

    def _on_gimp_finished(self, exit_code: int, exit_status) -> None:
        """Proces GIMP zakończony — odśwież miniaturę jeśli plik był eksportowany."""
        jpg_path = self._gimp_jpg_path

        # Cleanup watchera i timera przed odświeżeniem
        if self._gimp_watcher:
            self._gimp_watcher.deleteLater()
            self._gimp_watcher = None
        if self._gimp_export_timer:
            self._gimp_export_timer.stop()
            self._gimp_export_timer = None

        self._gimp_jpg_path = None
        self._gimp_process  = None

        # Odśwież miniaturę po zakończeniu — quit-hook już zapisał plik
        if jpg_path:
            QTimer.singleShot(300, lambda: self._refresh_thumbnail(jpg_path))

        self.update_selection_count()

    def _refresh_thumbnail(self, path: str) -> None:
        """Unieważnia miniaturę i odświeża ikonę w liście oraz podgląd."""
        from pathlib import Path
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_PATH_ROLE) == path:
                try:
                    pixmap = self.darkcache.get_pixmap(
                        Path(path), self.large_thumbs, force=True
                    )
                except TypeError:
                    pixmap = self.darkcache.get_pixmap(Path(path), self.large_thumbs)
                if pixmap and not pixmap.isNull():
                    item.setIcon(QIcon(pixmap))
                break
        # Przeładuj podgląd jeśli to aktualnie wyświetlany plik
        if path == self.current_image_path:
            if self._loader and self._loader.isRunning():
                self._loader.wait()
            self._loader = ImageLoader(path)
            self._loader.loaded.connect(self._on_image_loaded)
            self._loader.start()

    # ─────────────────────────── Zarządzanie katalogami

    def _make_dir(self) -> None:
        """Tworzy podkatalog w bieżącym folderze."""
        if not self.current_dir or self._sd_mode:
            return
        name, ok = QInputDialog.getText(
            self, self.tr("Make Directory"), self.tr("Directory name:")
        )
        if not ok or not name.strip():
            return
        path = os.path.join(self.current_dir, name.strip())
        try:
            os.makedirs(path, exist_ok=False)
            self._show_status(
                self.tr(f"Created: {name.strip()}"), 3000
            )
        except FileExistsError:
            QMessageBox.warning(
                self, self.tr("Make Directory"),
                self.tr(f"Directory '{name.strip()}' already exists.")
            )
        except Exception as e:
            QMessageBox.warning(self, self.tr("Make Directory"), str(e))

    def _delete_dir(self) -> None:
        """Usuwa wybrany podkatalog bieżącego folderu."""
        if not self.current_dir or self._sd_mode:
            return
        target = QFileDialog.getExistingDirectory(
            self, self.tr("Delete Directory"), self.current_dir
        )
        if not target:
            return
        # Tylko podkatalogi bieżącego folderu — zabezpieczenie przed usunięciem roota
        real_current = os.path.realpath(self.current_dir)
        real_target  = os.path.realpath(target)
        if not real_target.startswith(real_current + os.sep):
            QMessageBox.warning(
                self, self.tr("Delete Directory"),
                self.tr("Only subdirectories of the current folder can be deleted.")
            )
            return
        reply = QMessageBox.question(
            self,
            self.tr("Delete Directory"),
            self.tr(
                "Delete '{}' and all its contents?".format(
                    os.path.basename(target)
                )
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            import shutil
            shutil.rmtree(real_target)
            self._show_status(
                self.tr(f"Deleted: {os.path.basename(target)}"), 4000
            )
        except Exception as e:
            QMessageBox.warning(self, self.tr("Delete Directory"), str(e))

    def _on_develop_requested(self):
        """Emituje sygnał develop_requested z katalogiem bieżącym."""
        if self.current_dir:
            self.develop_requested.emit(self.current_dir)

    def _copy_or_move_selected(self, move: bool = False):
        """Kopiuje lub przenosi zaznaczone pliki do wybranego folderu."""
        import shutil

        source_paths = self._effective_files()
        if not source_paths:
            return

        dest_dir = QFileDialog.getExistingDirectory(
            self,
            self.tr("Move to folder") if move else self.tr("Copy to folder"),
            self.current_dir or os.path.expanduser("~"),
        )
        if not dest_dir:
            return

        errors = []
        moved_paths: set[str] = set()
        for src in source_paths:
            if not os.path.isfile(src):
                continue
            dest = os.path.join(dest_dir, os.path.basename(src))
            try:
                if move:
                    shutil.move(src, dest)
                    moved_paths.add(src)
                    if src == self.current_image_path:
                        self.preview.clear()
                        self.current_image_path = None
                else:
                    shutil.copy2(src, dest)
            except Exception as e:
                errors.append(f"{os.path.basename(src)}: {e}")

        if move and moved_paths:
            for i in range(self.list_widget.count() - 1, -1, -1):
                item = self.list_widget.item(i)
                p = item.data(_ITEM_PATH_ROLE) or item.data(Qt.ItemDataRole.UserRole)
                if p in moved_paths:
                    self.list_widget.takeItem(i)

        if errors:
            QMessageBox.warning(
                self,
                self.tr("Move to folder") if move else self.tr("Copy to folder"),
                "\n".join(errors[:5])
            )
        else:
            n = len(source_paths) - len(errors)
            verb = self.tr("Moved") if move else self.tr("Copied")
            self._show_status(self.tr(f"{verb} {n} file(s) → {dest_dir}"), 4000)

        self.update_selection_count()

    def _on_edit_xmp_file(self, xmp_path: str):
        """Dialog edycji inline wybranego pliku XMP."""
        from PyQt6.QtWidgets import QTextEdit as _QTextEdit
        from PyQt6.QtGui import QFont

        try:
            content = open(xmp_path, encoding="utf-8").read()
        except OSError as e:
            QMessageBox.warning(self, self.tr("Read error"), str(e))
            return

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout as _QHBoxLayout

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Edit XMP — {os.path.basename(xmp_path)}")
        dlg.setMinimumSize(640, 480)
        lay = QVBoxLayout(dlg)

        lbl = QLabel(xmp_path)
        lbl.setStyleSheet("color: #888; font-size: 11px;")
        lay.addWidget(lbl)

        editor = _QTextEdit()
        font = QFont("Monospace")
        font.setPointSize(9)
        editor.setFont(font)
        editor.setPlainText(content)
        lay.addWidget(editor, 1)

        btn_row = _QHBoxLayout()
        btn_save   = QPushButton(self.tr("Save"))
        btn_save.setFixedHeight(32)
        btn_cancel = QPushButton(self.tr("Cancel"))
        btn_cancel.setFixedHeight(32)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        lay.addLayout(btn_row)

        btn_cancel.clicked.connect(dlg.reject)

        def _save():
            try:
                open(xmp_path, "w", encoding="utf-8").write(editor.toPlainText())
                dlg.accept()
            except OSError as e:
                QMessageBox.warning(dlg, self.tr("Save error"), str(e))

        btn_save.clicked.connect(_save)
        btn_save.setDefault(True)
        dlg.exec()

    # ─────────────────────────── Tłumaczenia

    def retranslateUi(self):
        self.btn_sessions.setText(self.tr("Sessions"))
        self.btn_last_session.setText(self.tr("Last Session"))
        self.btn_delete.setText(self.tr("Delete"))
        if not self.current_image_path:
            self.preview.clear()
        self.update_selection_count()
