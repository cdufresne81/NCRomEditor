"""
Table Viewer Window

Displays table data in a separate, independent window.
Allows opening multiple tables simultaneously for comparison.
"""

from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

from ..utils.constants import TABLE_VIEWER_DEFAULT_WIDTH, TABLE_VIEWER_DEFAULT_HEIGHT, APP_NAME
from .table_viewer import TableViewer
from ..core.rom_definition import Table, RomDefinition


class TableViewerWindow(QMainWindow):
    """
    Standalone window for viewing a single table

    Features:
    - Independent window that can be moved/resized
    - Shows table name in window title
    - Contains TableViewer widget for displaying data
    - Can have multiple windows open simultaneously
    """

    def __init__(self, table: Table, data: dict, rom_definition: RomDefinition, parent=None):
        """
        Initialize table viewer window

        Args:
            table: Table definition
            data: Table data dictionary from RomReader
            rom_definition: ROM definition containing scalings
            parent: Parent widget (optional)
        """
        super().__init__(parent)

        self.table = table
        self.data = data
        self.rom_definition = rom_definition

        # Set window properties
        self.setWindowTitle(f"{table.name} - {APP_NAME}")
        self.resize(TABLE_VIEWER_DEFAULT_WIDTH, TABLE_VIEWER_DEFAULT_HEIGHT)

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Create table viewer widget
        self.viewer = TableViewer(rom_definition)
        layout.addWidget(self.viewer)

        # Display the table data
        self.viewer.display_table(table, data)

    def closeEvent(self, event):
        """Handle window close event"""
        # Clean up if needed
        event.accept()
