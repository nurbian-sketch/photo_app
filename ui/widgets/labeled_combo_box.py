#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Labeled ComboBox Widget
Universal component for displaying combobox with label.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QSizePolicy
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon


class LabeledComboBox(QWidget):
    """
    ComboBox with label above.
    
    Provides a clean, consistent way to display labeled dropdown selectors.
    
    Signals:
        currentTextChanged(str): Emitted when selection changes
    """
    
    currentTextChanged = pyqtSignal(str)
    
    def __init__(self, label: str, items: list, parent=None):
        """
        Initialize labeled combobox.
        
        Args:
            label: Text to display above combobox
            items: List of items for dropdown
            parent: Parent widget
        """
        super().__init__(parent)
        self._setup_ui(label, items)
        self._connect_signals()
    
    def _setup_ui(self, label: str, items: list):
        """Build the widget UI"""
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Sprężyna na górze
        layout.addStretch(1)

        # Label
        self.label = QLabel(label)
        self.label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.label)
        
        # ComboBox - zachowuje standardowy rozmiar (brak Policy.Expanding dla kontrolki)
        self.combo = QComboBox()
        self.combo.setIconSize(self.combo.iconSize().__class__(24, 24))
        self.combo.addItems([str(item) for item in items])
        layout.addWidget(self.combo)

        # Sprężyna na dole
        layout.addStretch(1)
    
    def _connect_signals(self):
        """Connect internal signals"""
        self.combo.currentTextChanged.connect(self.currentTextChanged.emit)
    
    def currentText(self) -> str:
        """
        Get currently selected text.
        
        Returns:
            Selected item text
        """
        return self.combo.currentText()
    
    def setCurrentText(self, text: str):
        """
        Set selected item by text.
        
        Args:
            text: Text of item to select
        """
        index = self.combo.findText(str(text))
        if index >= 0:
            self.combo.setCurrentIndex(index)
    
    def setEnabled(self, enabled: bool):
        """
        Enable/disable the entire widget.
        
        Args:
            enabled: True to enable, False to disable
        """
        super().setEnabled(enabled)
        self.combo.setEnabled(enabled)
        self.label.setEnabled(enabled)
    
    def setToolTip(self, tooltip: str):
        """
        Set tooltip for the combobox.
        
        Args:
            tooltip: Tooltip text
        """
        self.combo.setToolTip(tooltip)
    
    def addItem(self, item: str):
        """
        Add item to combobox.
        
        Args:
            item: Item to add
        """
        self.combo.addItem(str(item))
    
    def addItems(self, items: list):
        """
        Add multiple items to combobox.
        
        Args:
            items: List of items to add
        """
        self.combo.addItems([str(item) for item in items])
    
    def clear(self):
        """Clear all items from combobox"""
        self.combo.clear()
    
    def update_items(self, items: list):
        """
        Replace all items, preserving selection if possible.

        Args:
            items: New list of items
        """
        current = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems([str(item) for item in items])
        idx = self.combo.findText(current)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)

    def set_item_icons(self, icons: dict):
        """
        Set icons for combo items by text label.

        Args:
            icons: dict mapping item text → QIcon or file path (str)

        Example:
            wb_combo.set_item_icons({
                'Auto':     QIcon('assets/icons/wb/wb_awb.png'),
                'Daylight': 'assets/icons/wb/wb_daylight.png',
            })
        """
        for i in range(self.combo.count()):
            text = self.combo.itemText(i)
            icon = icons.get(text)
            if icon is None:
                continue
            if isinstance(icon, str):
                icon = QIcon(icon)
            self.combo.setItemIcon(i, icon)

    def count(self) -> int:
        """
        Get number of items.
        
        Returns:
            Number of items in combobox
        """
        return self.combo.count()