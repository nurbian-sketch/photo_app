from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QSpacerItem, QSizePolicy
)
from PyQt6.QtGui import QFont, QPixmap, QImageReader
from PyQt6.QtCore import Qt

class SessionView(QWidget):
    def __init__(self):
        super().__init__()
        self.current_image_path = "assets/pictures/test.jpg"
        self.setup_ui()

    def setup_ui(self):
        # === Obraz po lewej ===
        self.image_label = QLabel(self.tr("No image"))
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.image_label.setStyleSheet("background-color: #3d3d3d; color: white;")
        self.image_label.setMinimumSize(400, 300)

        # === Przyciski po prawej ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(10)

        # Font dla przycisków
        btn_font = QFont()
        btn_font.setPointSize(int(btn_font.pointSize() * 1.3))

        # Label informacyjny
        self.info_label = QLabel(self.tr("Session View"))
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setFont(btn_font)
        right_layout.addWidget(self.info_label)

        # Przyciski
        btn_size = (200, 50)
        
        self.btn_action1 = QPushButton(self.tr("Action 1"))
        self.btn_action1.setFixedSize(*btn_size)
        self.btn_action1.setFont(btn_font)
        right_layout.addWidget(self.btn_action1, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_action2 = QPushButton(self.tr("Action 2"))
        self.btn_action2.setFixedSize(*btn_size)
        self.btn_action2.setFont(btn_font)
        right_layout.addWidget(self.btn_action2, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_action3 = QPushButton(self.tr("Action 3"))
        self.btn_action3.setFixedSize(*btn_size)
        self.btn_action3.setFont(btn_font)
        right_layout.addWidget(self.btn_action3, alignment=Qt.AlignmentFlag.AlignCenter)

        # Spacer
        right_layout.addItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # === Layout główny ===
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.addWidget(self.image_label, stretch=2)
        main_layout.addWidget(right_panel, stretch=1)

        # Załaduj obraz
        self.load_image()

    def load_image(self):
        """Ładuje testowy obraz z EXIF auto-rotation"""
        if not self.current_image_path:
            return
            
        try:
            reader = QImageReader(self.current_image_path)
            reader.setAutoTransform(True)
            image = reader.read()
            
            if not image.isNull():
                pixmap = QPixmap.fromImage(image)
                scaled = pixmap.scaled(
                    self.image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.image_label.setPixmap(scaled)
        except Exception as e:
            self.image_label.setText(self.tr("Error: {0}").format(e))

    def resizeEvent(self, event):
        """Przeskaluj obraz przy zmianie rozmiaru okna"""
        self.load_image()
        super().resizeEvent(event)

    def retranslateUi(self):
        """Odświeżenie tekstów po zmianie języka"""
        self.info_label.setText(self.tr("Session View"))
        self.btn_action1.setText(self.tr("Action 1"))
        self.btn_action2.setText(self.tr("Action 2"))
        self.btn_action3.setText(self.tr("Action 3"))
        if not self.image_label.pixmap():
            self.image_label.setText(self.tr("No image"))