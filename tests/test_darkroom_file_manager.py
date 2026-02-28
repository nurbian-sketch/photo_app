"""
Testy jednostkowe dla refaktoru File Manager w darkroom_view.py
+ camera_import_dialog.py + camera_card_service.py

Uruchom: cd ~/Projekty/photo_app && venv/bin/python3 -m pytest tests/test_darkroom_file_manager.py -v
"""
import os
import sys
import tempfile
import shutil

# Offscreen — brak display fizycznego
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

# Ścieżka projektu
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtWidgets import QApplication, QListWidgetItem
from PyQt6.QtCore import Qt

# QApplication musi istnieć przed tworzeniem widgetów
_app = QApplication.instance() or QApplication(sys.argv)


# ─────────────────────────── Test 2a — Filtr rozszerzeń

class TestActiveExtensions:

    def setup_method(self):
        from ui.views.darkroom_view import DarkroomView
        self.view = DarkroomView()

    def teardown_method(self):
        self.view.close()

    def test_both_visible_by_default(self):
        exts = self.view._active_extensions
        assert '.jpg' in exts
        assert '.cr3' in exts

    def test_hide_raw_returns_only_jpeg(self):
        self.view._hide_raw  = True
        self.view._hide_jpeg = False
        exts = self.view._active_extensions
        assert '.jpg' in exts
        assert '.cr3' not in exts

    def test_hide_jpeg_returns_only_raw(self):
        self.view._hide_raw  = False
        self.view._hide_jpeg = True
        exts = self.view._active_extensions
        assert '.cr3' in exts
        assert '.jpg' not in exts

    def test_both_flags_false_returns_all(self):
        self.view._hide_raw  = False
        self.view._hide_jpeg = False
        exts = self.view._active_extensions
        assert '.jpg' in exts and '.cr3' in exts


# ─────────────────────────── Test 2b — Wzajemna blokada toggle'i

class TestToggleMutualExclusion:

    def setup_method(self):
        from ui.views.darkroom_view import DarkroomView
        self.view = DarkroomView()

    def teardown_method(self):
        self.view.close()

    def test_hide_raw_disables_hide_jpeg(self):
        self.view._on_hide_raw_toggled(True)
        assert not self.view.btn_hide_jpeg.isEnabled()

    def test_uncheck_hide_raw_reenables_hide_jpeg(self):
        self.view._on_hide_raw_toggled(True)
        self.view._on_hide_raw_toggled(False)
        assert self.view.btn_hide_jpeg.isEnabled()

    def test_hide_jpeg_disables_hide_raw(self):
        self.view._on_hide_jpeg_toggled(True)
        assert not self.view.btn_hide_raw.isEnabled()

    def test_uncheck_hide_jpeg_reenables_hide_raw(self):
        self.view._on_hide_jpeg_toggled(True)
        self.view._on_hide_jpeg_toggled(False)
        assert self.view.btn_hide_raw.isEnabled()


# ─────────────────────────── Test 2c — _get_selected_sd_files

class TestGetSelectedSdFiles:

    def setup_method(self):
        from ui.views.darkroom_view import DarkroomView, _ITEM_TYPE_ROLE, _PTP_FOLDER_ROLE
        self.view = DarkroomView()
        self._ITEM_TYPE_ROLE  = _ITEM_TYPE_ROLE
        self._PTP_FOLDER_ROLE = _PTP_FOLDER_ROLE

    def teardown_method(self):
        self.view.close()

    def _make_file_item(self, fname, folder, checked):
        item = QListWidgetItem(fname)
        item.setData(self._ITEM_TYPE_ROLE, 'file')
        item.setData(self._PTP_FOLDER_ROLE, folder)
        item.setData(Qt.ItemDataRole.UserRole,     fname)
        item.setData(Qt.ItemDataRole.UserRole + 1, checked)
        return item

    def _make_nav_item(self, label, path):
        item = QListWidgetItem(label)
        item.setData(self._ITEM_TYPE_ROLE, 'parent')
        item.setData(Qt.ItemDataRole.UserRole,     path)
        item.setData(Qt.ItemDataRole.UserRole + 1, False)
        return item

    def test_returns_only_checked_files(self):
        lw = self.view.list_widget
        lw.addItem(self._make_file_item('IMG_001.CR3', '/DCIM/100CANON', True))
        lw.addItem(self._make_file_item('IMG_002.CR3', '/DCIM/100CANON', False))
        lw.addItem(self._make_file_item('IMG_003.CR3', '/DCIM/100CANON', True))

        result = self.view._get_selected_sd_files()
        assert len(result) == 2
        fnames = [r[1] for r in result]
        assert 'IMG_001.CR3' in fnames
        assert 'IMG_003.CR3' in fnames
        assert 'IMG_002.CR3' not in fnames

    def test_skips_parent_and_folder_items(self):
        from ui.views.darkroom_view import _ITEM_TYPE_ROLE
        lw = self.view.list_widget

        nav = QListWidgetItem("← Sessions")
        nav.setData(_ITEM_TYPE_ROLE, 'parent')
        nav.setData(Qt.ItemDataRole.UserRole + 1, True)  # zaznaczony, ale parent
        lw.addItem(nav)

        folder = QListWidgetItem("Subfolder")
        folder.setData(_ITEM_TYPE_ROLE, 'folder')
        folder.setData(Qt.ItemDataRole.UserRole + 1, True)
        lw.addItem(folder)

        lw.addItem(self._make_file_item('IMG_001.CR3', '/DCIM/100', True))

        result = self.view._get_selected_sd_files()
        assert len(result) == 1
        assert result[0][1] == 'IMG_001.CR3'


