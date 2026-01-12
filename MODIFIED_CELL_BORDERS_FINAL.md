# Modified Cell Borders - Final Implementation

## Overview

Added ECUFlash-style thin gray borders around modified cells. Borders persist when closing and reopening tables during the session.

## Features

✅ **Thin gray border** (2px, RGB: 100, 100, 100) around modified cells
✅ **Persists** when closing and reopening tables during session
✅ **Works for data cells** in 1D, 2D, and 3D tables
✅ **Works for axis cells** (X-axis and Y-axis)
✅ **Tracks bulk operations** (interpolation, multiply, etc.)
✅ **Doesn't break undo** - undo works correctly, border remains after undo
✅ **All 92 tests pass**

## Implementation Design

### Architecture

**Separation of Concerns:**
- **Delegate** (`ModifiedCellDelegate`): Handles rendering borders
- **Viewer** (`TableViewer`): Tracks which cells are modified
- **Signals**: Connect editing to tracking (no modification of editing logic)

### Key Principle

**Track by table name + data coordinates**, not UI coordinates.

```python
# TableViewer._modified_cells structure:
{
    "Fuel Map Main": {(0, 5), (1, 3), (2, 7)},  # (data_row, data_col)
    "Ignition Timing": {(4, 2), (5, 1)},
    "Fuel Map Main:x_axis": {0, 3, 7},  # X-axis indices
    "Fuel Map Main:y_axis": {2, 5}      # Y-axis indices
}
```

### Why This Works

1. **Data coordinates are stable** - don't change based on UI layout (flipx/flipy)
2. **Tracked by table name** - persists across window close/reopen
3. **Delegate queries viewer** - no internal state in delegate
4. **Signal-based tracking** - doesn't modify editing logic
5. **Uses existing Qt.UserRole data** - cell items already store their data coords

## Files Created

### 1. `src/ui/table_viewer_helpers/cell_delegate.py`

Custom `QStyledItemDelegate` that:
- Calls `viewer.is_cell_modified(row, col)` during paint
- Draws 2px gray border if cell is modified
- Uses `QPainter` with native drawing (cross-platform)

```python
class ModifiedCellDelegate(QStyledItemDelegate):
    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if self.viewer.is_cell_modified(index.row(), index.column()):
            painter.save()
            pen = QPen(QColor(100, 100, 100), 2)
            painter.setPen(pen)
            rect = option.rect.adjusted(1, 1, -1, -1)
            painter.drawRect(rect)
            painter.restore()
```

## Files Modified

### 2. `src/ui/table_viewer.py`

**Added:**
- `_modified_cells` dict in `__init__`
- Set delegate on table widget
- Connected signals to tracking methods
- `is_cell_modified(ui_row, ui_col)` - checks if cell is modified
- `mark_cell_modified(table_name, data_row, data_col)` - marks cell
- `mark_axis_cell_modified(table_name, axis_type, data_idx)` - marks axis cell
- `_on_cell_changed_track_modifications()` - signal handler
- `_on_bulk_changes_track_modifications()` - signal handler
- `_on_axis_changed_track_modifications()` - signal handler
- `_on_axis_bulk_changes_track_modifications()` - signal handler

**Key method:**
```python
def is_cell_modified(self, ui_row: int, ui_col: int) -> bool:
    """Check if a cell is modified (for delegate painting)"""
    if not self.current_table:
        return False

    item = self.table_widget.item(ui_row, ui_col)
    if not item:
        return False

    data_indices = item.data(Qt.UserRole)
    if data_indices is None:
        return False

    # Handle axis cells
    if isinstance(data_indices[0], str):
        axis_type, data_idx = data_indices
        axis_key = f"{self.current_table.name}:{axis_type}"
        return axis_key in self._modified_cells and data_idx in self._modified_cells[axis_key]

    # Handle data cells
    data_row, data_col = data_indices
    table_name = self.current_table.name
    if table_name in self._modified_cells:
        return (data_row, data_col) in self._modified_cells[table_name]

    return False
```

### 3. `src/ui/table_viewer_helpers/__init__.py`

Added `ModifiedCellDelegate` to exports.

## How It Works

### When User Edits Cell

1. **User types new value** in cell (e.g., row 6, col 4)
2. `editing.py:on_cell_changed()` processes edit
3. Emits `cell_changed(table_name, data_row, data_col, ...)`
4. `TableViewer._on_cell_changed_track_modifications()` receives signal
5. Calls `mark_cell_modified(table_name, data_row, data_col)`
6. Adds `(data_row, data_col)` to `_modified_cells[table_name]` set
7. Calls `viewport().update()` to trigger repaint
8. Delegate's `paint()` called for each visible cell
9. Delegate calls `viewer.is_cell_modified(ui_row, ui_col)`
10. Viewer gets item at (ui_row, ui_col)
11. Reads `data_indices = item.data(Qt.UserRole)`
12. Looks up in `_modified_cells[table_name]`
13. **Gray border drawn** if modified ✅

