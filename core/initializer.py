"""
Startup diagnostics — wyświetla info na splash screen.
Używa CameraProbe do komunikacji z aparatem.
"""
import platform
import gphoto2 as gp
from PyQt6.QtCore import Qt, QObject
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from core.camera_probe import CameraProbe


class AppInitializer(QObject):
    def __init__(self):
        super().__init__()

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

        if result['mode'] != 'Fv':
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
