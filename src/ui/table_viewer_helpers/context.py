"""
TableViewer Context

Shared state object for TableViewer helper classes.
Provides access to common state and the parent viewer's signals.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Dict, Any

from PySide6.QtWidgets import QTableWidget

if TYPE_CHECKING:
    from ..table_viewer import TableViewer
    from ...core.rom_definition import Table, RomDefinition


@dataclass
class TableViewerContext:
    """
    Shared context for TableViewer helper classes.

    Provides access to:
    - The parent TableViewer widget (for signal emission)
    - The QTableWidget for UI operations
    - ROM definition and current table/data state
    - Editing flags
    """
    viewer: 'TableViewer'
    table_widget: QTableWidget
    rom_definition: Optional['RomDefinition'] = None
    current_table: Optional['Table'] = None
    current_data: Optional[Dict[str, Any]] = None

    @property
    def editing_in_progress(self) -> bool:
        """Check if editing is in progress (suppresses signals)"""
        return self.viewer._editing_in_progress

    @editing_in_progress.setter
    def editing_in_progress(self, value: bool):
        """Set editing in progress flag"""
        self.viewer._editing_in_progress = value

    @property
    def read_only(self) -> bool:
        """Check if viewer is in read-only mode"""
        return self.viewer._read_only

    @property
    def info_label(self):
        """Access the info label widget"""
        return self.viewer.info_label
