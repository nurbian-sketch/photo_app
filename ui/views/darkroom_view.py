from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QMessageBox, QFileDialog, QScrollArea, QSplitter,
    QStyledItemDelegate, QStyle, QStyleOptionButton
)
from PyQt6.QtGui import QPixmap, QIcon, QImageReader, QPainter
from PyQt6.QtCore import Qt, QSize, QTimer, QRect, QPoint

import os
import hashlib

from pathlib import Path
from core.darkcache.cache_manager import PreviewCache
from core.darkcache.preview_generator import PreviewGenerator
from core.darkcache.thumbnail_reader import ExifThumbnailReader
from core.darkcache.service import DarkCacheService



class CheckboxDelegate(QStyledItemDelegate):
    """Custom delegate z checkboxem w rogu miniatury"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.checkbox_size = 20
        self.checkbox_margin_x = 16  
        self.checkbox_margin_y = 8  

    def paint(self, painter, option, index):
        # Rysuj standardowy item (ikonę + tekst)
        super().paint(painter, option, index)
        
        # Checkbox w lewym górnym rogu
        checkbox_rect = QRect(
            option.rect.left() + self.checkbox_margin_x,
            option.rect.top() + self.checkbox_margin_y,
            self.checkbox_size,
            self.checkbox_size
        )
        
        # Styl checkboxa
        checkbox_option = QStyleOptionButton()
        checkbox_option.rect = checkbox_rect
        
        # Sprawdź stan z custom data (UserRole + 1)
        is_checked = index.data(Qt.ItemDataRole.UserRole + 1)
        
        if is_checked:
            checkbox_option.state |= QStyle.StateFlag.State_On
        else:
            checkbox_option.state |= QStyle.StateFlag.State_Off
        
        checkbox_option.state |= QStyle.StateFlag.State_Enabled
        
        # Rysuj checkbox
        self.parent().style().drawControl(
            QStyle.ControlElement.CE_CheckBox,
            checkbox_option,
            painter
        )
    
    def editorEvent(self, event, model, option, index):
        # Wykryj klik na checkbox
        if event.type() == event.Type.MouseButtonRelease:
            # POPRAWKA: używamy checkbox_margin_x i checkbox_margin_y zamiast checkbox_margin
            checkbox_rect = QRect(
                option.rect.left() + self.checkbox_margin_x,
                option.rect.top() + self.checkbox_margin_y,
                self.checkbox_size,
                self.checkbox_size
            )
            
            if checkbox_rect.contains(event.pos()):
                # Toggle checkbox w custom data
                current_state = index.data(Qt.ItemDataRole.UserRole + 1)
                model.setData(index, not current_state, Qt.ItemDataRole.UserRole + 1)
                
                # Znajdź DarkroomView w hierarchii widgetów
                widget = self.parent()
                while widget and not isinstance(widget, DarkroomView):
                    widget = widget.parent()
                
                if widget:
                    widget.update_selection_count()
                
                return True
        
        return super().editorEvent(event, model, option, index)


class DarkroomView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_dir = None
        self.current_image_path = None  # Ścieżka do aktualnie wyświetlanego obrazu
        self.large_thumbs = False  # Domyślnie małe (thumbnail)
        
        # Cache directory
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

        # --- lazy loading miniatur (piexif) ---
        self.files = []
        self.load_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load_next_thumbnails)

        self.setup_ui()

        # AUTOMATYCZNE ŁADOWANIE OSTATNIEJ SESJI PRZY STARCIE
        QTimer.singleShot(500, self.open_last_session)


    def setup_ui(self):
        # === Panel miniatur po lewej ===
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)  # Multi-column
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)  # Auto-adjust columns
        self.list_widget.setIconSize(QSize(160, 120))  # Domyślnie małe thumbnail
        self.list_widget.setGridSize(QSize(120, 160))  # Grid z paddingiem
        self.list_widget.setStyleSheet("QListWidget { background-color: #1e1e1e; }")  # Ciemniejsze tło
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)  # Multi-select
        self.list_widget.itemClicked.connect(self.show_image)
        
        # Custom delegate z checkboxami
        self.list_widget.setItemDelegate(CheckboxDelegate(self.list_widget))

        # === Podgląd dużego obrazu po prawej ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5,5,5,5)

        self.image_label = QLabel(self.tr("No image"))
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: #3d3d3d; color: white;")
        self.image_label.setMinimumSize(400,300)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.image_label)
        right_layout.addWidget(scroll)

        # --- NOWY UKŁAD PRZYCISKÓW ---
        controls_layout = QVBoxLayout()

        # Grupa 1: Handle Files
        files_layout = QHBoxLayout()
        self.btn_open = QPushButton(self.tr("Open Folder"))
        self.btn_last_session = QPushButton(self.tr("Last Session"))
        self.btn_sd_card = QPushButton(self.tr("SD Card")) # TODO
        
        for btn in [self.btn_open, self.btn_last_session, self.btn_sd_card]:
            btn.setMinimumHeight(35)
            btn.setMaximumWidth(180)
            files_layout.addWidget(btn)
        files_layout.addStretch()

        # Grupa 2: View Options
        view_layout = QHBoxLayout()
        self.btn_toggle_size = QPushButton(self.tr("Large Thumbs"))
        self.btn_delete = QPushButton(self.tr("Delete Image(s)"))
        self.btn_raw_preview = QPushButton(self.tr("RAW Preview"))   # TODO
        self.btn_favorites = QPushButton(self.tr("Favorites Only")) # TODO
        self.btn_favorites.setCheckable(True)

        for btn in [self.btn_toggle_size, self.btn_delete, self.btn_raw_preview, self.btn_favorites]:
            btn.setMinimumHeight(35)
            btn.setMaximumWidth(180)
            view_layout.addWidget(btn)
        view_layout.addStretch()

        controls_layout.addLayout(files_layout)
        controls_layout.addLayout(view_layout)
        right_layout.addLayout(controls_layout)

        # QSplitter przypisany do self, aby main_window mógł go zapisać
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.list_widget)
        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5,5,5,5)
        main_layout.addWidget(self.splitter)

        # Sygnały
        self.btn_open.clicked.connect(self.open_folder)
        self.btn_last_session.clicked.connect(self.open_last_session)
        self.btn_delete.clicked.connect(self.delete_images)
        self.btn_toggle_size.clicked.connect(self.toggle_thumb_size)

    def open_last_session(self):
        """Otwiera najnowszy podfolder w katalogu sesji z preferencji"""
        main_win = self.window()
        if not hasattr(main_win, 'get_session_base_path'):
            return
            
        base_path = main_win.get_session_base_path()
        if not base_path or not os.path.exists(base_path):
            return

        try:
            subdirs = [os.path.join(base_path, d) for d in os.listdir(base_path) 
                       if os.path.isdir(os.path.join(base_path, d))]
            if not subdirs:
                return

            latest_dir = max(subdirs, key=os.path.getmtime)
            self.load_images(latest_dir)
            
            # Automatyczny podgląd pierwszego elementu
            if self.list_widget.count() > 0:
                first_item = self.list_widget.item(0)
                self.list_widget.setCurrentItem(first_item)
                self.show_image(first_item)
        except Exception as e:
            print(f"Error loading last session: {e}")

    def open_folder(self):
        default_path = os.path.expanduser("~/Obrazy/sessions")
        folder = QFileDialog.getExistingDirectory(
            self, 
            self.tr("Select photo folder"),
            default_path
        )
        if folder:
            self.current_dir = folder
            self.load_images(folder)

    def load_images(self, folder):
        self.list_widget.clear()
        self.image_label.clear()  # Wyczyść poprzedni podgląd
        self.image_label.setText(self.tr("No image"))
        self.current_image_path = None
        
        self.files = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        self.files.sort() # Dodane sortowanie, by 'pierwsze' zdjęcie było przewidywalne
        self.load_index = 0
        self.timer.start(30)  # 30ms batch loading (responsywność)

    def load_next_thumbnails(self):
        """Ładuje JEDNO zdjęcie per tick (responsywność)"""
        if self.load_index >= len(self.files):
            self.timer.stop()
            # Po zakończeniu ładowania wszystkich, upewnij się że pierwszy jest wybrany jeśli nic nie wyświetlamy
            if not self.current_image_path and self.list_widget.count() > 0:
                self.show_image(self.list_widget.item(0))
            return
        
        path = self.files[self.load_index]
        name = os.path.basename(path)
        
        pixmap = self.darkcache.get_pixmap(
            Path(path),
            self.large_thumbs
        )

   
        if pixmap and not pixmap.isNull():
            icon = QIcon(pixmap)
        else:
            # Fallback
            icon = QIcon(path)
        
        item = QListWidgetItem(icon, name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)  # Checkbox unchecked
        self.list_widget.addItem(item)
        self.load_index += 1

    def show_image(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        self.current_image_path = path  # Zapisz ścieżkę

        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()

        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            self.image_label.setPixmap(
                pixmap.scaled(
                    self.image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )
        else:
            self.image_label.setText(self.tr("Cannot open image"))

    def delete_images(self):
        """Usuń zaznaczone zdjęcia (checkboxy)"""
        # Zbierz zaznaczone pliki
        to_delete = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole + 1):  # Checkbox checked
                path = item.data(Qt.ItemDataRole.UserRole)
                to_delete.append((i, item, path))
        
        if not to_delete:
            QMessageBox.information(
                self, 
                self.tr("Delete Image(s)"),
                self.tr("No images selected")
            )
            return
        
        # Potwierdź usunięcie
        reply = QMessageBox.question(
            self, 
            self.tr("Delete Image(s)"),
            self.tr("Are you sure you want to delete {0} file(s)?").format(len(to_delete)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            deleted_count = 0
            errors = []
            
            # Usuń od końca (żeby indeksy się nie przesuwały)
            for i, item, path in reversed(to_delete):
                try:
                    os.remove(path)
                    self.list_widget.takeItem(i)
                    deleted_count += 1
                    
                    # Jeśli to był aktualny podgląd - wyczyść
                    if path == self.current_image_path:
                        self.image_label.setText(self.tr("No image"))
                        self.current_image_path = None
                        
                except Exception as e:
                    errors.append(f"{os.path.basename(path)}: {e}")
            
            # Status
            if errors:
                QMessageBox.warning(
                    self, 
                    self.tr("Delete Image(s)"),
                    self.tr("Deleted {0} file(s). Errors:\n{1}").format(
                        deleted_count, 
                        "\n".join(errors[:5])  # Max 5 błędów
                    )
                )
            
            self.update_selection_count()

    def resizeEvent(self, event):
        """Przeskaluj aktualnie wyświetlany obraz przy zmianie rozmiaru okna"""
        if self.current_image_path:
            reader = QImageReader(self.current_image_path)
            reader.setAutoTransform(True)
            image = reader.read()
            
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                self.image_label.setPixmap(
                    pixmap.scaled(
                        self.image_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                )
        
        super().resizeEvent(event)

    def retranslateUi(self):
        """Odświeżenie tekstów po zmianie języka"""
        self.btn_open.setText(self.tr("Open Folder"))
        self.btn_delete.setText(self.tr("Delete Image(s)"))
        if not self.current_image_path:
            self.image_label.setText(self.tr("No image"))
        self.update_selection_count()
    
    def update_selection_count(self):
        """Aktualizacja licznika zaznaczonych plików w status bar"""
        count = 0
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.ItemDataRole.UserRole + 1):  # Sprawdź checkbox state
                count += 1
        
        # Znajdź MainWindow i zaktualizuj status bar
        main_window = self.window()
        if hasattr(main_window, 'status_bar'):
            if count > 0:
                main_window.status_bar.showMessage(self.tr("Selected: {0} file(s)").format(count))
            else:
                main_window.status_bar.showMessage(self.tr("Ready"))
    
    def toggle_thumb_size(self):
        """Przełącz między małymi (thumbnail) a dużymi (preview) miniaturami"""
        self.large_thumbs = not self.large_thumbs
        
        # Zmień rozmiar ikon
        if self.large_thumbs:
            self.list_widget.setIconSize(QSize(240, 240))
            self.list_widget.setGridSize(QSize(270, 270))
            self.btn_toggle_size.setText(self.tr("Small Thumbs"))
        else:
            self.list_widget.setIconSize(QSize(160, 120))
            self.list_widget.setGridSize(QSize(120, 160))
            self.btn_toggle_size.setText(self.tr("Large Thumbs"))
        
        # Przeładuj katalog
        if self.current_dir:
            self.load_images(self.current_dir)