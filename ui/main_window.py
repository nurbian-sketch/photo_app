# --- PyQt6 ---
from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QMenuBar, QStatusBar,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QApplication
)
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QShortcut, QKeyEvent, QPixmap, QImage, QPainter
from PyQt6.QtCore import Qt, QTimer, QTranslator, QSettings, QSize
import json
import os
import subprocess
import sys
import logging
from pathlib import Path

# --- Widoki ---
from PyQt6.QtCore import QThread, pyqtSignal as _pyqtSignal
from core.rclone_about_worker import RcloneAboutWorker

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
        
        self.icon_camera    = QLabel()
        self.icon_sd_card   = QLabel()
        self.icon_sync      = QLabel()
        self.icon_developer = QLabel()
        self.icon_camera.setStyleSheet("background: transparent;")
        self.icon_sd_card.setStyleSheet("background: transparent;")
        self.icon_sync.setStyleSheet("background: transparent;")
        self.icon_developer.setStyleSheet("background: transparent;")
        self.icon_sync.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_sync.mousePressEvent = lambda e: self._sync_now()
        self.icon_sync.setVisible(False)       # ukryta gdy rclone nie skonfigurowany
        self.icon_developer.setVisible(False)  # ukryta gdy developer nieaktywny
        self.icon_developer.mousePressEvent = lambda e: self._on_developer_icon_clicked()

        self.icon_bot = QLabel()
        self.icon_bot.setStyleSheet("background: transparent;")
        self.icon_bot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_bot.setVisible(False)
        self.icon_bot.mousePressEvent = lambda e: self._show_preferences()

        icons_layout.addWidget(self.icon_camera)
        icons_layout.addWidget(self.icon_sd_card)
        icons_layout.addWidget(self.icon_sync)
        icons_layout.addWidget(self.icon_developer)
        icons_layout.addWidget(self.icon_bot)
        self.status_bar.addPermanentWidget(self.status_icons_widget)

        # Timer pollingu ikony sync (co 4s)
        self._sync_poll_timer = QTimer(self)
        self._sync_poll_timer.timeout.connect(self._update_sync_icon)
        self._sync_poll_timer.start(4000)

        # Timer pollingu ikony developer (co 3s)
        from core.developer.developer_manager import DeveloperManager
        self._developer_manager   = DeveloperManager()
        self._pending_develop_path: str | None = None
        self._dev_poll_timer = QTimer(self)
        self._dev_poll_timer.timeout.connect(self._update_developer_icon)
        self._dev_poll_timer.start(3000)

        # Timer pollingu ikony share bot (co 4s)
        self._bot_poll_timer = QTimer(self)
        self._bot_poll_timer.timeout.connect(self._update_bot_icon)
        self._bot_poll_timer.start(4000)
        QTimer.singleShot(1500, self._update_bot_icon)

        # Referencja do workera sprawdzającego miejsce na remote
        self._about_worker: RcloneAboutWorker | None = None

        # Sprawdź miejsce przy starcie (3s opóźnienie po splash)
        QTimer.singleShot(3000, self._start_space_check)

        # Cykliczne sprawdzanie co 15 minut
        self._space_check_timer = QTimer(self)
        self._space_check_timer.timeout.connect(self._start_space_check)
        self._space_check_timer.start(15 * 60 * 1000)

        # 3. INICJALIZACJA WIDOKÃ”W
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

        # Brak aparatu → otwórz ostatnią sesję w Darkroom
        if not self.camera_ready:
            QTimer.singleShot(100, self.darkroom_view.open_last_session)

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
        self.session_view.developer_requested.connect(self._on_developer_requested)

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

    def _update_sync_icon(self):
        """Odczytuje sync_status.json i aktualizuje ikonę sync w pasku stanu."""
        remote = self.settings.value("rclone/remote", "").strip()
        if not remote:
            self.icon_sync.setVisible(False)
            return

        base_dir    = self.settings.value(
            "session/directory", os.path.expanduser("~/Obrazy/sessions")
        )
        status_path = os.path.join(base_dir, "cloud", "sync_status.json")

        status  = "ok"
        free_mb = -1
        warn_mb = self.settings.value("rclone/warn_free_mb", 500, type=int)

        if os.path.exists(status_path):
            try:
                with open(status_path, encoding="utf-8") as f:
                    data = json.load(f)
                s = data.get("status", "ok")
                if s == "running":
                    status = "running"
                elif s == "warning":
                    status = "warning"
                free_mb = data.get("free_mb", -1)
            except Exception:
                pass

        space_warn = (free_mb >= 0 and free_mb < warn_mb)

        if status == "running":
            pix = self._make_status_pixmap("sync.png", active=True)
        elif status == "ok" and not space_warn:
            pix = self._make_status_pixmap("gdrive.png", active=True)
        else:
            pix = self._make_status_pixmap("gdrive.png", active=False)

        if free_mb >= 0:
            tooltip = self.tr(f"Google Drive — {free_mb} MB free")
            if space_warn:
                tooltip += self.tr(" ⚠ Low space")
            self.icon_sync.setToolTip(tooltip)
        else:
            self.icon_sync.setToolTip(self.tr("Google Drive sync"))

        self.icon_sync.setPixmap(pix)
        self.icon_sync.setVisible(True)

    def _start_space_check(self):
        """Uruchamia RcloneAboutWorker w tle — odświeża free_mb w ikonie."""
        remote = self.settings.value("rclone/remote", "").strip()
        if not remote:
            return
        if self._about_worker and self._about_worker.isRunning():
            return  # poprzednie sprawdzanie jeszcze trwa
        base_dir  = self.settings.value(
            "session/directory", os.path.expanduser("~/Obrazy/sessions")
        )
        cloud_dir = os.path.join(base_dir, "cloud")
        warn_mb   = self.settings.value("rclone/warn_free_mb", 500, type=int)
        self._about_worker = RcloneAboutWorker(remote, cloud_dir, warn_mb, parent=self)
        self._about_worker.finished.connect(lambda _: self._update_sync_icon())
        self._about_worker.start()

    def _sync_now(self):
        """Uruchamia rclone_sync_worker ręcznie (propaguje lokalne usunięcia na remote)."""
        remote = self.settings.value("rclone/remote", "").strip()
        dest   = self.settings.value("rclone/destination", "").strip()
        if not remote or not dest:
            self.status_bar.showMessage(self.tr("Sync: rclone not configured"), 4000)
            return

        base_dir  = self.settings.value(
            "session/directory", os.path.expanduser("~/Obrazy/sessions")
        )
        cloud_dir = os.path.join(base_dir, "cloud")

        # Sprawdź czy sync_worker już działa
        status_path = os.path.join(cloud_dir, "sync_status.json")
        if os.path.exists(status_path):
            try:
                with open(status_path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") == "running":
                    pid = data.get("pid")
                    if pid:
                        try:
                            os.kill(int(pid), 0)
                            self.status_bar.showMessage(
                                self.tr("Sync already in progress"), 3000
                            )
                            return
                        except (ProcessLookupError, ValueError):
                            pass  # martwy PID — startuj nowy
            except Exception:
                pass

        os.makedirs(cloud_dir, exist_ok=True)

        worker_path = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "core", "rclone_sync_worker.py")
        )
        try:
            subprocess.Popen(
                [sys.executable, worker_path, cloud_dir, remote, dest],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.status_bar.showMessage(self.tr("Sync started"), 3000)
            self._update_sync_icon()
        except Exception as e:
            self.status_bar.showMessage(self.tr(f"Sync error: {e}"), 5000)

    def _launch_tray_monitor(self):
        """Uruchamia tray monitor jako odłączony subprocess po zamknięciu aplikacji."""
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            subprocess.Popen(
                [sys.executable, "-m", "tray_monitor"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=project_dir,
            )
        except Exception as e:
            logging.getLogger(__name__).warning(f"Tray monitor launch failed: {e}")

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

        # TOOLS MENU
        tools_menu = menu_bar.addMenu(self.tr("Tools"))
        self._action_sync_now = QAction(self.tr("Sync now"), self)
        self._action_sync_now.triggered.connect(self._sync_now)
        tools_menu.addAction(self._action_sync_now)

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

    def _on_developer_requested(self, session_path: str):
        """
        Odebrano żądanie wywołania RAW z SessionRunner.
        Odkładamy ścieżkę — dialog otworzymy po zamknięciu active_dlg w _on_session_finished.
        """
        self._pending_develop_path = session_path

    def _on_session_finished(self, summary):
        """
        Callback po zakończeniu sesji.
        Dla trybu CLIENT i HOME: auto-load folderu sesji w Darkroom.
        Jeśli sesja zawierała RAW — otwiera DevelopDialog.
        """
        from core.session_context import SessionMode
        ctx = summary.context
        if ctx.mode != SessionMode.PRIVATE and ctx.session_path:
            self.darkroom_view.load_images(ctx.session_path)

        # Otwórz dialog wywołania RAW jeśli runner zgłosił pliki RAW
        if self._pending_develop_path:
            session_path = self._pending_develop_path
            self._pending_develop_path = None
            self._show_develop_dialog(session_path)

        # Odśwież info o miejscu na remote po zakończeniu sesji
        QTimer.singleShot(5000, self._start_space_check)

    def _show_develop_dialog(self, session_path: str):
        """Otwiera DevelopDialog i po akceptacji dodaje sesję do kolejki developer."""
        from ui.dialogs.develop_dialog import DevelopDialog
        presets_dir = Path(__file__).parent.parent / "presets"
        dlg = DevelopDialog(session_path, presets_dir, parent=self)
        if dlg.exec():
            self._developer_manager.start(
                session_path  = session_path,
                preset        = dlg.selected_preset,
                kelvin        = dlg.selected_kelvin,
            )
            self._update_developer_icon()

    def _on_developer_icon_clicked(self):
        """Klik na ikonę developera — retry gdy błąd."""
        state, _, _ = self._developer_manager.get_status()
        if state == "error":
            count = self._developer_manager.retry_errors()
            if count:
                self.status_bar.showMessage(
                    self.tr(f"Developer: retrying {count} session(s)..."), 4000
                )
            self._update_developer_icon()

    def _update_developer_icon(self):
        """Odczytuje status developer_manager i aktualizuje ikonę w pasku stanu."""
        state, processed, total = self._developer_manager.get_status()

        if state == "inactive":
            self.icon_developer.setVisible(False)
            self.icon_developer.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if state == "active":
            pix = self._make_status_pixmap("developer.svg", active=True)
            remaining = total - processed
            self.icon_developer.setToolTip(
                self.tr(f"Developer: {remaining} remaining of {total}")
            )
            self.icon_developer.setCursor(Qt.CursorShape.ArrowCursor)
        else:  # error
            pix = self._make_status_pixmap("developer.svg", active=False)
            msg = self._developer_manager.get_last_error()
            self.icon_developer.setToolTip(
                self.tr(f"Developer error — click to retry\n{msg}") if msg
                else self.tr("Developer error — click to retry")
            )
            self.icon_developer.setCursor(Qt.CursorShape.PointingHandCursor)

        self.icon_developer.setPixmap(pix)
        self.icon_developer.setVisible(True)

    def _update_bot_icon(self):
        """Odczytuje share_bot_status.json i aktualizuje ikonę bota w pasku stanu."""
        token = self.settings.value("telegram/bot_token", "").strip()
        if not token:
            self.icon_bot.setVisible(False)
            return

        import json as _json
        status_file = os.path.expanduser(
            "~/.local/share/photo_app/share_bot_status.json"
        )
        active = False
        status = "idle"
        try:
            if os.path.exists(status_file):
                with open(status_file, encoding="utf-8") as f:
                    data = _json.load(f)
                pid = data.get("pid")
                if pid:
                    try:
                        os.kill(int(pid), 0)
                        active = True
                        status = data.get("status", "idle")
                    except (ProcessLookupError, ValueError):
                        pass
        except Exception:
            pass

        tg_icon = QIcon.fromTheme("telegram")
        size = 24
        pix = tg_icon.pixmap(size, size) if not tg_icon.isNull() else QPixmap()
        if not active and not pix.isNull():
            out = QPixmap(pix.size())
            out.fill(Qt.GlobalColor.transparent)
            painter = QPainter(out)
            painter.setOpacity(0.35)
            painter.drawPixmap(0, 0, pix)
            painter.end()
            pix = out
        self.icon_bot.setPixmap(pix)

        labels = {"idle": "waiting", "active": "active", "sending": "sending photos…"}
        if active:
            self.icon_bot.setToolTip(
                self.tr(f"Share bot — {labels.get(status, status)}")
            )
        else:
            self.icon_bot.setToolTip(self.tr("Share bot — not running"))

        self.icon_bot.setVisible(True)

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

        # Tray monitor — gdy sync lub developer aktualnie w toku
        if self._is_sync_running() or self._developer_manager.get_pending_count() > 0:
            self._show_sync_close_info()
            self._launch_tray_monitor()

        super().closeEvent(event)

    def _is_sync_running(self) -> bool:
        """Sprawdza czy rclone_sync_worker aktualnie pracuje."""
        remote = self.settings.value("rclone/remote", "").strip()
        if not remote:
            return False
        base_dir    = self.settings.value(
            "session/directory", os.path.expanduser("~/Obrazy/sessions")
        )
        status_path = os.path.join(base_dir, "cloud", "sync_status.json")
        if not os.path.exists(status_path):
            return False
        try:
            with open(status_path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("status") == "running"
        except Exception:
            return False

    def _show_sync_close_info(self):
        """Informuje użytkownika że sync trwa i będzie dokończony przez tray."""
        msg = QMessageBox(self)
        msg.setWindowTitle(self.tr("Sync in progress"))
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText(self.tr(
            "Google Drive sync is still in progress.\n\n"
            "The application will close now. Sync will complete in the background\n"
            "and the tray icon will disappear when finished."
        ))
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

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
            self._update_sync_icon()
            QTimer.singleShot(1000, self._start_space_check)
            self.status_bar.showMessage(self.tr("Preferences saved"), 2000)

    def show_about(self):
        QMessageBox.information(self, self.tr("About"), self.tr("Sessions Assistant 0.99\nAuthor: Grzeza"))

    def retranslateUi(self):
        self.setWindowTitle(self.tr("Sessions Assistant 0.99"))