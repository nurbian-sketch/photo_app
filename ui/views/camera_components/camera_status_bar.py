"""
Camera Status Bar Component.

Contains:
- Status label (Ready/Changes)
- Reset button
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import pyqtSignal


class CameraStatusBar(QWidget):
    """Status bar with changes display and reset button"""
    
    reset_clicked = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Status label
        self.status_label = QLabel(self.tr("🟢 Ready"))
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #E8F5E9;
                color: #2E7D32;
                padding: 10px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.status_label, stretch=1)
        
        # Reset button
        self.reset_btn = QPushButton(self.tr("Reset"))
        self.reset_btn.setMinimumHeight(40)
        self.reset_btn.setEnabled(False)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
            QPushButton:focus {
                border: 1px solid rgba(180, 180, 180, 0.9); border-radius: 3px; background-color: #FF9800;
            }
            QPushButton:focus:hover {
                background-color: #F57C00;
            }
        """)
        layout.addWidget(self.reset_btn)
        
        self.reset_btn.clicked.connect(self.reset_clicked.emit)
    
    def update_status(self, cache):
        """Update status display based on cache state"""
        if cache.has_changes():
            changes = cache.get_bulk_update_dict()
            
            # Show first 3 changes
            changes_list = list(changes.items())[:3]
            changes_str = ", ".join([f"{k}→{v}" for k, v in changes_list])
            
            if len(changes) > 3:
                changes_str += f" (+{len(changes)-3} more)"
            
            self.status_label.setText(self.tr("🔴 Changes: %1").replace("%1", changes_str))
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #FFEBEE;
                    color: #9e3535;
                    padding: 10px;
                    border-radius: 4px;
                    font-weight: bold;
                }
            """)
            self.reset_btn.setEnabled(True)
        else:
            self.status_label.setText(self.tr("🟢 Ready"))
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #E8F5E9;
                    color: #2E7D32;
                    padding: 10px;
                    border-radius: 4px;
                    font-weight: bold;
                }
            """)
            self.reset_btn.setEnabled(False)
