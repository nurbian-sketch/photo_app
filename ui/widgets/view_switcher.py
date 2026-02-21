from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import pyqtSignal, Qt

class ViewSwitcher(QWidget):
    view_changed = pyqtSignal(str)

    def __init__(self, views, parent=None):
        super().__init__(parent)
        self.views = views
        self.labels = {}
        self.current_view = None

        layout = QHBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(5, 5, 5, 5)

        layout.addStretch()  # Spacer na początku - przesuwa wszystko w prawo

        for i, name in enumerate(views):
            label = QLabel(name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(self.label_style(False, False))
            label.mousePressEvent = lambda event, n=name: self.select_view(n)
            label.enterEvent = lambda event, n=name: self.on_hover(n, True)
            label.leaveEvent = lambda event, n=name: self.on_hover(n, False)
            layout.addWidget(label)
            self.labels[name] = label

            if i < len(views) - 1:
                sep = QLabel("|")
                sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sep.setStyleSheet("color: #AAAAAA; font-size: 16pt;")
                layout.addWidget(sep)

        self.select_view(views[0])

    def select_view(self, name):
        if name == self.current_view:
            return
        self.current_view = name
        for n, label in self.labels.items():
            if n == name:
                label.setStyleSheet(self.label_style(True, False))
            else:
                label.setStyleSheet(self.label_style(False, False))
        self.view_changed.emit(name)

    def on_hover(self, name, is_hovering):
        """Podświetlenie przy najechaniu kursorem"""
        if name != self.current_view:
            label = self.labels[name]
            label.setStyleSheet(self.label_style(False, is_hovering))

    def label_style(self, active, hovering):
        if active:
            color = "#FFFFFF"
        elif hovering:
            color = "#CCCCCC"  # Jaśniejszy przy hover
        else:
            color = "#888888"
        
        return f"""
            QLabel {{
                font-size: 16pt;
                color: {color};
                background-color: transparent;
            }}
        """