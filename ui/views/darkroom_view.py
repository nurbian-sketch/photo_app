from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QMessageBox, QFileDialog, QScrollArea, QSizePolicy, QSplitter,
    QStyledItemDelegate, QStyle, QStyleOptionButton
)
from PyQt6.QtGui import QPixmap, QIcon, QImageReader, QPainter, QTransform
from PyQt6.QtCore import Qt, QSize, QTimer, QRect, QPoint, pyqtSignal, QThread

import os
import hashlib

from pathlib import Path
from core.darkcache.cache_manager import PreviewCache
from core.darkcache.preview_generator import PreviewGenerator
from core.darkcache.thumbnail_reader import ExifThumbnailReader
from core.darkcache.service import DarkCacheService
from ui.widgets.preview_panel import PreviewPanel

# Rozszerzenia RAW — do filtrowania i wykrywania
RAW_EXTENSIONS = {'.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng'}


# ─────────────────────────── Helpers EXIF / loader (wspólne z camera_view)

def _is_raw(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in RAW_EXTENSIONS


def _find_companion_jpg(raw_path: str) -> str | None:
    base = os.path.splitext(raw_path)[0]
    for ext in ('.jpg', '.JPG', '.jpeg', '.JPEG'):
        c = base + ext
        if os.path.exists(c):
            return c
    return None


def _exiftool_extract_preview(path: str) -> str | None:
    import subprocess, tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name
        with open(tmp_path, 'wb') as out_fh:
            result = subprocess.run(
                ['exiftool', '-b', '-PreviewImage', path],
                stdout=out_fh, stderr=subprocess.PIPE, timeout=10,
            )
        if result.returncode == 0 and os.path.getsize(tmp_path) > 0:
            return tmp_path
        os.unlink(tmp_path)
    except Exception:
        pass
    return None


def _load_pixmap_from_path(path: str) -> QPixmap:
    if not _is_raw(path):
        pix = QPixmap(path)
        return pix if not pix.isNull() else QPixmap()
    jpg = _find_companion_jpg(path)
    if jpg:
        pix = QPixmap(jpg)
        if not pix.isNull():
            return pix
    tmp_path = _exiftool_extract_preview(path)
    if tmp_path:
        pix = QPixmap(tmp_path)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        if not pix.isNull():
            return pix
    return QPixmap()


def _read_exif(path: str) -> dict:
    r = {'shutter': '', 'aperture': '', 'iso': '', 'focal': '',
         'date': '', 'dims': '', 'size': '', 'camera': '', 'orientation': 0}
    try:
        r['size'] = f"{os.path.getsize(path) / (1024 * 1024):.1f}\u00a0MB"
        if _is_raw(path):
            jpg = _find_companion_jpg(path)
            if jpg:
                _fill_exif_piexif(jpg, r)
            else:
                _fill_exif_exiftool_json(path, r)
        else:
            _fill_exif_piexif(path, r)
    except Exception as e:
        print(f"EXIF read error ({os.path.basename(path)}): {e}")
    return r


def _fill_exif_piexif(source_path: str, r: dict):
    import piexif
    exif = piexif.load(source_path)
    ifd0 = exif.get('0th', {})
    exif_ifd = exif.get('Exif', {})
    r['orientation'] = {1: 0, 3: 180, 6: 90, 8: 270}.get(
        ifd0.get(piexif.ImageIFD.Orientation, 1), 0)
    reader = QImageReader(source_path)
    sz = reader.size()
    if sz.isValid():
        r['dims'] = f"{sz.width()}\u00d7{sz.height()}"
    def frac(v):
        return (v[0], v[1]) if isinstance(v, tuple) and len(v) == 2 and v[1] else (int(v), 1)
    exp = exif_ifd.get(piexif.ExifIFD.ExposureTime)
    if exp:
        n, d = frac(exp)
        if n and d:
            ratio = d / n
            r['shutter'] = f"1/{int(round(ratio))}s" if ratio >= 1 else f"{n/d:.1f}s"
    fn = exif_ifd.get(piexif.ExifIFD.FNumber)
    if fn:
        n, d = frac(fn)
        if d:
            r['aperture'] = f"f/{n/d:.1f}"
    iso = exif_ifd.get(piexif.ExifIFD.ISOSpeedRatings)
    if iso:
        r['iso'] = f"ISO\u00a0{iso}"
    fl = exif_ifd.get(piexif.ExifIFD.FocalLength)
    if fl:
        n, d = frac(fl)
        if d:
            r['focal'] = f"{int(round(n/d))}mm"
    dt = (exif_ifd.get(piexif.ExifIFD.DateTimeOriginal)
          or ifd0.get(piexif.ImageIFD.DateTime))
    if dt:
        s = dt.decode('ascii', errors='ignore') if isinstance(dt, bytes) else str(dt)
        r['date'] = s[:10].replace(':', '-') + ' ' + s[11:16]
    make = (ifd0.get(piexif.ImageIFD.Make) or b'').decode('ascii', errors='ignore').strip()
    model_b = (ifd0.get(piexif.ImageIFD.Model) or b'').decode('ascii', errors='ignore').strip()
    if model_b:
        r['camera'] = model_b if model_b.startswith(make) else (
            f"{make} {model_b}".strip() if make else model_b)


def _fill_exif_exiftool_json(path: str, r: dict):
    import subprocess, json
    try:
        result = subprocess.run(
            ['exiftool', '-j', '-n',
             '-Orientation', '-ImageWidth', '-ImageHeight',
             '-ExposureTime', '-FNumber', '-ISO',
             '-FocalLength', '-DateTimeOriginal', '-Make', '-Model', path],
            capture_output=True, text=True, timeout=15)
        if result.returncode != 0 or not result.stdout.strip():
            return
        data = json.loads(result.stdout)[0]
        r['orientation'] = {1: 0, 3: 180, 6: 90, 8: 270}.get(
            int(data.get('Orientation', 1)), 0)
        w = data.get('ImageWidth')
        h = data.get('ImageHeight')
        if w and h:
            r['dims'] = f"{int(w)}\u00d7{int(h)}"
        exp = data.get('ExposureTime')
        if exp:
            v = float(exp)
            if v > 0:
                r['shutter'] = f"1/{int(round(1/v))}s" if v < 1 else f"{v:.1f}s"
        fn = data.get('FNumber')
        if fn:
            r['aperture'] = f"f/{float(fn):.1f}"
        iso = data.get('ISO')
        if iso:
            r['iso'] = f"ISO\u00a0{int(iso)}"
        fl = data.get('FocalLength')
        if fl:
            r['focal'] = f"{int(round(float(fl)))}mm"
        dt = str(data.get('DateTimeOriginal', ''))
        if dt and len(dt) >= 16:
            r['date'] = dt[:10].replace(':', '-') + ' ' + dt[11:16]
        make = str(data.get('Make', '')).strip()
        model_s = str(data.get('Model', '')).strip()
        if model_s:
            r['camera'] = model_s if model_s.startswith(make) else (
                f"{make} {model_s}".strip() if make else model_s)
    except Exception as e:
        print(f"exiftool JSON error ({os.path.basename(path)}): {e}")


class _ImageLoader(QThread):
    """Laduje pixmape i EXIF w tle. Emituje loaded(pixmap, exif_dict)."""
    loaded = pyqtSignal(object, dict)

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        pixmap = _load_pixmap_from_path(self._path)
        exif = _read_exif(self._path)
        self.loaded.emit(pixmap, exif)




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

    # Emitowany gdy user klika "SD Card" — MainWindow obsługuje pobieranie plików
    sd_card_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_dir = None
        self.current_image_path = None  # Ścieżka do aktualnie wyświetlanego obrazu
        self.large_thumbs = False  # Domyślnie małe (thumbnail)
        self._show_raw = False          # domyślnie pliki RAW ukryte
        self._sd_card_ready = False     # True = karta SD wykryta w aparacie
        self._loader = None              # Aktywny _ImageLoader
        
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
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.itemClicked.connect(self.show_image)
        self.list_widget.currentItemChanged.connect(
            lambda cur, prev: self.show_image(cur) if cur else None
        )
        self.list_widget.installEventFilter(self)  # nawigacja strzałkami
        
        # Custom delegate z checkboxami
        self.list_widget.setItemDelegate(CheckboxDelegate(self.list_widget))

        # === Podgląd dużego obrazu po prawej ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5,5,5,5)

        self.preview = PreviewPanel()
        right_layout.addWidget(self.preview, 1)

        controls_layout = QVBoxLayout()
        controls_layout.setSpacing(6)

        # Jeden wiersz przycisków
        row_layout = QHBoxLayout()
        self.btn_open = QPushButton(self.tr("Open Folder"))
        self.btn_last_session = QPushButton(self.tr("Last Session"))
        self.btn_toggle_size = QPushButton(self.tr("Large Thumbs"))
        self.btn_delete = QPushButton(self.tr("Delete Image(s)"))
        self.btn_sd_card = QPushButton(self.tr("SD Card"))
        self.btn_raw_preview = QPushButton(self.tr("RAW: OFF"))
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
        self.btn_raw_preview.setCheckable(False)
        self.btn_raw_preview.setVisible(False)  # pojawia sie tylko gdy sa pliki RAW
        self.btn_raw_preview.clicked.connect(self._toggle_raw)
        self.btn_sd_card.setVisible(False)      # pojawia się tylko gdy karta wykryta
        self.btn_sd_card.clicked.connect(self.sd_card_requested.emit)
        self.btn_favorites.setVisible(False)    # TODO

    def open_last_session(self):
        """Otwiera najnowszy podfolder w katalogu sesji, pomijając captures subdir."""
        from ui.dialogs.preferences_dialog import PreferencesDialog
        base_path = PreferencesDialog.get_session_directory()
        captures_name = PreferencesDialog.get_captures_subdir()

        if not base_path or not os.path.exists(base_path):
            return
        try:
            subdirs = [
                os.path.join(base_path, d)
                for d in os.listdir(base_path)
                if os.path.isdir(os.path.join(base_path, d))
                and d != captures_name          # pomijamy katalog captures
            ]
            if not subdirs:
                return
            latest_dir = max(subdirs, key=os.path.getmtime)
            self.load_images(latest_dir)

            if self.list_widget.count() > 0:
                first_item = self.list_widget.item(0)
                self.list_widget.setCurrentItem(first_item)
                self.show_image(first_item)
        except Exception as e:
            print(f"Error loading last session: {e}")

    def open_folder(self):
        from ui.dialogs.preferences_dialog import PreferencesDialog
        default_path = PreferencesDialog.get_session_directory()
        folder = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select photo folder"),
            default_path
        )
        if folder:
            self.current_dir = folder
            self.load_images(folder)

    # Rozszerzenia JPEG/PNG obsługiwane zawsze
    JPEG_EXTENSIONS = ('.jpg', '.jpeg', '.png')
    # Rozszerzenia RAW — wyświetlane zależnie od btn_raw_preview
    RAW_EXTENSIONS_TUPLE = ('.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng')

    @property
    def IMAGE_EXTENSIONS(self):
        if self._show_raw:
            return self.JPEG_EXTENSIONS + self.RAW_EXTENSIONS_TUPLE
        return self.JPEG_EXTENSIONS

    def load_images(self, folder):
        self.current_dir = folder
        self.timer.stop()
        self.list_widget.clear()
        self.preview.clear()
        self.current_image_path = None

        all_files = [f.lower() for f in os.listdir(folder)]
        has_raw = any(
            f.endswith(self.RAW_EXTENSIONS_TUPLE) for f in all_files
        )
        self.btn_raw_preview.setVisible(has_raw)

        self.files = sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(self.IMAGE_EXTENSIONS)
        )

        if not self.files:
            return

        # Pierwszy plik od razu — thumbnail + podglad
        self._add_thumbnail_item(0)
        self._select_and_show(0)

        # Reszta w tle (timer)
        self.load_index = 1
        if len(self.files) > 1:
            self.timer.start(30)

    def _add_thumbnail_item(self, index: int):
        """Dodaje jeden element do list_widget z miniatura."""
        path = self.files[index]
        pixmap = self.darkcache.get_pixmap(Path(path), self.large_thumbs)
        icon = QIcon(pixmap) if pixmap and not pixmap.isNull() else QIcon()
        item = QListWidgetItem(icon, os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        self.list_widget.addItem(item)

    def load_next_thumbnails(self):
        """Laduje JEDNO zdjecie per tick (responsywnosc)."""
        if self.load_index >= len(self.files):
            self.timer.stop()
            return

        self._add_thumbnail_item(self.load_index)
        self.load_index += 1

    def show_image(self, item):
        """Wyswietla podglad asynchronicznie przez _ImageLoader."""
        path = item.data(Qt.ItemDataRole.UserRole)
        self.current_image_path = path
        self.preview.set_message(self.tr("Loading…"))

        # Anuluj poprzedni loader — odlacz sygnal, poczekaj na zakonczenie
        if self._loader and self._loader.isRunning():
            try:
                self._loader.loaded.disconnect()
            except RuntimeError:
                pass
            self._loader.wait()
        self._loader = None

        self._loader = _ImageLoader(path)
        self._loader.loaded.connect(self._on_image_loaded)
        self._loader.start()

    def _on_image_loaded(self, pixmap: QPixmap, exif: dict):
        """Callback z _ImageLoader — deleguje do PreviewPanel."""
        self.preview.set_pixmap(pixmap, exif.get('orientation', 0))
        self.preview.set_exif(exif)

    def _select_and_show(self, index: int):
        """Zaznacza element listy i wyświetla podgląd."""
        item = self.list_widget.item(index)
        if item:
            self.list_widget.setCurrentItem(item)
            self.show_image(item)

    def eventFilter(self, obj, event):
        """Przekazuje zdarzenia klawiatury do QListWidget — nawigacja po gridzie obsługiwana natywnie."""
        return super().eventFilter(obj, event)

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
                        self.preview.clear()
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

    # ─────────────────────────── RAW TOGGLE

    def _toggle_raw(self):
        """Przelacza widocznosc plikow RAW na liscie miniatur."""
        self._show_raw = not self._show_raw
        self.btn_raw_preview.setText(
            self.tr("RAW: ON") if self._show_raw else self.tr("RAW: OFF")
        )
        if self.current_dir:
            self.load_images(self.current_dir)

    # ─────────────────────────── SD CARD

    def set_sd_card_ready(self, ready: bool):
        """Wywoływane przez MainWindow gdy probe wykryje / utraci kartę SD."""
        self._sd_card_ready = ready
        self.btn_sd_card.setVisible(ready)

    def retranslateUi(self):
        """Odświeżenie tekstów po zmianie języka"""
        self.btn_open.setText(self.tr("Open Folder"))
        self.btn_delete.setText(self.tr("Delete Image(s)"))
        if not self.current_image_path:
            self.preview.clear()
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