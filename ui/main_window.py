# --- PyQt6 ---
from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QMenuBar, QStatusBar,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QApplication
)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QShortcut, QKeyEvent, QPixmap, QImage, QPainter
from PyQt6.QtCore import Qt, QTimer, QTranslator, QSettings, QSize
import os
import logging

# --- Widoki ---
from PyQt6.QtCore import QThread, pyqtSignal as _pyqtSignal

class _ProbeWorker(QThread):
    """Uruchamia CameraProbe w tle — nie blokuje UI."""
    done = _pyqtSignal(bool, bool, str)   # camera_ready, sd_ready, model

    def __init__(self, enforce_fv=False):
        super().__init__()
        self.enforce_fv = enforce_fv

    def run(self):
        from core.camera_probe import CameraProbe
        camera_ready = False
        sd_ready = False
        model = ""
        try:
            with CameraProbe() as probe:
                if probe.connected:
                    camera_ready = True
                    model = probe.model or ""
                    storage = probe.check_storage()
                    sd_ready = storage.get('ok', False)
                    if self.enforce_fv:
                        mode = probe.get_mode()
                        if mode != 'Fv':
                            probe.set_fv_mode()
        except Exception:
            pass
        self.done.emit(camera_ready, sd_ready, model)

from ui.views.session_view import SessionView
from ui.views.darkroom_view import DarkroomView
from ui.views.camera_view import CameraView

