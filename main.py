import sys
import os

# Logging musi być skonfigurowany przed importem pozostałych modułów
import core.log_setup as _log_setup
_log_setup.setup(verbose=("-verbose" in sys.argv))

from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtGui import QColor, QPalette, QPixmap, QIcon
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType, QTranslator, QLocale, QSettings
from ui.main_window import MainWindow
from ui.styles import APP_STYLE
from core.initializer import AppInitializer


def _qt_message_handler(mode, context, message):
    """Filtruje zbędne ostrzeżenia Qt — przepuszcza tylko błędy krytyczne."""
    if "Failed to register with host portal" in message:
        return
    if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        print(f"Qt: {message}", file=sys.stderr)


qInstallMessageHandler(_qt_message_handler)



def _load_translator(app: QApplication) -> QTranslator | None:
    """Wczytuje tłumaczenie na podstawie ustawień lub lokalizacji systemu."""
    settings = QSettings("Grzeza", "SessionsAssistant")
    lang = settings.value("app/language", "")  # "" = auto
    if not lang:
        lang = QLocale.system().name()[:2]      # np. "pl", "ru", "uk"
    ts_dir = os.path.join(os.path.dirname(__file__), "locales")
    qm_path = os.path.join(ts_dir, f"{lang}.qm")
    if not os.path.exists(qm_path):
        return None
    translator = QTranslator(app)
    if translator.load(qm_path):
        app.installTranslator(translator)
        return translator
    return None


_APP_PID_FILE        = os.path.expanduser("~/.local/share/photo_app/app.pid")
_TRAY_LOCK_FILE      = os.path.expanduser("~/.local/share/photo_app/tray_monitor.lock")
_BOT_TRAY_LOCK_FILE  = os.path.expanduser("~/.local/share/photo_app/share_bot_tray.lock")


def _kill_pid_file(path: str, signum: int = 15):
    """Wysyła sygnał do procesu z pliku PID i usuwa plik."""
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            pid = int(f.read().strip())
        os.kill(pid, signum)
    except (ValueError, ProcessLookupError, OSError):
        pass
    try:
        os.unlink(path)
    except OSError:
        pass


def _write_app_pid():
    """Zapisuje PID bieżącej instancji aplikacji."""
    os.makedirs(os.path.dirname(_APP_PID_FILE), exist_ok=True)
    try:
        with open(_APP_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def main():
    # Zamknij poprzednią instancję aplikacji (niesie ikonę bota w pasku stanu)
    _kill_pid_file(_APP_PID_FILE)
    # Zamknij tray_monitor i share_bot_tray z poprzedniej sesji
    _kill_pid_file(_TRAY_LOCK_FILE)
    _kill_pid_file(_BOT_TRAY_LOCK_FILE)
    _write_app_pid()

    app = QApplication(sys.argv)
    _load_translator(app)
    app.setStyle('Fusion')
    app.setStyleSheet(APP_STYLE)

    # Biały/przygaszony focus ring zamiast niebieskiego — ujednolicony w całym projekcie
    pal = app.palette()
    pal.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Highlight, QColor(160, 160, 160))
    pal.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.HighlightedText, QColor(10, 10, 10))
    app.setPalette(pal)

    # Ikona aplikacji
    app.setWindowIcon(QIcon("assets/icons/favicon/web-app-manifest-192x192.png"))
    # setDesktopFileName — Plank sięga po ikonę z .desktop z pominięciem PyQt6
    app.setDesktopFileName("sessions_assistant")

    # Grafika startowa
    pixmap = QPixmap("assets/pictures/startup-picture-6.png")
    splash = QSplashScreen(pixmap)
    splash.show()

    initializer = AppInitializer()
    init_results = initializer.run_all_checks(splash)

    window = MainWindow(
        camera_on=init_results.get("camera_on", False),
        sd_on=init_results.get("sd_on", False)
    )

    window.show()
    splash.finish(window)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
