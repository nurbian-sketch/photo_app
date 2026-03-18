"""
tray_monitor/__main__.py

Entry point: python3 -m tray_monitor
Singleton — drugi egzemplarz wychodzi cicho (lock file).
"""
import os
import sys

# Lock file — jeden egzemplarz
LOCK_FILE = os.path.expanduser("~/.local/share/photo_app/tray_monitor.lock")


def _acquire_lock() -> bool:
    """Zwraca True jeśli udało się przejąć lock."""
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    try:
        # Sprawdź czy PID z lock file żyje
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)   # sygnał 0 = sprawdzenie czy proces istnieje
                return False      # żyje — nie startujemy
            except (ProcessLookupError, PermissionError):
                pass              # martwy PID — nadpisujemy
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return True   # przy błędzie — startuj mimo wszystko


def _release_lock():
    try:
        os.unlink(LOCK_FILE)
    except OSError:
        pass


def main():
    if not _acquire_lock():
        sys.exit(0)   # już działa — wyjdź cicho

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QCoreApplication

    app = QApplication(sys.argv)
    app.setApplicationName("sessions-sync-monitor")
    app.setQuitOnLastWindowClosed(False)   # nie zamykaj przy braku okien

    # Sprawdź czy system tray jest dostępny
    from PyQt6.QtWidgets import QSystemTrayIcon
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray niedostępny", file=sys.stderr)
        _release_lock()
        sys.exit(1)

    from tray_monitor.monitor_app import SyncMonitorApp
    _monitor = SyncMonitorApp(app)

    try:
        code = app.exec()
    finally:
        _release_lock()

    sys.exit(code)


if __name__ == "__main__":
    main()
