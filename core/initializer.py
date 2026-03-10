"""
Startup diagnostics — wyświetla info na splash screen.
Używa CameraProbe do komunikacji z aparatem.
"""
import os
import sys
import platform
import subprocess
import gphoto2 as gp
from PyQt6.QtCore import Qt, QObject, QSettings
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from core.camera_probe import CameraProbe


class AppInitializer(QObject):
    def __init__(self):
        super().__init__()

    def _ensure_share_bot(self) -> str:
        """Uruchamia share_bot.py jeśli nie działa. Zwraca komunikat do splash."""
        settings = QSettings("Grzeza", "SessionsAssistant")
        token = settings.value("telegram/bot_token", "").strip()
        if not token:
            return "Share bot: brak tokenu Telegram — pomijam"

        # Sprawdź czy bot już działa
        result = subprocess.run(
            ["pgrep", "-f", "share_bot.py"],
            capture_output=True,
        )
        if result.returncode == 0:
            return "Share bot: już uruchomiony"

        # Uruchom jako niezależny proces (przeżywa zamknięcie aplikacji)
        bot_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "core", "share_bot.py")
        env = os.environ.copy()
        env["SHARE_BOT_TOKEN"] = token
        subprocess.Popen(
            [sys.executable, bot_path],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        return "Share bot: uruchomiony"

    def run_all_checks(self, splash) -> dict:
        def msg(text):
            splash.showMessage(
                self.tr(text),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
                QColor("white")
            )
            print(self.tr(text))
            QApplication.processEvents()

        print("\n" + "=" * 60)
        print(self.tr("SESSIONS ASSISTANT STARTUP REPORT").center(60, "="))
        print("=" * 60)

        # Wersja biblioteki
        gp_ver = gp.gp_library_version(gp.GP_VERSION_SHORT)[0]
        sys_info = f"{platform.system()} {platform.release()}"
        msg(f"gphoto2 library version {gp_ver} detected on {sys_info}")

        # Share bot
        msg(self._ensure_share_bot())

        # Probe aparatu
        probe = CameraProbe()
        connected = probe.connect()

        if not connected:
            msg("WARNING: Camera not detected")
            probe.release()
            msg("System ready. Launching Sessions Assistant ...")
            print("=" * 60 + "\n")
            return {'camera_on': False, 'sd_on': False}

        result = probe.full_check()

        msg(f"Camera detected: {result['model']}")
        msg(f"Mode: {result['mode']}")

        if result['mode'] and result['mode'] != 'Fv':
            msg(f"WARNING: Camera not in Fv mode ({result['mode']})")

        storage = result['storage']
        if storage['ok']:
            msg(f"SD Card: {storage['total_gb']} GB "
                f"(Free {storage['free_gb']} GB)")
            msg(f"Card contains {storage['on_card']} images "
                f"({storage['images_left']} shots left)")
        else:
            msg("WARNING: SD card not available")

        if result['battery'] >= 0:
            msg(f"Battery level: {result['battery']}%")

        for w in result['warnings']:
            msg(f"WARNING: {w}")

        probe.release()
        msg("System ready. Launching Sessions Assistant ...")
        print("=" * 60 + "\n")

        return {
            'camera_on': result['camera_on'],
            'sd_on': result['sd_on'],
        }
