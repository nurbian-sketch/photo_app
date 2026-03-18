from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QMessageBox, QFileDialog, QSizePolicy, QSplitter,
    QStyledItemDelegate, QStyle, QStyleOptionButton, QApplication, QMenu,
    QGroupBox, QToolButton
)
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import Qt, QSize, QTimer, QRect, pyqtSignal

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
    wb_apply_requested = pyqtSignal(int)  # kelvin

    JPEG_EXTENSIONS      = ('.jpg', '.jpeg')
    RAW_EXTENSIONS_TUPLE = ('.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng')

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_dir        = None
        self.current_image_path = None
        self.large_thumbs       = False
        self._hide_raw          = False
        self._hide_jpeg         = False
        self._filter_state      = 'all'
        self._sort_key          = 'name'   # 'name' | 'date' | 'type'
        self._sd_card_ready     = False
        self._sd_mode           = False
        self._loader            = None
        self._browser_worker    = None
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

        self.setup_ui()
        QTimer.singleShot(500, self.open_last_session)

    # ─────────────────────────── UI

    def setup_ui(self):
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
        self.list_widget.customContextMenuRequested.connect(self._show_sort_menu)
        left_layout.addWidget(self.list_widget, 1)

        # Panel prawy: podgląd + kontrolki
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(6)

        self.preview = PreviewPanel()
        right_layout.addWidget(self.preview, 1)

        BTN_H = 28

        # Wiersz grup — wszystkie w jednym QHBoxLayout ze stretch na końcu
        groups_row = QHBoxLayout()
        groups_row.setSpacing(8)
        groups_row.setContentsMargins(0, 0, 0, 0)

        # ── Grupa 1: Location ────────────────────────────────────────────────
        grp_loc = QGroupBox(self.tr("Location"))
        grp_loc.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_loc = QHBoxLayout(grp_loc)
        row_loc.setContentsMargins(6, 4, 6, 4)
        row_loc.setSpacing(4)

        self.btn_sessions     = QPushButton(self.tr("Sessions"))
        self.btn_last_session = QPushButton(self.tr("Last Session"))
        self.btn_open_folder  = QPushButton(self.tr("Open Folder…"))
        self.btn_sd_card      = QPushButton(self.tr("SD Card"))
        self.btn_sd_card.setVisible(False)

        for btn in [self.btn_sessions, self.btn_last_session,
                    self.btn_open_folder, self.btn_sd_card]:
            btn.setMinimumHeight(BTN_H)
            row_loc.addWidget(btn)

        groups_row.addWidget(grp_loc)

        # ── Grupa 2: View ─────────────────────────────────────────────────────
        grp_view = QGroupBox(self.tr("View"))
        grp_view.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_view = QHBoxLayout(grp_view)
        row_view.setContentsMargins(6, 4, 6, 4)
        row_view.setSpacing(4)

        # Dropdown filtru — klik = cykliczne, strzałka = menu z checkmarkami
        self.btn_filter = QToolButton()
        self.btn_filter.setMinimumHeight(BTN_H)
        self.btn_filter.setMinimumWidth(90)
        self.btn_filter.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_filter.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        filter_menu = QMenu(self)
        self._action_filter_all  = filter_menu.addAction(self.tr("All Files"))
        self._action_filter_jpeg = filter_menu.addAction(self.tr("JPEG Only"))
        self._action_filter_raw  = filter_menu.addAction(self.tr("RAW Only"))
        for a in [self._action_filter_all, self._action_filter_jpeg,
                  self._action_filter_raw]:
            a.setCheckable(True)
        self._action_filter_all.setChecked(True)
        self.btn_filter.setMenu(filter_menu)
        self.btn_filter.setText(self.tr("All Files"))
        self.btn_filter.clicked.connect(self._cycle_filter)
        self._action_filter_all.triggered.connect(lambda: self._set_filter('all'))
        self._action_filter_jpeg.triggered.connect(lambda: self._set_filter('jpeg'))
        self._action_filter_raw.triggered.connect(lambda: self._set_filter('raw'))

        # Toggle rozmiar miniatur — prosty przycisk, etykieta = przyszły stan
        self.btn_toggle_size = QPushButton(self.tr("Large Thumbs"))
        self.btn_toggle_size.setMinimumHeight(BTN_H)

        row_view.addWidget(self.btn_filter)
        row_view.addWidget(self.btn_toggle_size)

        groups_row.addWidget(grp_view)

        # ── Grupa 3: Operations ───────────────────────────────────────────────
        grp_ops = QGroupBox(self.tr("Operations"))
        grp_ops.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        row_ops = QHBoxLayout(grp_ops)
        row_ops.setContentsMargins(6, 4, 6, 4)
        row_ops.setSpacing(4)

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

        self.btn_open_darktable = QPushButton(self.tr("Edit…"))
        self.btn_open_darktable.setMinimumHeight(BTN_H)
        self.btn_open_darktable.setIcon(QIcon.fromTheme("darktable"))
        self.btn_open_darktable.setEnabled(False)

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
        # klik = wyślij jako plik (bezstratnie)
        self.btn_send.clicked.connect(lambda: self._send_via_telegram())
        self._action_telegram_config.triggered.connect(self._configure_telegram)

        self.btn_delete = QPushButton(self.tr("Delete Selected"))
        self.btn_delete.setMinimumHeight(BTN_H)
        self.btn_delete.setEnabled(False)

        # SD card only — domyślnie ukryte
        self.btn_copy_to_disk = QPushButton(self.tr("Copy to Disk"))
        self.btn_copy_to_disk.setMinimumHeight(BTN_H)
        self.btn_copy_to_disk.setEnabled(False)
        self.btn_copy_to_disk.setVisible(False)

        self.btn_format_card = QPushButton(self.tr("Format Card"))
        self.btn_format_card.setMinimumHeight(BTN_H)
        self.btn_format_card.setStyleSheet(BTN_STYLE_RED)
        self.btn_format_card.setVisible(False)

        for w in [self.btn_select, self.btn_send, self.btn_delete,
                  self.btn_copy_to_disk, self.btn_format_card, self.btn_open_darktable]:
            row_ops.addWidget(w)

        groups_row.addWidget(grp_ops)
        groups_row.addStretch()
        right_layout.addLayout(groups_row)

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
        self.btn_open_darktable.clicked.connect(self._open_in_darktable)
        self.btn_sd_card.clicked.connect(self._open_sd_card)

        self.btn_filter.clicked.connect(self._cycle_filter)
        self.btn_toggle_size.clicked.connect(self.toggle_thumb_size)
        self.btn_delete.clicked.connect(self.delete_images)
        self.btn_copy_to_disk.clicked.connect(self._copy_to_disk)
        self.btn_format_card.clicked.connect(self._format_card)

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
        """Otwiera najnowszy podfolder w katalogu sesji."""
        from ui.dialogs.preferences_dialog import PreferencesDialog
        base_path     = PreferencesDialog.get_session_directory()
        captures_name = PreferencesDialog.get_captures_subdir()
        if not base_path:
            return
        os.makedirs(base_path, exist_ok=True)
        try:
            all_ext = self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE
            subdirs = [
                os.path.join(base_path, d)
                for d in os.listdir(base_path)
                if os.path.isdir(os.path.join(base_path, d))
                and d != captures_name
                and any(
                    f.lower().endswith(all_ext)
                    for f in os.listdir(os.path.join(base_path, d))
                )
            ]
            target = max(subdirs, key=os.path.getmtime) if subdirs else base_path
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
        self.current_dir = folder
        self.timer.stop()
        self.list_widget.clear()
        self.preview.clear()
        self.current_image_path = None
        self._list_file_offset  = 0

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
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        item = QListWidgetItem(icon, name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE, 'folder')
        item.setToolTip(path)
        self.list_widget.addItem(item)

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
        self.btn_open_darktable.setVisible(False)
        self.btn_open_darktable.setEnabled(False)
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
        self.btn_open_darktable.setVisible(True)
        self.btn_open_darktable.setEnabled(False)
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

        # Plik
        self.current_image_path = path if not self._sd_mode else None

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

    def _navigate_to(self, path: str):
        self.load_images(path)

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
        to_delete = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if (item.data(_ITEM_TYPE_ROLE) == 'file'
                    and item.data(Qt.ItemDataRole.UserRole + 1)):
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

    def _show_sort_menu(self, pos):
        """Menu kontekstowe Sort By na prawym kliku w liście miniatur."""
        menu = QMenu(self)
        labels = [
            ('name', self.tr("Sort by Name")),
            ('date', self.tr("Sort by Date")),
            ('type', self.tr("Sort by Type")),
        ]
        for key, label in labels:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._sort_key == key)
            action.setData(key)
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen:
            self.set_sort(chosen.data())

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
        """
        Zwraca ścieżki zaznaczonych plików.
        W trybie SD: lokalne ścieżki do plików tymczasowych.
        W trybie dysk: bezpośrednie ścieżki z systemu plików.
        """
        paths = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if (item.data(_ITEM_TYPE_ROLE) == 'file'
                    and item.data(Qt.ItemDataRole.UserRole + 1)):
                if self._sd_mode:
                    local = item.data(_SD_LOCAL_PATH_ROLE)
                    if local and os.path.isfile(local):
                        paths.append(local)
                else:
                    path = item.data(Qt.ItemDataRole.UserRole)
                    if path and os.path.isfile(path):
                        paths.append(path)
        return paths

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

        # btn_delete aktywny zawsze gdy coś zaznaczone
        self.btn_delete.setEnabled(count > 0)
        # btn_copy_to_disk — aktywny w SD mode gdy coś zaznaczone
        if self._sd_mode:
            self.btn_copy_to_disk.setEnabled(count > 0)
        # btn_open_darktable — aktywny w trybie dysk gdy coś zaznaczone
        if not self._sd_mode:
            self.btn_open_darktable.setEnabled(count > 0)
        # btn_send — aktywny gdy coś zaznaczone (oba tryby)
        self.btn_send.setEnabled(count > 0)

    # ─────────────────────────── Cleanup

    def closeEvent(self, event):
        self._exit_sd_mode()
        if self._loader and self._loader.isRunning():
            self._loader.wait()
        super().closeEvent(event)

    # ─────────────────────────── Tłumaczenia

    def retranslateUi(self):
        self.btn_sessions.setText(self.tr("Sessions"))
        self.btn_last_session.setText(self.tr("Last Session"))
        self.btn_delete.setText(self.tr("Delete"))
        if not self.current_image_path:
            self.preview.clear()
        self.update_selection_count()
