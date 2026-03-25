"""
share_bot_tray/__main__.py

Punkt startowy monitora tray dla share_bot.
Uruchamia core/share_bot.py jako subprocess i wyświetla ikonę w zasobniku systemowym.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys

from PyQt6.QtWidgets import QApplication

# Katalog projektu (rodzic share_bot_tray/)
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_DIR)

from share_bot_tray.bot_tray_app import BotTrayApp  # noqa: E402

_DATA_DIR  = os.path.expanduser("~/.local/share/photo_app")
_LOCK_FILE = os.path.join(_DATA_DIR, "share_bot_tray.lock")


def _write_lock():
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_lock():
    try:
        os.unlink(_LOCK_FILE)
    except OSError:
        pass


def _start_bot():
    """Uruchamia core/share_bot.py jako odłączony subprocess."""
    bot_path = os.path.join(_PROJECT_DIR, "core", "share_bot.py")
    if not os.path.exists(bot_path):
        return
    try:
        subprocess.Popen(
            [sys.executable, bot_path],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=_PROJECT_DIR,
        )
    except Exception:
        pass


def main():
    # Opcjonalny PID rodzica (głównej aplikacji) — tray ukryty dopóki rodzic żyje
    parent_pid: int | None = None
    if "--parent-pid" in sys.argv:
        idx = sys.argv.index("--parent-pid")
        try:
            parent_pid = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            pass

    _write_lock()
    _start_bot()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = BotTrayApp(app, parent_pid=parent_pid)  # noqa: F841

    def _on_sigterm(signum, frame):
        _remove_lock()
        app.quit()

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        ret = app.exec()
    finally:
        _remove_lock()

    sys.exit(ret)


if __name__ == "__main__":
    main()