# ─────────────────────────── Test 2d — CameraImportDialog — domyślna nazwa sesji

class TestDefaultSessionName:

    def test_format_yyyy_mm_dd_nnn(self):
        from ui.dialogs.camera_import_dialog import CameraImportDialog
        with tempfile.TemporaryDirectory() as tmpdir:
            dlg = CameraImportDialog([], tmpdir)
            name = dlg._default_session_name()
            # Format: YYYY-MM-DD_NNN
            assert len(name) == 14, f"Oczekiwano 14 znaków, dostałem: {name!r}"
            parts = name.rsplit('_', 1)
            assert len(parts) == 2
            assert parts[1].isdigit()
            assert len(parts[1]) == 3
            dlg.close()

    def test_increments_when_exists(self):
        from ui.dialogs.camera_import_dialog import CameraImportDialog
        from datetime import date
        with tempfile.TemporaryDirectory() as tmpdir:
            today = date.today().strftime('%Y-%m-%d')
            # Utwórz _001 żeby wymusić _002
            os.makedirs(os.path.join(tmpdir, f'{today}_001'))
            dlg = CameraImportDialog([], tmpdir)
            name = dlg._default_session_name()
            assert name == f'{today}_002', f"Oczekiwano _002, dostałem: {name!r}"
            dlg.close()


# ─────────────────────────── Test 2e — _apply_filter w _CopyWorker

class TestCopyWorkerApplyFilter:

    def _make_worker(self, files, fmt):
        from ui.dialogs.camera_import_dialog import _CopyWorker
        return _CopyWorker(files, '/tmp/test', fmt)

    def test_filter_all_returns_all(self):
        files = [('/f', 'a.CR3'), ('/f', 'b.JPG'), ('/f', 'c.png')]
        w = self._make_worker(files, 'all')
        assert w._apply_filter(files) == files

    def test_filter_jpeg_returns_only_jpeg(self):
        files = [('/f', 'a.CR3'), ('/f', 'b.jpg'), ('/f', 'c.PNG'), ('/f', 'd.nef')]
        w = self._make_worker(files, 'jpeg')
        result = w._apply_filter(files)
        fnames = [r[1] for r in result]
        assert 'b.jpg' in fnames
        assert 'c.PNG' in fnames
        assert 'a.CR3' not in fnames
        assert 'd.nef' not in fnames

    def test_filter_raw_returns_only_raw(self):
        files = [('/f', 'a.cr3'), ('/f', 'b.jpg'), ('/f', 'c.NEF'), ('/f', 'd.ARW')]
        w = self._make_worker(files, 'raw')
        result = w._apply_filter(files)
        fnames = [r[1] for r in result]
        assert 'a.cr3' in fnames
        assert 'c.NEF' in fnames
        assert 'd.ARW' in fnames
        assert 'b.jpg' not in fnames

    def test_filter_empty_list(self):
        w = self._make_worker([], 'jpeg')
        assert w._apply_filter([]) == []


# ─────────────────────────── Test 2f — format_camera_card gdy gphoto2 niedostępne

class TestFormatCameraCard:

    def test_gphoto2_not_found_returns_false(self, monkeypatch):
        """Symuluje brak gphoto2 w PATH."""
        from core.camera_card_service import format_camera_card
        import subprocess

        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("gphoto2 not found")

        monkeypatch.setattr(subprocess, 'run', fake_run)
        ok, msg = format_camera_card()
        assert ok is False
        assert 'gphoto2 not found' in msg.lower() or 'not found' in msg.lower()

    def test_timeout_returns_false(self, monkeypatch):
        """Symuluje timeout gphoto2."""
        from core.camera_card_service import format_camera_card
        import subprocess

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 60)

        monkeypatch.setattr(subprocess, 'run', fake_run)
        ok, msg = format_camera_card(timeout=60)
        assert ok is False
        assert 'timeout' in msg.lower() or '60' in msg