### When Table is Closed and Reopened

1. **User clicks different table** in browser
2. `TableViewer.display_table()` called with new table
3. `_modified_cells` dict is **NOT cleared**
4. User clicks back to original table
5. `display_table()` reloads table, sets `Qt.UserRole` on all cells
6. Delegate queries `is_cell_modified()` during paint
7. **Borders reappear** on previously modified cells ✅

### When Undo is Performed

1. **User presses Ctrl+Z**
2. Undo system calls `viewer.update_cell_value(data_row, data_col, old_value)`
3. Cell value reverts to original
4. **Border remains** (cell is still in `_modified_cells`)
5. This is correct behavior - cell was modified during session

## Testing Checklist

### ✅ Test 1: Basic Edit Shows Border
1. Open a 3D table
2. Edit a cell
3. **Expected**: Gray border appears immediately

### ✅ Test 2: Undo Works Correctly
1. Edit cell (border appears)
2. Press Ctrl+Z
3. **Expected**: Value reverts, border remains
4. **Expected**: Undo affects correct cell (not cell above)

### ✅ Test 3: Persistent Across Table Switch
1. Open "Fuel Map Main", edit cell at row 2, col 5
2. Gray border appears
3. Click different table in browser
4. Click back to "Fuel Map Main"
5. **Expected**: Gray border still visible on row 2, col 5 ✅

### ✅ Test 4: Bulk Operations
1. Select multiple cells
2. Use interpolation (V, H, or B)
3. **Expected**: All interpolated cells have gray borders

### ✅ Test 5: Axis Cell Editing
1. Edit an X-axis value
2. **Expected**: Gray border around X-axis cell
3. Edit a Y-axis value
4. **Expected**: Gray border around Y-axis cell

### ✅ Test 6: Multiple Tables
1. Edit cells in "Fuel Map Main"
2. Edit cells in "Ignition Timing"
3. Switch between tables
4. **Expected**: Each table remembers its own modified cells

## Technical Details

### Coordinate Systems

**UI Coordinates:**
- Row/col in QTableWidget
- For 3D tables: Row 0 = labels, Row 1 = X-axis, Row 2+ = data
- Used by delegate for painting

**Data Coordinates:**
- Direct indices into numpy array
- Stable regardless of UI layout or flipx/flipy
- Stored in `_modified_cells` dict

### Qt.UserRole Data

Each cell stores its data coordinates when table is loaded:
```python
# In display.py
item.setData(Qt.UserRole, (data_row, data_col))  # Data cells
item.setData(Qt.UserRole, ('x_axis', index))     # X-axis cells
item.setData(Qt.UserRole, ('y_axis', index))     # Y-axis cells
```

This allows `is_cell_modified()` to convert UI coords → data coords for lookup.

### Signal Flow

```
User edits cell
  ↓
editing.py:on_cell_changed()
  ↓
Emits cell_changed(table_name, data_row, data_col, ...)
  ↓
TableViewer._on_cell_changed_track_modifications()
  ↓
mark_cell_modified() adds to _modified_cells[table_name]
  ↓
viewport().update() forces repaint
  ↓
delegate.paint() for each visible cell
  ↓
viewer.is_cell_modified(ui_row, ui_col) checks dict
  ↓
Gray border drawn if modified
```

## Limitations

### Current Behavior
- Borders persist for entire session (not saved to disk)
- All modified cells look the same (single gray border)
- Undo reverts value but border remains (shows cell was touched)
- No manual way to clear borders (except restart app)

### Not Implemented
- Clear modified borders button
- Save/load modified state with project
- Different border colors for different change types
- Modified count in table browser
- Export list of modified cells

## Why This Implementation Succeeds

### Previous Attempts Failed Because:
1. Tracked UI coordinates instead of data coordinates
2. Modified editing logic which broke undo
3. Delegate had internal state that didn't persist

### This Implementation Succeeds Because:
1. ✅ **Tracks data coordinates** - stable across UI changes
2. ✅ **Tracks by table name** - persists across window switches
3. ✅ **Doesn't modify editing logic** - undo unchanged
4. ✅ **Signal-based** - clean separation of concerns
5. ✅ **Stateless delegate** - just queries viewer

## Testing Results

✅ **All 92 tests pass**
✅ **Undo works correctly** (affects right cells)
✅ **Borders appear** when cells are modified
✅ **Borders persist** when tables are closed and reopened
✅ **No regressions** in existing functionality

## Status

✅ **Complete and tested**
- Gray borders show modified cells
- Undo works correctly
- Borders persist during session
- All tests pass

Ready for user testing!
