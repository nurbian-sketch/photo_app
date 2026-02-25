"""
CameraDownloadDialog — pobiera pliki z karty SD aparatu przez gphoto2 (PTP).
Wymaga wolnego portu USB (Live View musi być zatrzymane).
"""
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QProgressBar, QMessageBox,
    QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────── Worker: listuje pliki na karcie

class _ListFilesWorker(QThread):
    """Pobiera listę plików z kamery w tle."""
    done = pyqtSignal(list, str)   # [(folder, filename), ...], error_msg

    def run(self):
        import gphoto2 as gp
        files = []
        error = ''
        camera = None
        context = gp.Context()
        try:
            camera = gp.Camera()
            camera.init(context)
            dcim = '/store_00020001/DCIM'
            folders = camera.folder_list_folders(dcim, context)
            for i in range(folders.count()):
                subfolder = folders.get_name(i)
                folder_path = f'{dcim}/{subfolder}'
                filelist = camera.folder_list_files(folder_path, context)
                for j in range(filelist.count()):
                    fname = filelist.get_name(j)
                    files.append((folder_path, fname))
        except Exception as e:
            error = str(e)
        finally:
            if camera:
                try:
                    camera.exit(context)
                except Exception:
                    pass
        self.done.emit(files, error)


# ─────────────────────────── Worker: pobiera zaznaczone pliki

class _DownloadWorker(QThread):
    """Pobiera wskazane pliki z kamery do katalogu docelowego."""
    progress = pyqtSignal(int, str)   # (percent, current_filename)
    done = pyqtSignal(str, str)       # (dest_dir, error_msg)

    def __init__(self, files_to_download, dest_dir):
        super().__init__()
        # files_to_download: [(folder, filename), ...]
        self._files = files_to_download
        self._dest = dest_dir

    def run(self):
        import gphoto2 as gp
        error = ''
        camera = None
        context = gp.Context()
        downloaded = 0
        total = len(self._files)
        os.makedirs(self._dest, exist_ok=True)
        try:
            camera = gp.Camera()
            camera.init(context)
            for i, (folder, fname) in enumerate(self._files):
                self.progress.emit(
                    int(i / total * 100),
                    fname
                )
                try:
                    camera_file = camera.file_get(
                        folder, fname,
                        gp.GP_FILE_TYPE_NORMAL, context
                    )
                    local_path = os.path.join(self._dest, fname)
                    # Nie nadpisuj istniejących plików
                    if os.path.exists(local_path):
                        base, ext = os.path.splitext(fname)
                        ts = datetime.now().strftime("%H%M%S")
                        local_path = os.path.join(self._dest, f"{base}_{ts}{ext}")
                    camera_file.save(local_path)
                    downloaded += 1
                except Exception as e:
                    logger.warning(f"Download {fname}: {e}")
        except Exception as e:
            error = str(e)
        finally:
            if camera:
                try:
                    camera.exit(context)
                except Exception:
                    pass
        self.progress.emit(100, '')
        self.done.emit(self._dest if downloaded > 0 else '', error)


# ─────────────────────────── Dialog

class CameraDownloadDialog(QDialog):
    """
    Dialog pobierania plików z karty SD aparatu.
    Zwraca `downloaded_dir` po exec() jeśli pobrano pliki.
    """

    def __init__(self, dest_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download from Camera")
        self.setMinimumSize(500, 400)
        self.downloaded_dir = None
        self._dest_dir = dest_dir
        self._files = []    # [(folder, fname)]
        self._worker = None

        self._init_ui()
        self._start_listing()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self._status = QLabel("Connecting to camera…")
        layout.addWidget(self._status)

        # Select all / none
        sel_row = QHBoxLayout()
        self._chk_all = QCheckBox("Select all")
        self._chk_all.setChecked(True)
        self._chk_all.toggled.connect(self._toggle_all)
        sel_row.addWidget(self._chk_all)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        self._list = QListWidget()
        self._list.setEnabled(False)
        layout.addWidget(self._list)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_download = QPushButton("Download Selected")
        self._btn_download.setEnabled(False)
        self._btn_download.setStyleSheet(
            "font-weight: bold; background-color: #1565c0; color: white;"
        )
        self._btn_download.clicked.connect(self._start_download)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_download)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _start_listing(self):
        self._worker = _ListFilesWorker()
        self._worker.done.connect(self._on_list_done)
        self._worker.start()

    def _on_list_done(self, files, error):
        if error:
            self._status.setText(f"Error: {error}")
            return
        if not files:
            self._status.setText("No files found on camera SD card.")
            return

        self._files = files
        self._list.setEnabled(True)
        self._btn_download.setEnabled(True)
        self._status.setText(f"Found {len(files)} file(s) on camera.")

        for folder, fname in files:
            item = QListWidgetItem(fname)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, (folder, fname))
            self._list.addItem(item)

    def _toggle_all(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)

    def _start_download(self):
        selected = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))

        if not selected:
            QMessageBox.information(self, "Download", "No files selected.")
            return

        # Katalog: session_dir/YYYY-MM-DD_HH-MM-SS_camera
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dest = os.path.join(self._dest_dir, f"{ts}_camera")

        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._btn_download.setEnabled(False)
        self._list.setEnabled(False)

        self._worker = _DownloadWorker(selected, dest)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_download_done)
        self._worker.start()

    def _on_progress(self, percent, filename):
        self._progress.setValue(percent)
        if filename:
            self._status.setText(f"Downloading: {filename}")

    def _on_download_done(self, dest_dir, error):
        if error:
            QMessageBox.warning(self, "Download", f"Error: {error}")
        if dest_dir:
            self.downloaded_dir = dest_dir
            self.accept()
        else:
            self._status.setText("Download failed — no files saved.")
            self._btn_download.setEnabled(True)
            self._list.setEnabled(True)