# --- Widgety pomocnicze ---
from ui.widgets.view_switcher import ViewSwitcher

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, camera_on=False, sd_on=False):
        super().__init__()
        
        # 1. PARAMETRY I USTAWIENIA (Inicjalizacja krytyczna)
        self.camera_ready = camera_on
        self.sd_ready = sd_on
        self.settings = QSettings("Grzeza", "SessionsAssistant")
        self.saved_geometry = None
        self.translator = QTranslator()
        self.current_language = "en"
        self._current_view_name = None
        self._probe_worker = None  # referencja — nie GC przed zakończeniem
        
        self.setWindowTitle(self.tr("Sessions Assistant 0.99"))

        # 2. PASEK STANU I IKONY (24px, 4px od doÅ‚u)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(self.tr("Ready"))

        self.status_icons_widget = QWidget()
        self.status_icons_widget.setStyleSheet("background: transparent; border: none;")
        
        icons_layout = QHBoxLayout(self.status_icons_widget)
        # Margines dÃ³Å‚ = 4px, aby ikony nie dotykaÅ‚y krawÄ™dzi ekranu
        icons_layout.setContentsMargins(5, 0, 10, 4)
        icons_layout.setSpacing(12) 
        
        self.icon_camera = QLabel() 
        self.icon_sd_card = QLabel()
        self.icon_camera.setStyleSheet("background: transparent;")
        self.icon_sd_card.setStyleSheet("background: transparent;")
        
        icons_layout.addWidget(self.icon_camera)
        icons_layout.addWidget(self.icon_sd_card)
        self.status_bar.addPermanentWidget(self.status_icons_widget)
        
        # 3. INICJALIZACJA WIDOKÃ“W
        self.session_view = SessionView()
        self.darkroom_view = DarkroomView()
        self.camera_view = CameraView()

        self.central_stack = QStackedWidget()
        self.central_stack.addWidget(self.darkroom_view)   # index 0
        self.central_stack.addWidget(self.camera_view)     # index 1
        self.central_stack.addWidget(self.session_view)    # index 2

        self.switcher = ViewSwitcher(["Darkroom", "Camera", "Session"])
        self.switcher.view_changed.connect(self.change_view)

        layout = QVBoxLayout()
        layout.addWidget(self.switcher)
        layout.addWidget(self.central_stack)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # 4. FINALIZACJA STANU
        # Ustawiamy ikony na podstawie danych ze splasha
        self.set_status_icons(camera=self.camera_ready, sd=self.sd_ready)
        self.session_view.set_camera_ready(self.camera_ready, self.sd_ready)
        
        # Logika wyboru widoku startowego: aparat → Camera, brak → Darkroom
        start_view = "Camera" if self.camera_ready else "Darkroom"

        self.change_view(start_view)
        self.switcher.select_view(start_view) # Synchronizacja switchera

        # camera_released: USB zwolnione po zatrzymaniu LV — odśwież stan we wszystkich widokach
        self.camera_view.camera_released.connect(self._probe_camera)
        # Dynamiczne menu podglądów
        self.camera_view.preview_list_changed.connect(self._update_preview_menu)
        # Komunikaty z camera_view do status bar
        self.camera_view.status_message.connect(self.status_bar.showMessage)
        # WB picker z DarkroomView → przełącz na Camera + aplikuj temperaturę
        self.darkroom_view.wb_apply_requested.connect(self._on_darkroom_wb_apply)


        self.read_settings()
        self.setup_menu()

        # Połączenia SessionView
        self.session_view.status_message.connect(
            lambda msg: self.status_bar.showMessage(msg, 5000)
        )
        self.session_view.session_finished.connect(self._on_session_finished)
        self.session_view.camera_detected.connect(self._probe_camera)

    def _make_status_pixmap(self, file_name, active=True):
        """Tworzy pixmapę 24px: kolorową lub przyciemnioną (nieaktywna)."""
        path = os.path.join("assets", "icons", file_name)
        if not os.path.exists(path):
            return QPixmap()

        pix = QPixmap(path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
        if active:
            return pix

        # Nieaktywna: oryginał z alpha zachowanym, opacity 0.35
        out = QPixmap(pix.size())
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setOpacity(0.35)
        painter.drawPixmap(0, 0, pix)
        painter.end()
        return out

    def set_status_icons(self, camera=False, sd=False):
        """Aktualizuje ikony graficzne w pasku stanu"""
        self.icon_camera.setPixmap(self._make_status_pixmap("camera.svg", active=camera))
        self.icon_sd_card.setPixmap(self._make_status_pixmap("sdcard.png", active=sd))

    def setup_menu(self):
        menu_bar = QMenuBar()
        self.setMenuBar(menu_bar)

        # FILE MENU
        file_menu = menu_bar.addMenu(self.tr("File"))

        pref_action = QAction(self.tr("Preferences..."), self)
        pref_action.setShortcut(QKeySequence("Ctrl+,"))
        pref_action.triggered.connect(self._show_preferences)
        file_menu.addAction(pref_action)

        file_menu.addSeparator()

        exit_action = QAction(self.tr("Exit"), self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # SELECT MENU — między File a View, pozycje wyszarzane poza Pictures
        self._select_menu = menu_bar.addMenu(self.tr("Select"))
        self._action_mw_select_all = QAction(self.tr("Select All"), self)
        self._action_mw_deselect_all = QAction(self.tr("Deselect All"), self)
        self._action_mw_select_all.triggered.connect(
            lambda: self.darkroom_view._select_all()
        )
        self._action_mw_deselect_all.triggered.connect(
            lambda: self.darkroom_view._deselect_all()
        )
        self._action_mw_select_all.setEnabled(False)
        self._action_mw_deselect_all.setEnabled(False)
        self._select_menu.addAction(self._action_mw_select_all)
        self._select_menu.addAction(self._action_mw_deselect_all)

        # VIEW MENU
        self._view_menu = menu_bar.addMenu(self.tr("View"))
        for name, key in [("Darkroom", "Ctrl+1"), ("Camera", "Ctrl+2"), ("Session", "Ctrl+3")]:
            action = QAction(self.tr(name), self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(lambda checked, n=name: self.switcher.select_view(n))
            self._view_menu.addAction(action)

        self._view_menu.addSeparator()

        # Submenu Sort By — aktywne tylko gdy widok Pictures
        self._sort_menu = self._view_menu.addMenu(self.tr("Sort By"))
        self._sort_actions = {}
        for key, label in [('name', "Name"), ('date', "Date"), ('type', "Type")]:
            action = QAction(self.tr(label), self)
            action.setCheckable(True)
            action.setData(key)
            action.triggered.connect(lambda checked, k=key: self._on_sort_changed(k))
            self._sort_menu.addAction(action)
            self._sort_actions[key] = action
        self._sort_actions['name'].setChecked(True)
        self._sort_menu.setEnabled(False)

        # Separator + dynamiczne wpisy dla okien podglądu
        self._preview_separator = self._view_menu.addSeparator()
        self._preview_separator.setVisible(False)
        self._preview_actions = {}  # dialog → QAction

        menu_bar.setStyleSheet("""
            QMenuBar { background-color: #2b2b2b; color: #cccccc; }
            QMenuBar::item { background-color: transparent; padding: 4px 10px; }
            QMenuBar::item:selected { background-color: #3d3d3d; }
            QMenu { background-color: #2b2b2b; color: #cccccc; border: 1px solid #555555; }
            QMenu::item { padding: 5px 30px 5px 20px; }
            QMenu::item:selected { background-color: #3d3d3d; }
            QMenu::item:disabled { color: #666666; }
        """)

    def change_view(self, name):
        prev = self._current_view_name

        # --- Opuszczamy Camera: zamykamy sesję PTP ---
        if prev == "Camera":
            self.camera_view.on_leave()

        # --- Opuszczamy Session: zatrzymujemy worker i polling USB ---
        if prev == "Session":
            self.session_view.on_leave()

        # --- Przełączamy widget ---
        mapping = {
            "Darkroom": self.darkroom_view,
            "Camera": self.camera_view,
            "Session": self.session_view
        }
        self.central_stack.setCurrentWidget(mapping[name])
        self._current_view_name = name

        # --- Wchodzimy do widoku ---
        if name == "Camera":
            self.camera_view.on_enter()
        elif name == "Session":
            self.session_view.on_enter()
        elif name == "Darkroom":
            QTimer.singleShot(150, self.darkroom_view.btn_open_folder.setFocus)

        # Sort By i Select aktywne tylko w Darkroom
        is_pictures = (name == "Darkroom")
        if hasattr(self, '_sort_menu'):
            self._sort_menu.setEnabled(is_pictures)
        if hasattr(self, '_action_mw_select_all'):
            self._action_mw_select_all.setEnabled(is_pictures)
            self._action_mw_deselect_all.setEnabled(is_pictures)

        self._probe_camera(enforce_fv=(name == "Camera"))

    def _probe_camera(self, enforce_fv=False):
        """Uruchamia CameraProbe w tle — nie blokuje UI.
        Pomija probe gdy LV aktywne, wątek się zamyka lub sesja trwa (USB odłączone)."""
        if self.session_view.is_session_active():
            return  # Sesja aktywna — aparat bezprzewodowy, nie dotykaj USB
        if self.camera_view.is_lv_active():
            return  # LV trzyma USB — nie dotykaj
        if self.camera_view._stopping:
            return  # Wątek w trakcie zamykania — USB niestabilne
        if self.session_view.is_settings_active():
            return  # Worker ustawień sesji aktywny — nie przerywaj
        if self._probe_worker and self._probe_worker.isRunning():
            return  # Poprzedni probe jeszcze działa
        # Zatrzymaj workerów ustawień — probe potrzebuje wyłącznego dostępu USB (PTP exclusive)
        self.camera_view._stop_settings_worker()
        self.session_view._stop_settings_worker()
        self.status_bar.showMessage(self.tr("Connecting camera..."))
        self._probe_worker = _ProbeWorker(enforce_fv=enforce_fv)
        self._probe_worker.done.connect(self._on_probe_done)
        self._probe_worker.start()

    def _on_sort_changed(self, key: str):
        """Zmiana sortowania — aktualizuje checkmarki i przekazuje do darkroom_view."""
        for k, action in self._sort_actions.items():
            action.setChecked(k == key)
        self.darkroom_view.set_sort(key)

    def _on_probe_done(self, camera_ready, sd_ready, model):
        self.camera_ready = camera_ready
        self.sd_ready = sd_ready
        self.set_status_icons(camera=camera_ready, sd=sd_ready)
        self.camera_view.set_camera_ready(camera_ready)
        self.darkroom_view.set_sd_card_ready(sd_ready)
        self.session_view.set_camera_ready(camera_ready, sd_ready)
        if camera_ready:
            self.status_bar.showMessage(
                self.tr(f"Camera found: {model}") if model else self.tr("Camera found"), 4000
            )
        else:
            self.status_bar.showMessage(self.tr("Camera not detected"), 4000)

    def _on_session_finished(self, summary):
        """
        Callback po zakończeniu sesji.
        Dla trybu CLIENT i HOME: auto-load folderu sesji w Darkroom.
        """
        from core.session_context import SessionMode
        ctx = summary.context
        if ctx.mode != SessionMode.PRIVATE and ctx.session_path:
            self.darkroom_view.load_images(ctx.session_path)

    def _on_darkroom_wb_apply(self, kelvin: int):
        """WB picker z DarkroomView: aplikuje temperaturę WB na aparacie."""
        self.camera_view.image_ctrl.apply_wb_temperature(kelvin)
        self.status_bar.showMessage(
            self.tr(f"WB set to {kelvin} K"), 4000
        )

    def _update_preview_menu(self, pairs):
        """Aktualizuje dynamiczne wpisy menu View dla okien podglądu."""
        # Usuń stare akcje
        for action in self._preview_actions.values():
            self._view_menu.removeAction(action)
        self._preview_actions.clear()

        # Dodaj nowe
        for title, dialog in pairs:
            action = QAction(f"📷 {title}", self)
            action.triggered.connect(lambda checked, d=dialog: (d.show(), d.raise_(), d.activateWindow()))
            self._view_menu.addAction(action)
            self._preview_actions[id(dialog)] = action

        self._preview_separator.setVisible(bool(pairs))

    def read_settings(self):
        screen = QApplication.primaryScreen().availableGeometry()
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
            geo = self.geometry()
            w = min(geo.width(), screen.width())
            h = min(geo.height(), screen.height())
            x = max(screen.left(), min(geo.x(), screen.right() - w))
            y = max(screen.top(), min(geo.y(), screen.bottom() - h))
            self.setGeometry(x, y, w, h)
        else:
            w = min(1100, screen.width() - 40)
            h = min(720, screen.height() - 40)
            self.resize(w, h)
            
        if self.settings.value("windowState"):
            self.restoreState(self.settings.value("windowState"))
            
        if self.settings.value("darkroom_splitter"):
            self.darkroom_view.splitter.restoreState(self.settings.value("darkroom_splitter"))

    def closeEvent(self, event):
        self.camera_view.close_all_previews()
        self.camera_view.on_leave()
        self.session_view.on_leave()  # zatrzymuje worker ustawień i USB polling
        # Nie zapisujemy geometrii fullscreen — przywracamy normalną
        if self.isFullScreen():
            self.showNormal()
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("darkroom_splitter", self.darkroom_view.splitter.saveState())
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if self.saved_geometry:
                self.setGeometry(self.saved_geometry)
        else:
            self.saved_geometry = self.geometry()
            self.showFullScreen()

    def _show_preferences(self):
        from ui.dialogs.preferences_dialog import PreferencesDialog
        dialog = PreferencesDialog(self)
        if dialog.exec() == PreferencesDialog.DialogCode.Accepted:
            self.camera_view.update_capture_directory()
            self.status_bar.showMessage(self.tr("Preferences saved"), 2000)

    def show_about(self):
        QMessageBox.information(self, self.tr("About"), self.tr("Sessions Assistant 0.99\nAuthor: Grzeza"))

    def retranslateUi(self):
        self.setWindowTitle(self.tr("Sessions Assistant 0.99"))