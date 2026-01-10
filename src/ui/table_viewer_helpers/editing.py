"""
Table Edit Helper

Handles cell editing, validation, and value conversion for TableViewer.
"""

import logging
from typing import TYPE_CHECKING, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush

from ...core.rom_definition import TableType
from .context import TableViewerContext

if TYPE_CHECKING:
    from .display import TableDisplayHelper

logger = logging.getLogger(__name__)


class TableEditHelper:
    """Helper class for cell editing operations"""

    def __init__(self, ctx: TableViewerContext, display: 'TableDisplayHelper'):
        self.ctx = ctx
        self.display = display

    def on_cell_changed(self, row: int, col: int):
        """Handle cell value change from user edit"""
        if self.ctx.editing_in_progress or self.ctx.read_only:
            return

        if not self.ctx.current_table or not self.ctx.current_data:
            return

        item = self.ctx.table_widget.item(row, col)
        if not item:
            return

        # Get the actual data indices from the item
        data_indices = item.data(Qt.UserRole)
        if data_indices is None:
            # This is an axis cell, not a data cell
            return

        data_row, data_col = data_indices

        # Get the new text value
        new_text = item.text().strip()

        # Try to parse the new value
        try:
            new_value = float(new_text)
        except ValueError:
            # Invalid input - revert to old value
            self._revert_cell(row, col, data_row, data_col)
            return

        # Get the old value from current_data
        values = self.ctx.current_data['values']
        if values.ndim == 1:
            old_value = float(values[data_row])
        else:
            old_value = float(values[data_row, data_col])

        # Skip if no change
        if abs(new_value - old_value) < 1e-10:
            return

        # Validate against scaling min/max if available
        if self.ctx.rom_definition and self.ctx.current_table.scaling:
            scaling = self.ctx.rom_definition.get_scaling(self.ctx.current_table.scaling)
            if scaling:
                # Check min/max bounds
                if scaling.min is not None and new_value < scaling.min:
                    logger.warning(f"Value {new_value} below minimum {scaling.min}")
                    self._revert_cell(row, col, data_row, data_col)
                    return
                if scaling.max is not None and new_value > scaling.max:
                    logger.warning(f"Value {new_value} above maximum {scaling.max}")
                    self._revert_cell(row, col, data_row, data_col)
                    return

        # Convert display values to raw values
        old_raw = self.display_to_raw(old_value)
        new_raw = self.display_to_raw(new_value)

        if old_raw is None or new_raw is None:
            self._revert_cell(row, col, data_row, data_col)
            return

        # Update the internal data
        if values.ndim == 1:
            self.ctx.current_data['values'][data_row] = new_value
        else:
            self.ctx.current_data['values'][data_row, data_col] = new_value

        # Update cell display with proper formatting
        self.ctx.editing_in_progress = True
        try:
            value_fmt = self.display.get_value_format()
            item.setText(self.display.format_value(new_value, value_fmt))

            # Update cell color based on new value
            color = self.display.get_cell_color(new_value, self.ctx.current_data['values'], data_row, data_col)
            item.setBackground(QBrush(color))
        finally:
            self.ctx.editing_in_progress = False

        # Emit the change signal
        self.ctx.viewer.cell_changed.emit(
            self.ctx.current_table.name,
            data_row, data_col,
            old_value, new_value,
            old_raw, new_raw
        )

        logger.debug(f"Cell changed: {self.ctx.current_table.name}[{data_row},{data_col}] {old_value} -> {new_value}")

    def _revert_cell(self, row: int, col: int, data_row: int, data_col: int):
        """Revert cell to its original value"""
        values = self.ctx.current_data['values']
        if values.ndim == 1:
            old_value = values[data_row]
        else:
            old_value = values[data_row, data_col]

        self.ctx.editing_in_progress = True
        try:
            value_fmt = self.display.get_value_format()
            item = self.ctx.table_widget.item(row, col)
            if item:
                item.setText(self.display.format_value(old_value, value_fmt))
        finally:
            self.ctx.editing_in_progress = False

    def display_to_raw(self, display_value: float) -> Optional[float]:
        """Convert display value to raw binary value using scaling"""
        if not self.ctx.rom_definition or not self.ctx.current_table:
            return display_value

        scaling = self.ctx.rom_definition.get_scaling(self.ctx.current_table.scaling)
        if not scaling:
            return display_value

        try:
            from simpleeval import simple_eval
            return simple_eval(scaling.frexpr, names={'x': display_value})
        except Exception as e:
            logger.error(f"Error converting to raw: {e}")
            return None

    def update_cell_value(self, data_row: int, data_col: int, new_value: float):
        """
        Update a cell's value programmatically (for undo/redo)

        Args:
            data_row: Data row index
            data_col: Data column index
            new_value: New display value
        """
        if not self.ctx.current_table or not self.ctx.current_data:
            return

        # Update internal data
        values = self.ctx.current_data['values']
        if values.ndim == 1:
            values[data_row] = new_value
        else:
            values[data_row, data_col] = new_value

        # Find the UI cell that corresponds to this data cell
        ui_row, ui_col = self.data_to_ui_coords(data_row, data_col)
        if ui_row is None:
            return

        # Update UI
        self.ctx.editing_in_progress = True
        try:
            item = self.ctx.table_widget.item(ui_row, ui_col)
            if item:
                value_fmt = self.display.get_value_format()
                item.setText(self.display.format_value(new_value, value_fmt))
                color = self.display.get_cell_color(new_value, values, data_row, data_col)
                item.setBackground(QBrush(color))
        finally:
            self.ctx.editing_in_progress = False

    def data_to_ui_coords(self, data_row: int, data_col: int) -> Tuple[Optional[int], Optional[int]]:
        """Convert data coordinates to UI table coordinates"""
        if not self.ctx.current_table:
            return None, None

        table_type = self.ctx.current_table.type
        flipx = self.ctx.current_table.flipx if self.ctx.current_table else False
        flipy = self.ctx.current_table.flipy if self.ctx.current_table else False

        if table_type == TableType.ONE_D:
            return 0, 0
        elif table_type == TableType.TWO_D:
            values = self.ctx.current_data['values']
            num_values = len(values)
            ui_row = (num_values - 1 - data_row) if flipy else data_row
            return ui_row, 1  # Column 1 is the value column
        elif table_type == TableType.THREE_D:
            values = self.ctx.current_data['values']
            rows, cols = values.shape
            ui_row = (rows - 1 - data_row) if flipy else data_row
            ui_col = (cols - 1 - data_col) if flipx else data_col
            return ui_row + 1, ui_col + 1  # +1 for axis row/col

        return None, None
