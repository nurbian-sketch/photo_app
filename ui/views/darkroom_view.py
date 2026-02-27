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
_ITEM_TYPE_ROLE = Qt.ItemDataRole.UserRole + 2


class CheckboxDelegate(QStyledItemDelegate):
    """Custom delegate z checkboxem w rogu miniatury (tylko dla plików)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkbox_size = 20
        self.checkbox_margin_x = 16
        self.checkbox_margin_y = 8

    def paint(self, painter, option, index):
        super().paint(painter, option, index)

        # Checkbox tylko dla plików
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

        if is_checked:
            checkbox_option.state |= QStyle.StateFlag.State_On
        else:
            checkbox_option.state |= QStyle.StateFlag.State_Off

        checkbox_option.state |= QStyle.StateFlag.State_Enabled

        self.parent().style().drawControl(
            QStyle.ControlElement.CE_CheckBox,
            checkbox_option,
            painter
        )

    def editorEvent(self, event, model, option, index):
        # Checkbox tylko dla plików
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

    # Emitowany gdy user klika "SD Card" — MainWindow obsługuje pobieranie plików
    sd_card_requested = pyqtSignal()
    # Emitowany po zaakceptowaniu WB picker — MainWindow przełącza na Camera i aplikuje WB
    wb_apply_requested = pyqtSignal(int)  # kelvin

    # Tryby wyświetlania plików
    _VIEW_LABELS = ["JPG only", "JPG + RAW", "All files"]

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_dir = None
        self.current_image_path = None
        self.large_thumbs = False
        self._view_mode = 0          # 0=JPG, 1=JPG+RAW, 2=All files
        self._list_file_offset = 0   # ile elementów nav (.. + foldery) przed plikami
        self._sd_card_ready = False
        self._loader = None

        # Cache
        self.cache_dir = os.path.expanduser("~/.cache/photo_app/previews")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache = PreviewCache(Path(self.cache_dir))
        self.preview_generator = PreviewGenerator()
        self.thumbnail_reader = ExifThumbnailReader()
        self.darkcache = DarkCacheService(
            self.cache,
            self.preview_generator,
            self.thumbnail_reader,
        )

        # Lazy loading miniatur
        self.files = []
        self.load_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load_next_thumbnails)

        self.setup_ui()

        QTimer.singleShot(500, self.open_last_session)

    def setup_ui(self):
        # === Panel miniatur po lewej ===
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
        self.list_widget.installEventFilter(self)

        # Custom delegate z checkboxami
        self.list_widget.setItemDelegate(CheckboxDelegate(self.list_widget))

        # === Podgląd dużego obrazu po prawej ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)

        self.preview = PreviewPanel()
        right_layout.addWidget(self.preview, 1)

        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(6)

        # Label z nazwą i ścieżką katalogu
        self.lbl_folder = QLabel("")
        self.lbl_folder.setStyleSheet("color: #888; font-size: 11px; padding: 2px 4px;")
        self.lbl_folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        controls_layout.addWidget(self.lbl_folder)

        # Wiersz przycisków
        row_layout = QHBoxLayout()
        self.btn_open = QPushButton(self.tr("Open Folder"))
        self.btn_last_session = QPushButton(self.tr("Last Session"))
        self.btn_toggle_size = QPushButton(self.tr("Large Thumbs"))
        self.btn_delete = QPushButton(self.tr("Delete Image(s)"))
        self.btn_sd_card = QPushButton(self.tr("SD Card"))
        self.btn_raw_preview = QPushButton(self._VIEW_LABELS[0])
        self.btn_favorites = QPushButton(self.tr("Favorites Only"))
        self.btn_favorites.setCheckable(True)

        for btn in [self.btn_open, self.btn_last_session, self.btn_toggle_size,
                    self.btn_delete, self.btn_sd_card, self.btn_raw_preview,
                    self.btn_favorites]:
            btn.setMinimumHeight(35)
            btn.setMaximumWidth(180)
            row_layout.addWidget(btn)
        row_layout.addStretch()

        controls_layout.addLayout(row_layout)
        right_layout.addLayout(controls_layout)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.list_widget)
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.addWidget(self.splitter)

        # Sygnały
        self.btn_open.clicked.connect(self.open_folder)
        self.btn_last_session.clicked.connect(self.open_last_session)
        self.btn_delete.clicked.connect(self.delete_images)
        self.btn_toggle_size.clicked.connect(self.toggle_thumb_size)
        self.btn_raw_preview.clicked.connect(self._cycle_view_mode)
        self.btn_sd_card.setVisible(False)
        self.btn_sd_card.clicked.connect(self.sd_card_requested.emit)
        self.btn_favorites.setVisible(False)  # TODO
        self.preview.wb_applied.connect(self._on_wb_applied)

    # ─────────────────────────── Sesja

    def open_last_session(self):
        """Otwiera najnowszy podfolder w katalogu sesji, pomijając captures subdir."""
        from ui.dialogs.preferences_dialog import PreferencesDialog
        base_path = PreferencesDialog.get_session_directory()
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
            target_dir = max(subdirs, key=os.path.getmtime) if subdirs else base_path
            self.load_images(target_dir)
        except Exception as e:
            print(f"Error loading last session: {e}")

    def open_folder(self):
        from ui.dialogs.preferences_dialog import PreferencesDialog
        default_path = PreferencesDialog.get_session_directory()
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Select photo folder"), default_path
        )
        if folder:
            self.current_dir = folder
            self.load_images(folder)

    # ─────────────────────────── Rozszerzenia

    JPEG_EXTENSIONS = ('.jpg', '.jpeg', '.png')
    RAW_EXTENSIONS_TUPLE = ('.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng')

    @property
    def IMAGE_EXTENSIONS(self):
        if self._view_mode == 1:
            return self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE
        return self.JPEG_EXTENSIONS  # tryb 0 i 2 — pliki images obsługiwane osobno

    # ─────────────────────────── Ładowanie obrazów

    def load_images(self, folder, select_path: str = None):
        """Ładuje katalog. select_path — ścieżka do przywrócenia selekcji."""
        self.current_dir = folder
        self.timer.stop()
        self.list_widget.clear()
        self.preview.clear()
        self.current_image_path = None
        self._list_file_offset = 0

        folder_name = os.path.basename(folder.rstrip("/"))
        self.lbl_folder.setText(f"{folder_name}   —   {folder}")

        # Ikona ".." — wyjście do katalogu nadrzędnego (zawsze, gdy nie jesteśmy w root)
        parent = os.path.dirname(folder.rstrip("/"))
        if parent and parent != folder:
            self._add_nav_item("..", parent)
            self._list_file_offset += 1

        # Podfoldery — tylko w trybie "All files"
        if self._view_mode == 2:
            subdirs = sorted(
                d for d in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, d)) and not d.startswith('.')
            )
            for d in subdirs:
                self._add_folder_item(d, os.path.join(folder, d))
                self._list_file_offset += 1

        # Lista plików do wyświetlenia
        if self._view_mode == 2:
            # Wszystkie pliki (obrazy z miniaturami, inne z placeholderem)
            self.files = sorted(
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, f))
            )
        else:
            self.files = sorted(
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if f.lower().endswith(self.IMAGE_EXTENSIONS)
            )

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
        """Dodaje element nawigacyjny '..' do listy."""
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
        """Dodaje element folderu do listy."""
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        item = QListWidgetItem(icon, name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE, 'folder')
        item.setToolTip(path)
        self.list_widget.addItem(item)

    def _add_thumbnail_item(self, index: int):
        """Dodaje jeden element pliku do list_widget z miniaturą."""
        path = self.files[index]
        ext = os.path.splitext(path)[1].lower()
        is_image = ext in (self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE)
        if is_image:
            pixmap = self.darkcache.get_pixmap(Path(path), self.large_thumbs)
        else:
            pixmap = None
        icon = QIcon(pixmap) if pixmap and not pixmap.isNull() else QIcon()
        item = QListWidgetItem(icon, os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        item.setData(_ITEM_TYPE_ROLE, 'file')
        self.list_widget.addItem(item)

    def load_next_thumbnails(self):
        """Ładuje jedno zdjęcie per tick (responsywność)."""
        if self.load_index >= len(self.files):
            self.timer.stop()
            return
        self._add_thumbnail_item(self.load_index)
        self.load_index += 1

    def start_camera_import(self, dest_dir: str, worker):
        """Importuje pliki z karty aparatu — thumbnails pojawiają się jeden po drugim."""
        self.timer.stop()
        self.list_widget.clear()
        self.preview.clear()
        self.current_image_path = None
        self.files = []
        self.current_dir = dest_dir
        self._list_file_offset = 0

        self.lbl_folder.setText(f"📷 Camera Import  —  {dest_dir}")

        self._camera_worker = worker
        worker.file_ready.connect(self._on_camera_file_ready)
        worker.start()

    def _on_camera_file_ready(self, local_path: str):
        """Dodaje nowo pobrany plik z karty do listy miniatur."""
        self.files.append(local_path)
        self._add_thumbnail_item(len(self.files) - 1)
        if self.list_widget.count() == 1:
            self._select_and_show(0)

    # ─────────────────────────── Wyświetlanie podglądu / nawigacja

    def show_image(self, item):
        """Wyświetla podgląd lub nawiguje do folderu/katalogu nadrzędnego."""
        if item is None:
            return
        item_type = item.data(_ITEM_TYPE_ROLE)
        path = item.data(Qt.ItemDataRole.UserRole)

        if item_type in ('folder', 'parent'):
            self._navigate_to(path)
            return

        # Zwykły plik — załaduj podgląd
        self.current_image_path = path
        self.preview.set_message(self.tr("Loading…"))

        if self._loader and self._loader.isRunning():
            try:
                self._loader.loaded.disconnect()
            except RuntimeError:
                pass
            self._loader.wait()
        self._loader = None

        self._loader = ImageLoader(path)
        self._loader.loaded.connect(self._on_image_loaded)
        self._loader.start()

    def _navigate_to(self, path: str):
        """Przejdź do folderu — przeładuj widok."""
        self.load_images(path)

    def _on_image_loaded(self, pixmap: QPixmap, exif: dict):
        """Callback z ImageLoader — deleguje do PreviewPanel."""
        self.preview.set_pixmap(pixmap, exif.get('orientation', 0))
        self.preview.set_exif(exif)

    def _select_and_show(self, index: int):
        """Zaznacza element pliku (z uwzględnieniem offsetu nav) i wyświetla podgląd."""
        item = self.list_widget.item(self._list_file_offset + index)
        if item:
            self.list_widget.setCurrentItem(item)
            self.show_image(item)

    def eventFilter(self, obj, event):
        return super().eventFilter(obj, event)

    # ─────────────────────────── WB Picker / podgląd pełny

    def _open_preview_dialog(self, item):
        """Double-click — dla pliku otwiera pełny podgląd, dla folderu nawiguje."""
        item_type = item.data(_ITEM_TYPE_ROLE)
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        if item_type in ('folder', 'parent'):
            self._navigate_to(path)
            return
        self._open_preview_dialog_for_path(path)

    def _open_preview_dialog_for_path(self, path: str):
        """Otwiera PhotoPreviewDialog dla podanej ścieżki."""
        dialog = PhotoPreviewDialog(path, parent=None)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.wb_applied.connect(self._on_wb_applied)
        dialog.show()

    def _on_wb_applied(self, kelvin: int):
        """Callback z PhotoPreviewDialog — emituje sygnał do MainWindow."""
        self.wb_apply_requested.emit(kelvin)

    # ─────────────────────────── Usuwanie

    def delete_images(self):
        """Usuń zaznaczone zdjęcia (checkboxy) — tylko pliki."""
        to_delete = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(_ITEM_TYPE_ROLE) == 'file' and item.data(Qt.ItemDataRole.UserRole + 1):
                path = item.data(Qt.ItemDataRole.UserRole)
                to_delete.append((i, item, path))

        if not to_delete:
            QMessageBox.information(
                self,
                self.tr("Delete Image(s)"),
                self.tr("No images selected")
            )
            return

        reply = QMessageBox.question(
            self,
            self.tr("Delete Image(s)"),
            self.tr("Are you sure you want to delete {0} file(s)?").format(len(to_delete)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            deleted_count = 0
            errors = []

            for i, item, path in reversed(to_delete):
                try:
                    os.remove(path)
                    self.list_widget.takeItem(i)
                    deleted_count += 1

                    if path == self.current_image_path:
                        self.preview.clear()
                        self.current_image_path = None

                except Exception as e:
                    errors.append(f"{os.path.basename(path)}: {e}")

            if errors:
                QMessageBox.warning(
                    self,
                    self.tr("Delete Image(s)"),
                    self.tr("Deleted {0} file(s). Errors:\n{1}").format(
                        deleted_count,
                        "\n".join(errors[:5])
                    )
                )

            self.update_selection_count()

    # ─────────────────────────── Tryb wyświetlania plików

    def _cycle_view_mode(self):
        """Cykluje między trybami: JPG only → JPG+RAW → All files → JPG only."""
        prev_path = self.current_image_path
        self._view_mode = (self._view_mode + 1) % 3
        self.btn_raw_preview.setText(self._VIEW_LABELS[self._view_mode])
        if self.current_dir:
            self.load_images(self.current_dir, select_path=prev_path)

    # ─────────────────────────── SD Card

    def set_sd_card_ready(self, ready: bool):
        """Wywoływane przez MainWindow gdy probe wykryje / utraci kartę SD."""
        self._sd_card_ready = ready
        self.btn_sd_card.setVisible(ready)

    # ─────────────────────────── Rozmiar miniatur

    def toggle_thumb_size(self):
        """Przełącz między małymi (thumbnail) a dużymi (preview) miniaturami."""
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

        if self.current_dir:
            self.load_images(self.current_dir, select_path=prev_path)

    # ─────────────────────────── Selekcja / status

    def update_selection_count(self):
        """Aktualizacja licznika zaznaczonych plików w status bar."""
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

    # ─────────────────────────── Tłumaczenia

    def retranslateUi(self):
        self.btn_open.setText(self.tr("Open Folder"))
        self.btn_delete.setText(self.tr("Delete Image(s)"))
        if not self.current_image_path:
            self.preview.clear()
        self.update_selection_count()
