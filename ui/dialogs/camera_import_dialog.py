"""
ui/dialogs/camera_import_dialog.py

Dialog importu zdjęć z karty aparatu.
Przyjmuje listę wybranych plików (folder_ptp, filename), docelowy katalog sesji,
pozwala nadać nazwę sesji i filtrować format (All / JPEG / RAW).
Kopiowanie odbywa się w osobnym wątku — UI nie jest blokowane.
"""
import os
import subprocess
import logging
from datetime import date

import gphoto2 as gp
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QProgressBar, QComboBox, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

logger = logging.getLogger(__name__)

RAW_EXTENSIONS  = {'.cr3', '.cr2', '.nef', '.arw', '.orf', '.rw2', '.dng'}
JPEG_EXTENSIONS = {'.jpg', '.jpeg', '.png'}


# ─────────────────────────── Worker kopiowania

class _CopyWorker(QThread):
    """
    Kopiuje wybrane pliki z karty aparatu do katalogu lokalnego.
    Emituje file_copied() po każdym pliku, finished() na końcu.
    """

    file_copied = pyqtSignal(int, int, str)   # (current, total, filename)
    finished    = pyqtSignal(str, str)         # (dest_dir, error_msg)

    def __init__(
        self,
        selected: list[tuple[str, str]],   # [(folder_ptp, filename), ...]
        dest_dir: str,
        fmt_filter: str,                   # 'all' | 'jpeg' | 'raw'
    ):
        super().__init__()
        self._selected  = selected
        self._dest      = dest_dir
        self._filter    = fmt_filter

    def run(self):
        camera  = None
        context = gp.Context()
        copied  = 0
        error   = ''

        # Filtruj listę wg formatu
        files = self._apply_filter(self._selected)
        total = len(files)

        try:
            camera = gp.Camera()
            camera.init(context)

            os.makedirs(self._dest, exist_ok=True)

            for idx, (folder, fname) in enumerate(files):
                self.file_copied.emit(idx, total, fname)
                local_path = os.path.join(self._dest, fname)

                if os.path.exists(local_path):
                    copied += 1
                    continue

                saved = False
                for attempt in range(2):
                    try:
                        cam_file = gp.CameraFile()
                        camera.file_get(
                            folder, fname,
                            gp.GP_FILE_TYPE_NORMAL,
                            cam_file, context
                        )
                        cam_file.save(local_path)
                        saved = True
                        break
                    except Exception as e:
                        code = getattr(e, 'code', None)
                        logger.warning(f"Kopiowanie {fname} (próba {attempt+1}): {e}")
                        if attempt == 0 and code in (-7, -52, -110):
                            # Reset połączenia USB po błędzie I/O
                            try:
                                camera.exit(context)
                            except Exception:
                                pass
                            import time; time.sleep(2.5)
                            context = gp.Context()
                            camera = gp.Camera()
                            camera.init(context)

                if saved:
                    copied += 1
                else:
                    logger.warning(f"Pominięto {fname} — nie udało się pobrać")

            self.file_copied.emit(total, total, '')

        except Exception as e:
            error = str(e)
            logger.error(f"CopyWorker: {e}")
        finally:
            if camera:
                try:
                    camera.exit(context)
                except Exception:
                    pass

        self.finished.emit(self._dest if copied > 0 else '', error)

    def _apply_filter(self, files: list) -> list:
        if self._filter == 'all':
            return files
        result = []
        for folder, fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if self._filter == 'jpeg' and ext in JPEG_EXTENSIONS:
                result.append((folder, fname))
            elif self._filter == 'raw' and ext in RAW_EXTENSIONS:
                result.append((folder, fname))
        return result


# ─────────────────────────── Dialog

