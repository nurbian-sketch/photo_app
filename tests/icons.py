import os
import sys
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtGui import QPixmap, QImage, QPainter
from PyQt6.QtCore import Qt

class IconTester(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Icon De-saturation Tester")
        self.setStyleSheet("background-color: #1e1e1e; color: #eee;")
        
        layout = QVBoxLayout(self)
        path = os.path.expanduser("~/Projekty/photo_app/assets/icons")
        
        sizes = [20, 24, 32, 48]

        if not os.path.exists(path):
            layout.addWidget(QLabel(f"Folder nie istnieje: {path}"))
            return

        for s in sizes:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"<b>{s}px:</b>"))
            
            for file in sorted(os.listdir(path)):
                if file.lower().endswith(('.png', '.svg')):
                    full_path = os.path.join(path, file)
                    
                    # 1. Oryginał (Active)
                    pix_active = QPixmap(full_path).scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    lbl_on = QLabel()
                    lbl_on.setPixmap(pix_active)
                    row.addWidget(lbl_on)
                    
                    # 2. Wyszarzona (Inactive) - generowana w locie
                    pix_inactive = self.make_gray(pix_active)
                    lbl_off = QLabel()
                    lbl_off.setPixmap(pix_inactive)
                    row.addWidget(lbl_off)
                    
            row.addStretch()
            layout.addLayout(row)

    def make_gray(self, pixmap):
        """Konwertuje pixmapę na szarą i półprzezroczystą"""
        # Konwersja na odcienie szarości
        img = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
        gray_pix = QPixmap.fromImage(img)
        
        # Dodanie przezroczystości (opacity)
        out_pix = QPixmap(gray_pix.size())
        out_pix.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(out_pix)
        painter.setOpacity(0.3)  # 30% widoczności dla stanu nieaktywnego
        painter.drawPixmap(0, 0, gray_pix)
        painter.end()
        
        return out_pix

if __name__ == "__main__":
    app = QApplication(sys.argv)
    t = IconTester()
    t.show()
    sys.exit(app.exec())