import sys
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtGui import QPixmap, QIcon
from ui.main_window import MainWindow
from core.initializer import AppInitializer


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Ikona aplikacji
    app.setWindowIcon(QIcon("assets/icons/favicon/web-app-manifest-192x192.png"))

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
