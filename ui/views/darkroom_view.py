from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QMessageBox, QFileDialog, QSizePolicy, QSplitter,
    QStyledItemDelegate, QStyle, QStyleOptionButton, QApplication
)
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import Qt, QSize, QTimer, QRect, pyqtSignal

import os
from pathlib import Path

from core.darkcache.cache_manager import PreviewCache
from core.darkcache.preview_generator import PreviewGenerator
from core.darkcache.thumbnail_reader import ExifThumbnailReader
from core.darkcache.service import DarkCacheService
from ui.widgets.preview_panel import PreviewPanel
from ui.widgets.photo_preview_dialog import PhotoPreviewDialog
from core.image_io import ImageLoader


# Rola typu elementu listy: 'file', 'folder', 'parent'
_ITEM_TYPE_ROLE  = Qt.ItemDataRole.UserRole + 2
# Rola przechowująca folder PTP (tylko w trybie SD card)
_PTP_FOLDER_ROLE = Qt.ItemDataRole.UserRole + 3


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
                return True
        return super().editorEvent(event, model, option, index)


class DarkroomView(QWidget):

    # Emitowany po zaakceptowaniu WB picker
    wb_apply_requested = pyqtSignal(int)  # kelvin

    JPEG_EXTENSIONS      = ('.jpg', '.jpeg', '.png')
    RAW_EXTENSIONS_TUPLE = ('.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng')

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_dir        = None
        self.current_image_path = None
        self.large_thumbs       = False
        self._hide_raw          = False
        self._hide_jpeg         = False
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
        self.list_widget.setStyleSheet("QListWidget { background-color: #1e1e1e; }")
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.itemClicked.connect(self.show_image)
        self.list_widget.currentItemChanged.connect(
            lambda cur, prev: self.show_image(cur) if cur else None
        )
        self.list_widget.itemDoubleClicked.connect(self._open_preview_dialog)
        self.list_widget.setItemDelegate(CheckboxDelegate(self.list_widget))
        left_layout.addWidget(self.list_widget, 1)

        # Panel prawy: podgląd + kontrolki
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(6)

        self.preview = PreviewPanel()
        right_layout.addWidget(self.preview, 1)

        # Wiersz 1: nawigacja lokacji
        row_nav = QHBoxLayout()
        self.btn_sessions      = QPushButton(self.tr("Sessions"))
        self.btn_last_session  = QPushButton(self.tr("Last Session"))
        self.btn_sd_card       = QPushButton(self.tr("SD Card"))
        self.btn_sd_card.setVisible(False)
        for btn in [self.btn_sessions, self.btn_last_session, self.btn_sd_card]:
            btn.setMinimumHeight(32)
            btn.setMaximumWidth(150)
            row_nav.addWidget(btn)
        row_nav.addStretch()
        right_layout.addLayout(row_nav)

        # Wiersz 2: opcje widoku
        row_view = QHBoxLayout()
        self.btn_hide_raw = QPushButton(self.tr("Hide RAW"))
        self.btn_hide_raw.setCheckable(True)
        self.btn_hide_raw.setMaximumWidth(100)
        self.btn_hide_raw.setMinimumHeight(32)

        self.btn_hide_jpeg = QPushButton(self.tr("Hide JPEG"))
        self.btn_hide_jpeg.setCheckable(True)
        self.btn_hide_jpeg.setMaximumWidth(100)
        self.btn_hide_jpeg.setMinimumHeight(32)

        self.btn_toggle_size = QPushButton(self.tr("Large Thumbs"))
        self.btn_toggle_size.setMaximumWidth(130)
        self.btn_toggle_size.setMinimumHeight(32)

        self.btn_delete = QPushButton(self.tr("Delete"))
        self.btn_delete.setMaximumWidth(100)
        self.btn_delete.setMinimumHeight(32)

        for btn in [self.btn_hide_raw, self.btn_hide_jpeg,
                    self.btn_toggle_size, self.btn_delete]:
            row_view.addWidget(btn)
        row_view.addStretch()
        right_layout.addLayout(row_view)

        # Wiersz 3: akcje SD card (widoczny tylko w trybie SD)
        self._sd_bar = QWidget()
        row_sd = QHBoxLayout(self._sd_bar)
        row_sd.setContentsMargins(0, 0, 0, 0)
        row_sd.setSpacing(6)

        self.btn_select_all   = QPushButton(self.tr("Select All"))
        self.btn_deselect_all = QPushButton(self.tr("Deselect All"))
        self.btn_copy_to_disk = QPushButton(self.tr("Copy to Disk"))
        self.btn_format_card  = QPushButton(self.tr("Format Card"))

        self.btn_copy_to_disk.setStyleSheet(
            "background-color: #1565c0; color: white; font-weight: bold;"
        )
        self.btn_format_card.setStyleSheet(
            "background-color: #b71c1c; color: white; font-weight: bold;"
        )

        for btn in [self.btn_select_all, self.btn_deselect_all,
                    self.btn_copy_to_disk, self.btn_format_card]:
            btn.setMinimumHeight(32)
            btn.setMaximumWidth(140)
            row_sd.addWidget(btn)
        row_sd.addStretch()

        self._sd_bar.setVisible(False)
        right_layout.addWidget(self._sd_bar)

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
        self.btn_sd_card.clicked.connect(self._open_sd_card)

        self.btn_hide_raw.clicked.connect(self._on_hide_raw_toggled)
        self.btn_hide_jpeg.clicked.connect(self._on_hide_jpeg_toggled)
        self.btn_toggle_size.clicked.connect(self.toggle_thumb_size)
        self.btn_delete.clicked.connect(self.delete_images)

        self.btn_select_all.clicked.connect(self._select_all)
        self.btn_deselect_all.clicked.connect(self._deselect_all)
        self.btn_copy_to_disk.clicked.connect(self._copy_to_disk)
        self.btn_format_card.clicked.connect(self._format_card)

        self.preview.wb_applied.connect(self._on_wb_applied)

    # ─────────────────────────── Filtr widoku

    def _on_hide_raw_toggled(self, checked: bool):
        self._hide_raw = checked
        if checked:
            self._hide_jpeg = False
            self.btn_hide_jpeg.setChecked(False)
            self.btn_hide_jpeg.setEnabled(False)
        else:
            self.btn_hide_jpeg.setEnabled(True)
        self._reload_current()

    def _on_hide_jpeg_toggled(self, checked: bool):
        self._hide_jpeg = checked
        if checked:
            self._hide_raw = False
            self.btn_hide_raw.setChecked(False)
            self.btn_hide_raw.setEnabled(False)
        else:
            self.btn_hide_raw.setEnabled(True)
        self._reload_current()

    def _reload_current(self):
        if self.current_dir and not self._sd_mode:
            self.load_images(self.current_dir)

    @property
    def _active_extensions(self) -> tuple:
        if self._hide_raw:
            return self.JPEG_EXTENSIONS
        if self._hide_jpeg:
            return self.RAW_EXTENSIONS_TUPLE
        return self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE

    # ─────────────────────────── Nawigacja / sesje

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

        # Pliki obrazów wg filtru
        try:
            self.files = sorted(
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if f.lower().endswith(self._active_extensions)
            )
        except PermissionError:
            self.files = []

        if not self.files:
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
        from core.camera_card_browser import CameraCardBrowserWorker

        self._sd_mode = True
        self.timer.stop()
        self.list_widget.clear()
        self.preview.clear()
        self.current_image_path = None
        self.files              = []
        self._list_file_offset  = 0

        self.lbl_path.setText(self.tr("📷 Camera Card  —  scanning…"))
        self._sd_bar.setVisible(True)
        self.btn_sd_card.setEnabled(False)

        # Nawigacja powrotna
        self._add_nav_item("← Sessions", '__sessions__')
        self._list_file_offset += 1

        self._browser_worker = CameraCardBrowserWorker()
        self._browser_worker.file_found.connect(self._on_card_file_found)
        self._browser_worker.scan_finished.connect(self._on_card_scan_finished)
        self._browser_worker.start()

    def _on_card_file_found(self, ptp_folder: str, filename: str, pixmap: QPixmap):
        icon = QIcon(pixmap) if pixmap and not pixmap.isNull() else QIcon()
        item = QListWidgetItem(icon, filename)
        item.setData(Qt.ItemDataRole.UserRole, filename)
        item.setData(_PTP_FOLDER_ROLE, ptp_folder)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE, 'file')
        self.list_widget.addItem(item)

        # Zaznacz i pokaż pierwszy plik
        if self.list_widget.count() == 2:
            self.list_widget.setCurrentItem(item)

    def _on_card_scan_finished(self, total: int, error: str):
        self.btn_sd_card.setEnabled(True)
        if error:
            QMessageBox.warning(
                self, self.tr("SD Card"),
                self.tr(f"Scan error: {error}")
            )
        else:
            self.lbl_path.setText(self.tr(f"📷 Camera Card  —  {total} files"))

    def _exit_sd_mode(self):
        if self._browser_worker and self._browser_worker.isRunning():
            self._browser_worker.abort()
            self._browser_worker.wait()
        self._browser_worker = None
        self._sd_mode = False
        self._sd_bar.setVisible(False)

    # ─────────────────────────── SD Card — selekcja

    def _select_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_TYPE_ROLE) == 'file':
                item.setData(Qt.ItemDataRole.UserRole + 1, True)
        self.list_widget.update()
        self.update_selection_count()

    def _deselect_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_TYPE_ROLE) == 'file':
                item.setData(Qt.ItemDataRole.UserRole + 1, False)
        self.list_widget.update()
        self.update_selection_count()

    def _get_selected_sd_files(self) -> list:
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
        self.preview.set_message(self.tr("Loading…"))

        if self._loader and self._loader.isRunning():
            try:
                self._loader.loaded.disconnect()
            except RuntimeError:
                pass
            self._loader.wait()
        self._loader = None

        if not self._sd_mode:
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
        if self._sd_mode:
            return

        to_delete = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if (item.data(_ITEM_TYPE_ROLE) == 'file'
                    and item.data(Qt.ItemDataRole.UserRole + 1)):
                to_delete.append((i, item, item.data(Qt.ItemDataRole.UserRole)))

        if not to_delete:
            QMessageBox.information(
                self, self.tr("Delete"), self.tr("No images selected.")
            )
            return

        reply = QMessageBox.question(
            self,
            self.tr("Delete"),
            self.tr("Delete {0} file(s)?").format(len(to_delete)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        errors = []
        for i, item, path in reversed(to_delete):
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
        self.update_selection_count()

    # ─────────────────────────── Rozmiar miniatur

    def toggle_thumb_size(self):
        prev_path = self.current_image_path
        self.large_thumbs = not self.large_thumbs
        if self.large_thumbs:
            self.list_widget.setIconSize(QSize(240, 240))
            self.list_widget.setGridSize(QSize(260, 280))
            self.btn_toggle_size.setText(self.tr("Small Thumbs"))
        else:
            self.list_widget.setIconSize(QSize(120, 120))
            self.list_widget.setGridSize(QSize(140, 155))
            self.btn_toggle_size.setText(self.tr("Large Thumbs"))
        if self.current_dir and not self._sd_mode:
            self.load_images(self.current_dir, select_path=prev_path)

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
