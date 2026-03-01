import sys
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import qInstallMessageHandler, QtMsgType
from ui.main_window import MainWindow
from core.initializer import AppInitializer


def _qt_message_handler(mode, context, message):
    """Filtruje zbędne ostrzeżenia Qt — przepuszcza tylko błędy krytyczne."""
    if "Failed to register with host portal" in message:
        return
    if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        print(f"Qt: {message}", file=sys.stderr)


qInstallMessageHandler(_qt_message_handler)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(
        "QToolTip { color: #bbbbbb; background-color: #2b2b2b; border: 1px solid #555555; }"
    )

    # Ikona aplikacji
    app.setWindowIcon(QIcon("assets/icons/favicon/web-app-manifest-192x192.png"))
    # setDesktopFileName — Plank sięga po ikonę z .desktop z pominięciem PyQt6
    app.setDesktopFileName("sessions_assistant")

    # Grafika startowa
    pixmap = QPixmap("assets/pictures/startup-picture-3.jpg")
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