class CameraImportDialog(QDialog):
    """
    Dialog importu z karty aparatu.

    Sygnały:
        import_finished(dest_dir) — import zakończony sukcesem, dest_dir = ścieżka
    """

    import_finished = pyqtSignal(str)

    def __init__(
        self,
        selected_files: list[tuple[str, str]],   # [(folder_ptp, filename)]
        sessions_dir: str,
        parent=None,
    ):
        super().__init__(parent)
        self._selected      = selected_files
        self._sessions_dir  = sessions_dir
        self._worker        = None

        self.setWindowTitle(self.tr("Import from Camera Card"))
        self.setMinimumWidth(480)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )
        self._build_ui()
        self._refresh_dest_preview()

    def showEvent(self, event):
        super().showEvent(event)
        # Zaznacz tekst pola nazwy sesji — użytkownik może od razu wpisać nową
        self._edit_name.setFocus()
        self._edit_name.selectAll()

    # ─────────────────────────── UI

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Liczba wybranych plików
        count = len(self._selected)
        lbl_count = QLabel(self.tr(f"Selected files: {count}"))
        lbl_count.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(lbl_count)

        # Filtr formatu
        row_fmt = QHBoxLayout()
        row_fmt.addWidget(QLabel(self.tr("Copy:")))
        self._combo_fmt = QComboBox()
        self._combo_fmt.addItems([
            self.tr("All files"),
            self.tr("JPEG only"),
            self.tr("RAW only"),
        ])
        self._combo_fmt.currentIndexChanged.connect(self._refresh_dest_preview)
        row_fmt.addWidget(self._combo_fmt)
        row_fmt.addStretch()
        layout.addLayout(row_fmt)

        # Nazwa sesji
        row_name = QHBoxLayout()
        row_name.addWidget(QLabel(self.tr("Session name:")))
        self._edit_name = QLineEdit()
        self._edit_name.setText(self._default_session_name())
        self._edit_name.textChanged.connect(self._refresh_dest_preview)
        row_name.addWidget(self._edit_name, 1)
        layout.addLayout(row_name)

        # Podgląd ścieżki docelowej
        self._lbl_dest = QLabel()
        self._lbl_dest.setStyleSheet(
            "color: #888; font-size: 11px; padding: 4px 0;"
        )
        self._lbl_dest.setWordWrap(True)
        layout.addWidget(self._lbl_dest)

        # Progress bar (ukryty do czasu importu)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMinimum(0)
        layout.addWidget(self._progress)

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #aaa; font-size: 11px;")
        self._lbl_status.setVisible(False)
        layout.addWidget(self._lbl_status)

        # Przyciski
        row_btns = QHBoxLayout()
        row_btns.addStretch()

        self._btn_start = QPushButton(self.tr("Start Import"))
        self._btn_start.setFixedHeight(36)
        self._btn_start.setStyleSheet(
            "background-color: #1565c0; color: white; font-weight: bold;"
        )
        self._btn_start.clicked.connect(self._start_import)
        row_btns.addWidget(self._btn_start)

        self._btn_cancel = QPushButton(self.tr("Cancel"))
        self._btn_cancel.setFixedHeight(36)
        self._btn_cancel.clicked.connect(self.reject)
        row_btns.addWidget(self._btn_cancel)

        layout.addLayout(row_btns)

    # ─────────────────────────── helpers

    def _default_session_name(self) -> str:
        """Generuje nazwę sesji: YYYY-MM-DD_NNN (kolejny wolny numer)."""
        today = date.today().strftime('%Y-%m-%d')
        idx = 1
        while True:
            name = f"{today}_{idx:03d}"
            if not os.path.exists(os.path.join(self._sessions_dir, name)):
                return name
            idx += 1

    def _dest_dir(self) -> str:
        name = self._edit_name.text().strip() or self._default_session_name()
        return os.path.join(self._sessions_dir, name)

    def _refresh_dest_preview(self):
        dest = self._dest_dir()
        self._lbl_dest.setText(f"→ {dest}")

    def _fmt_filter(self) -> str:
        idx = self._combo_fmt.currentIndex()
        return ['all', 'jpeg', 'raw'][idx]

    # ─────────────────────────── Import

    def _start_import(self):
        dest = self._dest_dir()
        if not self._edit_name.text().strip():
            QMessageBox.warning(
                self, self.tr("Import"),
                self.tr("Session name cannot be empty.")
            )
            return

        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setMaximum(len(self._selected))
        self._progress.setValue(0)
        self._lbl_status.setVisible(True)

        self._worker = _CopyWorker(self._selected, dest, self._fmt_filter())
        self._worker.file_copied.connect(self._on_file_copied)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_file_copied(self, current: int, total: int, fname: str):
        self._progress.setValue(current)
        if fname:
            self._lbl_status.setText(
                self.tr(f"Copying {current}/{total}: {fname}")
            )

    def _on_finished(self, dest_dir: str, error: str):
        if error:
            QMessageBox.critical(
                self, self.tr("Import Error"),
                self.tr(f"Import failed:\n{error}")
            )
            self._btn_start.setEnabled(True)
            self._btn_cancel.setEnabled(True)
            return

        self._lbl_status.setText(self.tr("Import complete!"))

        # Zapytaj o usunięcie plików z karty
        if dest_dir:
            reply = QMessageBox.question(
                self,
                self.tr("Delete from Card?"),
                self.tr(
                    "Import finished successfully.\n\n"
                    "Do you want to delete the copied files from the camera card?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._delete_from_card()

            self.import_finished.emit(dest_dir)
        self.accept()

    def _delete_from_card(self):
        """Usuwa skopiowane pliki z karty przez gphoto2."""
        context = gp.Context()
        camera  = None
        errors  = []
        try:
            camera = gp.Camera()
            camera.init(context)
            for folder, fname in self._selected:
                try:
                    camera.file_delete(folder, fname, context)
                except Exception as e:
                    errors.append(f"{fname}: {e}")
        except Exception as e:
            QMessageBox.warning(
                self, self.tr("Delete from Card"),
                self.tr(f"Could not connect to camera:\n{e}")
            )
            return
        finally:
            if camera:
                try:
                    camera.exit(context)
                except Exception:
                    pass

        if errors:
            QMessageBox.warning(
                self, self.tr("Delete from Card"),
                self.tr("Some files could not be deleted:\n") + "\n".join(errors[:5])
            )
