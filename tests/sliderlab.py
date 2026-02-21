#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from enum import Enum

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QSlider,
    QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QSpinBox, QColorDialog,
    QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QStyle, QStyleOptionSlider


# ───────────────────────────────────────── CONFIG

class LabelPositionMode(Enum):
    HANDLE_CENTER = "handle_center"
    EVEN_SPACING = "even_spacing"


# ───────────────────────────────────────── SLIDER

class SliderWithScale(QWidget):
    valueChanged = pyqtSignal(str)

    def __init__(self, values):
        super().__init__()

        self.values = [str(v) for v in values]
        self.labels = []

        # feature toggles
        self.safe_indices = True
        self.dynamic_updates = True
        self.label_mode = LabelPositionMode.HANDLE_CENTER

        # style params
        self.colors = {
            "groove": "#555",
            "handle": "#aaa",
            "hover": "#ccc",
            "pressed": "#5ca0d3",
            "inactive": "#444",
        }

        self.handle_width = 18
        self.handle_height = 22
        self.handle_radius = 4

        self._build_ui()
        self._apply_style()
        self._update_labels()

    # ───────────────── UI

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.scale = QWidget()
        self.scale.setFixedHeight(22)
        layout.addWidget(self.scale)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(self.values) - 1)
        layout.addWidget(self.slider)

        self.value_lbl = QLabel(self.values[0])
        self.value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_lbl)

        self.slider.valueChanged.connect(self._on_change)

    # ───────────────── CORE

    def _on_change(self, idx):
        self.value_lbl.setText(self.values[idx])
        self._update_labels()

    def _slider_x(self, idx):
        opt = QStyleOptionSlider()
        self.slider.initStyleOption(opt)
        opt.sliderPosition = idx

        style = self.slider.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self.slider
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self.slider
        )

        min_x = groove.left()
        max_x = groove.right() - handle.width()
        ratio = idx / max(1, self.slider.maximum())
        return int(min_x + ratio * (max_x - min_x) + handle.width() / 2)

    def _update_labels(self):
        for l in self.labels:
            l.deleteLater()
        self.labels.clear()

        w = self.scale.width()
        n = len(self.values)
        if n < 2 or w <= 0:
            return

        count = max(2, w // 60)
        count = min(count, n)

        step = (n - 1) / (count - 1)
        indices = [round(i * step) for i in range(count)]

        if self.safe_indices:
            indices = sorted(set(indices))

        for i, idx in enumerate(indices):
            lbl = QLabel(self.values[idx], self.scale)
            lbl.adjustSize()

            if self.label_mode == LabelPositionMode.HANDLE_CENTER:
                x = self._slider_x(idx) - lbl.width() // 2
            else:
                x = int(i * (w / (len(indices) - 1))) - lbl.width() // 2

            lbl.move(max(2, min(x, w - lbl.width() - 2)), 0)
            lbl.show()
            self.labels.append(lbl)

    # ───────────────── STYLE

    def _apply_style(self):
        self.slider.setStyleSheet(f"""
        QSlider::groove:horizontal {{
            background: {self.colors['groove']};
            height: 4px;
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: {self.colors['handle']};
            width: {self.handle_width}px;
            height: {self.handle_height}px;
            margin: -9px 0;
            border-radius: {self.handle_radius}px;
        }}
        QSlider::handle:hover {{
            background: {self.colors['hover']};
        }}
        QSlider::handle:pressed {{
            background: {self.colors['pressed']};
        }}
        """)

    def resizeEvent(self, e):
        if self.dynamic_updates:
            self._update_labels()
        super().resizeEvent(e)

    def event(self, e):
        if self.dynamic_updates and e.type() in (
            e.Type.StyleChange, e.Type.FontChange
        ):
            self._update_labels()
        return super().event(e)


# ───────────────────────────────────────── CONTROL PANEL

class SliderLab(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Slider LAB")

        layout = QHBoxLayout(self)

        self.slider = SliderWithScale(
            ["100", "200", "400", "800", "1600", "3200"]
        )
        layout.addWidget(self.slider, 2)

        panel = QVBoxLayout()
        layout.addLayout(panel, 1)

        # toggles
        chk_safe = QCheckBox("Safe indices")
        chk_safe.setChecked(True)
        chk_safe.toggled.connect(lambda v: setattr(self.slider, "safe_indices", v))
        panel.addWidget(chk_safe)

        chk_dyn = QCheckBox("Dynamic updates")
        chk_dyn.setChecked(True)
        chk_dyn.toggled.connect(lambda v: setattr(self.slider, "dynamic_updates", v))
        panel.addWidget(chk_dyn)

        mode = QComboBox()
        mode.addItems([m.value for m in LabelPositionMode])
        mode.currentTextChanged.connect(
            lambda v: setattr(self.slider, "label_mode", LabelPositionMode(v))
        )
        panel.addWidget(QLabel("Label positioning"))
        panel.addWidget(mode)

        # size
        for name, attr in [("Handle width", "handle_width"),
                           ("Handle height", "handle_height"),
                           ("Handle radius", "handle_radius")]:
            box = QSpinBox()
            box.setRange(4, 60)
            box.setValue(getattr(self.slider, attr))
            box.valueChanged.connect(
                lambda v, a=attr: (setattr(self.slider, a, v), self.slider._apply_style())
            )
            panel.addWidget(QLabel(name))
            panel.addWidget(box)

        # colors
        for key in self.slider.colors:
            btn = QPushButton(f"Color: {key}")
            btn.clicked.connect(lambda _, k=key: self.pick_color(k))
            panel.addWidget(btn)

        panel.addStretch()

        ok = QPushButton("OK – print config")
        ok.clicked.connect(self.print_config)
        panel.addWidget(ok)

    def pick_color(self, key):
        c = QColorDialog.getColor()
        if c.isValid():
            self.slider.colors[key] = c.name()
            self.slider._apply_style()

    def print_config(self):
        print("CONFIG = {")
        print("  colors =", self.slider.colors)
        print("  handle_width =", self.slider.handle_width)
        print("  handle_height =", self.slider.handle_height)
        print("  handle_radius =", self.slider.handle_radius)
        print("  safe_indices =", self.slider.safe_indices)
        print("  dynamic_updates =", self.slider.dynamic_updates)
        print("  label_mode =", self.slider.label_mode.value)
        print("}")


# ───────────────────────────────────────── RUN

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = SliderLab()
    w.resize(900, 300)
    w.show()
    sys.exit(app.exec())
