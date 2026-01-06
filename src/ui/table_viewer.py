"""
Table Viewer Widget

Displays table data in a grid view.
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView
)
from PySide6.QtCore import Qt

from ..core.rom_definition import Table, TableType
import numpy as np


class TableViewer(QWidget):
    """Widget for viewing table data"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_table = None
        self.current_data = None
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Table info label
        self.info_label = QLabel("Select a table to view")
        layout.addWidget(self.info_label)

        # Table widget for displaying data
        self.table_widget = QTableWidget()
        self.table_widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(self.table_widget)

    def display_table(self, table: Table, data: dict):
        """
        Display table data

        Args:
            table: Table definition
            data: Dictionary with 'values', 'x_axis', 'y_axis' from RomReader
        """
        self.current_table = table
        self.current_data = data

        # Update info label
        info_text = (
            f"{table.name} | "
            f"Type: {table.type.value} | "
            f"Category: {table.category} | "
            f"Address: 0x{table.address}"
        )
        self.info_label.setText(info_text)

        values = data['values']

        if table.type == TableType.ONE_D:
            self._display_1d(values)
        elif table.type == TableType.TWO_D:
            self._display_2d(values, data.get('y_axis'))
        elif table.type == TableType.THREE_D:
            self._display_3d(values, data.get('x_axis'), data.get('y_axis'))

    def _display_1d(self, values: np.ndarray):
        """Display 1D table (single value)"""
        self.table_widget.setRowCount(1)
        self.table_widget.setColumnCount(1)
        self.table_widget.setHorizontalHeaderLabels(["Value"])
        self.table_widget.setVerticalHeaderLabels([""])

        item = QTableWidgetItem(f"{values[0]:.4f}")
        self.table_widget.setItem(0, 0, item)

    def _display_2d(self, values: np.ndarray, y_axis: np.ndarray):
        """Display 2D table (1D array with Y axis)"""
        num_values = len(values)
        self.table_widget.setRowCount(num_values)
        self.table_widget.setColumnCount(2)
        self.table_widget.setHorizontalHeaderLabels(["Y Axis", "Value"])

        for i in range(num_values):
            # Y axis value
            if y_axis is not None and i < len(y_axis):
                y_item = QTableWidgetItem(f"{y_axis[i]:.4f}")
            else:
                y_item = QTableWidgetItem(str(i))
            self.table_widget.setItem(i, 0, y_item)

            # Data value
            value_item = QTableWidgetItem(f"{values[i]:.4f}")
            self.table_widget.setItem(i, 1, value_item)

    def _display_3d(self, values: np.ndarray, x_axis: np.ndarray, y_axis: np.ndarray):
        """Display 3D table (2D grid with X and Y axes)"""
        if values.ndim != 2:
            self._display_1d(values.flatten())
            return

        rows, cols = values.shape

        # Set up table dimensions (+1 for axis column)
        self.table_widget.setRowCount(rows)
        self.table_widget.setColumnCount(cols + 1)

        # Set column headers (X axis values)
        headers = ["Y \\ X"]  # Top-left cell label
        if x_axis is not None and len(x_axis) == cols:
            headers.extend([f"{x:.2f}" for x in x_axis])
        else:
            headers.extend([str(i) for i in range(cols)])
        self.table_widget.setHorizontalHeaderLabels(headers)

        # Fill table
        for row in range(rows):
            # Y axis value in first column
            if y_axis is not None and row < len(y_axis):
                y_item = QTableWidgetItem(f"{y_axis[row]:.2f}")
            else:
                y_item = QTableWidgetItem(str(row))
            y_item.setFlags(y_item.flags() & ~Qt.ItemIsEditable)  # Make read-only
            self.table_widget.setItem(row, 0, y_item)

            # Data values
            for col in range(cols):
                value_item = QTableWidgetItem(f"{values[row, col]:.4f}")
                self.table_widget.setItem(row, col + 1, value_item)

    def clear(self):
        """Clear the viewer"""
        self.current_table = None
        self.current_data = None
        self.info_label.setText("Select a table to view")
        self.table_widget.setRowCount(0)
        self.table_widget.setColumnCount(0)
