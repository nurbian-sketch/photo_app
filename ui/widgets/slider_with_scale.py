#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PyQt6.QtWidgets import (
    QWidget, QLabel, QSlider,
    QVBoxLayout, QHBoxLayout,
    QStyle, QStyleOptionSlider, QSizePolicy,
    QProxyStyle
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QEvent
from PyQt6.QtGui import QPalette, QColor


class BigHandleStyle(QProxyStyle):
    """Fusion z powiększonym handle'em suwaka."""

    HANDLE_W = 14
    HANDLE_H = 22

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_SliderLength:
            return self.HANDLE_W
        if metric == QStyle.PixelMetric.PM_SliderThickness:
            return self.HANDLE_H
        return super().pixelMetric(metric, option, widget)

    def subControlRect(self, cc, opt, sc, widget=None):
        rect = super().subControlRect(cc, opt, sc, widget)
        if cc == QStyle.ComplexControl.CC_Slider:
            if sc == QStyle.SubControl.SC_SliderHandle:
                center = rect.center()
                rect = QRect(0, 0, self.HANDLE_W, self.HANDLE_H)
                rect.moveCenter(center)
        return rect


# Singleton — jeden styl dla wszystkich suwaków
_big_handle_style = None

def _get_style():
    global _big_handle_style
    if _big_handle_style is None:
        _big_handle_style = BigHandleStyle("Fusion")
    return _big_handle_style


class SliderWithScale(QWidget):
    valueChanged = pyqtSignal(str)

    TITLE_STYLE = "font-weight: 600;"
    TITLE_STYLE_LOCKED = "font-weight: 600; color: #555;"
    SCALE_COLOR = "color: #999; font-size: 11px;"
    SCALE_COLOR_LOCKED = "color: #555; font-size: 11px;"
    VALUE_STYLE = "font-size: 14px; font-weight: 600;"
    VALUE_STYLE_LOCKED = "font-size: 14px; font-weight: 600; color: #555;"

    def __init__(self, title: str, values: list, parent=None):
        super().__init__(parent)

        self.values = [str(v) for v in values]
        self.current_index = 0
        self.labels: list[QLabel] = []
        self._locked = False

        self._build_ui(title)
        self._connect()
        self._update_labels()

    # ───────────────────────────────────────── UI

    def _build_ui(self, title: str):
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        layout.addStretch(1)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.title_label)

        self.scale_widget = QWidget()
        self.scale_widget.setFixedHeight(22)
        layout.addWidget(self.scale_widget)

        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(self.values) - 1)
        self.slider.setStyle(_get_style())
        self.slider.setMinimumHeight(BigHandleStyle.HANDLE_H + 4)

        # Paleta — zmiana koloru Highlight (pressed) z niebieskiego na neutralny
        pal = self.slider.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#555555"))
        self.slider.setPalette(pal)

        slider_row.addWidget(self.slider)
        layout.addLayout(slider_row)

        self.value_label = QLabel(self.values[0])
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet(self.VALUE_STYLE)
        layout.addWidget(self.value_label)

        layout.addStretch(1)

    # ───────────────────────────────────────── CORE

    def _slider_handle_x(self, index: int) -> int:
        opt = QStyleOptionSlider()
        self.slider.initStyleOption(opt)

        style = self.slider.style()

        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderGroove,
            self.slider
        )

        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderHandle,
            self.slider
        )

        min_x = groove.left()
        max_x = groove.right() - handle.width() + 1

        ratio = index / max(1, self.slider.maximum())
        return int(min_x + ratio * (max_x - min_x) + handle.width() / 2)

    def _update_labels(self):
        for lbl in self.labels:
            lbl.deleteLater()
        self.labels.clear()

        w = self.scale_widget.width()
        n = len(self.values)
        if n < 2 or w <= 0:
            return

        num_to_draw = max(2, w // 50)
        if num_to_draw % 2 == 0:
            num_to_draw -= 1

        num_to_draw = min(num_to_draw, n)

        if num_to_draw > 1:
            step = (n - 1) / (num_to_draw - 1)
            indices = [round(i * step) for i in range(num_to_draw)]
        else:
            indices = [0]

        disabled = not self.isEnabled() or self._locked
        color = self.SCALE_COLOR_LOCKED if disabled else self.SCALE_COLOR
        for idx in indices:
            if idx >= len(self.values): continue
            lbl = QLabel(self.values[int(idx)], self.scale_widget)
            lbl.setStyleSheet(color)
            lbl.adjustSize()

            x = self._slider_handle_x(int(idx)) - lbl.width() // 2
            x = max(2, min(x, self.scale_widget.width() - lbl.width() - 2))

            lbl.move(x, 0)
            lbl.show()
            self.labels.append(lbl)

    # ───────────────────────────────────────── EVENTS

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_labels()

    def changeEvent(self, event):
        """Aktualizuje kolory etykiet przy zmianie stanu enabled/disabled."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self._locked:
            self._apply_label_colors()

    def _apply_label_colors(self):
        """Ustawia kolory etykiet wg aktualnego stanu."""
        disabled = not self.isEnabled() or self._locked
        scale_color = self.SCALE_COLOR_LOCKED if disabled else self.SCALE_COLOR
        value_style = self.VALUE_STYLE_LOCKED if disabled else self.VALUE_STYLE
        title_style = self.TITLE_STYLE_LOCKED if disabled else self.TITLE_STYLE
        for lbl in self.labels:
            lbl.setStyleSheet(scale_color)
        self.value_label.setStyleSheet(value_style)
        self.title_label.setStyleSheet(title_style)

    def _connect(self):
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, idx: int):
        self.current_index = idx
        value = self.values[idx]
        self.value_label.setText(value)
        self.valueChanged.emit(value)

    # ───────────────────────────────────────── API

    def set_value(self, value: str):
        if value in self.values:
            idx = self.values.index(value)
            self.current_index = idx
            self.slider.blockSignals(True)
            self.slider.setValue(idx)
            self.slider.blockSignals(False)
            self.value_label.setText(value)

    def get_value(self) -> str:
        if not self.values or self.current_index >= len(self.values):
            return ""
        return self.values[self.current_index]

    def setLocked(self, locked: bool):
        """Blokuje/odblokowuje suwak wizualnie i funkcjonalnie."""
        self._locked = locked
        self.slider.setEnabled(not locked)
        self._apply_label_colors()

    def update_values(self, new_values: list):
        self.values = [str(v) for v in new_values]
        self.current_index = min(self.current_index, max(0, len(self.values) - 1))
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, len(self.values) - 1))
        self.slider.setValue(self.current_index)
        self.slider.blockSignals(False)
        self.value_label.setText(self.values[self.current_index] if self.values else "")
        self._update_labels()
