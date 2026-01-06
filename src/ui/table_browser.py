"""
Table Browser Widget

Shows a tree view of all available tables organized by category.
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QLabel
)
from PySide6.QtCore import Signal

from ..core.rom_definition import RomDefinition, Table


class TableBrowser(QWidget):
    """Widget for browsing tables by category"""

    # Signal emitted when a table is selected
    table_selected = Signal(Table)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.definition = None
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Label
        label = QLabel("Tables")
        layout.addWidget(label)

        # Tree widget for categories and tables
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Type", "Address"])
        self.tree.setColumnWidth(0, 400)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree)

    def load_definition(self, definition: RomDefinition):
        """
        Load ROM definition and populate tree

        Args:
            definition: ROM definition with tables
        """
        self.definition = definition
        self.tree.clear()

        # Get tables grouped by category
        categories = definition.get_tables_by_category()

        # Sort categories alphabetically
        for category in sorted(categories.keys()):
            tables = categories[category]

            # Create category item
            category_item = QTreeWidgetItem([category, "", ""])
            category_item.setData(0, 100, None)  # Store None for category items
            self.tree.addTopLevelItem(category_item)

            # Sort tables by name within category
            for table in sorted(tables, key=lambda t: t.name):
                # Create table item
                table_item = QTreeWidgetItem([
                    table.name,
                    table.type.value,
                    f"0x{table.address}"
                ])
                # Store table object
                table_item.setData(0, 100, table)
                category_item.addChild(table_item)

            # Collapse categories initially
            category_item.setExpanded(False)

    def _on_item_clicked(self, item, column):
        """Handle item click in tree"""
        # Get table object stored in item
        table = item.data(0, 100)
        if table is not None:  # Not a category
            self.table_selected.emit(table)
