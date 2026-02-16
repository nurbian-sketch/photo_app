# --- PyQt6 ---
from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QMenuBar, QStatusBar,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QApplication,
    QFileDialog  # Dodano QFileDialog
)
from PyQt6.QtGui import QAction, QKeySequence, QShortcut, QKeyEvent, QPixmap, QImage, QPainter
from PyQt6.QtCore import Qt, QTranslator, QSettings, QSize
import os
import logging

# --- Widoki ---
from ui.views.session_view import SessionView
from ui.views.darkroom_view import DarkroomView
from ui.views.camera_view import CameraView

# --- Widgety pomocnicze ---
from ui.widgets.view_switcher import ViewSwitcher
from core.camera_probe import CameraProbe

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
        
        self.setWindowTitle(self.tr("Sessions Assistant 0.99"))

        # 2. PASEK STANU I IKONY (24px, 4px od dołu)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(self.tr("Ready"))

        self.status_icons_widget = QWidget()
        self.status_icons_widget.setStyleSheet("background: transparent; border: none;")
        
        icons_layout = QHBoxLayout(self.status_icons_widget)
        # Margines dół = 4px, aby ikony nie dotykały krawędzi ekranu
        icons_layout.setContentsMargins(5, 0, 10, 4)
        icons_layout.setSpacing(12) 
        
        self.icon_camera = QLabel() 
        self.icon_sd_card = QLabel()
        self.icon_camera.setStyleSheet("background: transparent;")
        self.icon_sd_card.setStyleSheet("background: transparent;")
        
        icons_layout.addWidget(self.icon_camera)
        icons_layout.addWidget(self.icon_sd_card)
        self.status_bar.addPermanentWidget(self.status_icons_widget)
        
        # 3. INICJALIZACJA WIDOKÓW
        self.session_view = SessionView()
        self.darkroom_view = DarkroomView()
        self.camera_view = CameraView()

        self.central_stack = QStackedWidget()
        self.central_stack.addWidget(self.darkroom_view)   # index 0
        self.central_stack.addWidget(self.camera_view)     # index 1
        self.central_stack.addWidget(self.session_view)    # index 2

        self.switcher = ViewSwitcher(["Pictures", "Camera", "Session"])
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
        
        # Logika wyboru widoku startowego
        if self.camera_ready and self.sd_ready:
            start_view = "Camera"
        elif self.camera_ready:
            start_view = "Pictures"
        else:
            start_view = "Session"

        self.change_view(start_view)
        self.switcher.select_view(start_view) # Synchronizacja switchera

        self.read_settings()
        self.setup_menu()

        # Połączenia akcji SessionView
        self.session_view.btn_action1.clicked.connect(lambda: self.status_bar.showMessage(self.tr("Action 1 executed")))
        self.session_view.btn_action2.clicked.connect(lambda: self.status_bar.showMessage(self.tr("Action 2 executed")))
        self.session_view.btn_action3.clicked.connect(lambda: self.status_bar.showMessage(self.tr("Action 3 executed")))

    def _make_status_pixmap(self, file_name, active=True):
        """Tworzy pixmapę 24px: kolorową lub wyszarzoną w locie"""
        path = os.path.join("assets", "icons", file_name)
        if not os.path.exists(path):
            return QPixmap()

        pix = QPixmap(path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        
        if active:
            return pix

        # Wersja nieaktywna: szara i półprzezroczysta
        img = pix.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        gray_pix = QPixmap.fromImage(img)
        
        out_pix = QPixmap(gray_pix.size())
        out_pix.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(out_pix)
        painter.setOpacity(0.3) 
        painter.drawPixmap(0, 0, gray_pix)
        painter.end()
        return out_pix

    def set_status_icons(self, camera=False, sd=False):
        """Aktualizuje ikony graficzne w pasku stanu"""
        self.icon_camera.setPixmap(self._make_status_pixmap("camera.svg", active=camera))
        self.icon_sd_card.setPixmap(self._make_status_pixmap("sdcard.png", active=sd))

    def setup_menu(self):
        menu_bar = QMenuBar()
        self.setMenuBar(menu_bar)

        # FILE MENU
        file_menu = menu_bar.addMenu(self.tr("File"))
        
        # Preferences submenu
        pref_menu = file_menu.addMenu(self.tr("Preferences"))
        set_folder_action = QAction(self.tr("Set Session Folder"), self)
        set_folder_action.triggered.connect(self.set_session_folder_pref)
        pref_menu.addAction(set_folder_action)
        
        file_menu.addSeparator()

        exit_action = QAction(self.tr("Exit"), self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # VIEW MENU
        view_menu = menu_bar.addMenu(self.tr("View"))
        for name, key in [("Pictures", "Ctrl+1"), ("Camera", "Ctrl+2"), ("Session", "Ctrl+3")]:
            action = QAction(self.tr(name), self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(lambda checked, n=name: self.switcher.select_view(n))
            view_menu.addAction(action)

        menu_bar.setStyleSheet("""
            QMenuBar { background-color: #2b2b2b; color: #cccccc; }
            QMenuBar::item { background-color: transparent; padding: 4px 10px; }
            QMenuBar::item:selected { background-color: #3d3d3d; }
            QMenu { background-color: #2b2b2b; color: #cccccc; border: 1px solid #555555; }
            QMenu::item { padding: 5px 30px 5px 20px; }
            QMenu::item:selected { background-color: #3d3d3d; }
        """)

    def get_session_base_path(self):
        """Pobiera ścieżkę bazową sesji z QSettings lub zwraca domyślną."""
        default = os.path.join(os.path.expanduser("~"), "Obrazy", "sessions")
        return self.settings.value("session_base_path", default)

    def set_session_folder_pref(self):
        """Otwiera okno wyboru folderu i zapisuje nową ścieżkę w ustawieniach."""
        current = self.get_session_base_path()
        folder = QFileDialog.getExistingDirectory(self, self.tr("Select Base Session Folder"), current)
        if folder:
            self.settings.setValue("session_base_path", folder)
            self.status_bar.showMessage(self.tr("Session folder updated"), 3000)

    def change_view(self, name):
        prev = self._current_view_name

        # --- Opuszczamy Camera: zamykamy sesję PTP ---
        if prev == "Camera":
            self.camera_view.on_leave()

        # --- Przełączamy widget ---
        mapping = {
            "Pictures": self.darkroom_view,
            "Camera": self.camera_view,
            "Session": self.session_view
        }
        self.central_stack.setCurrentWidget(mapping[name])
        self._current_view_name = name

        # --- Jeden probe: status + tryb w jednym połączeniu ---
        self._probe_camera(enforce_fv=(name == "Camera"))

    def _probe_camera(self, enforce_fv=False):
        """Jedno połączenie: odświeża status ikon + opcjonalnie wymusza Fv."""
        try:
            with CameraProbe() as probe:
                if not probe.connected:
                    self.camera_ready = False
                    self.sd_ready = False
                else:
                    self.camera_ready = True
                    storage = probe.check_storage()
                    self.sd_ready = storage['ok']

                    if enforce_fv:
                        mode = probe.get_mode()
                        if mode != 'Fv':
                            logger.info(f"Tryb {mode} → wymuszam Fv")
                            if probe.set_fv_mode():
                                self.status_bar.showMessage(
                                    f"Camera mode: {mode} → Fv", 3000
                                )
                            else:
                                self.status_bar.showMessage(
                                    "WARNING: Could not set Fv mode", 5000
                                )
        except Exception as e:
            logger.warning(f"Camera probe error: {e}")
            self.camera_ready = False
            self.sd_ready = False

        self.set_status_icons(camera=self.camera_ready, sd=self.sd_ready)
        self.camera_view.set_camera_ready(self.camera_ready)

    def read_settings(self):
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))
        else:
            self.resize(1200, 800)
            
        if self.settings.value("windowState"):
            self.restoreState(self.settings.value("windowState"))
            
        if self.settings.value("darkroom_splitter"):
            self.darkroom_view.splitter.restoreState(self.settings.value("darkroom_splitter"))

    def closeEvent(self, event):
        self.camera_view.on_leave()
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

    def show_about(self):
        QMessageBox.information(self, self.tr("About"), self.tr("Sessions Assistant 0.99\nAuthor: Grzeza"))

    def retranslateUi(self):
        self.setWindowTitle(self.tr("Sessions Assistant 0.99"))