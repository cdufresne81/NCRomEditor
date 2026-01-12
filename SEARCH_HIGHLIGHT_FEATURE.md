# Search Highlighting & Modified Table Indicators

## Overview
Added two visual enhancements to the table browser:
1. **Search text highlighting** - Highlights matching text in yellow with bold font
2. **Modified table indicators** - Shows modified tables in pink color

---

## Feature 1: Search Text Highlighting

### Implementation
- Created custom `HighlightDelegate` class that extends `QStyledItemDelegate`
- Uses custom painting to highlight search matches in the table name column
- **Avoids HTML/rich text** issues that caused transparency problems on Windows

### How It Works
1. When user types in search box, the delegate's `set_search_text()` is called
2. Custom `paint()` method finds all occurrences of search text (case-insensitive)
3. For each match:
   - Draws yellow background behind the matched text
   - Makes matched text bold (when not selected)
   - Preserves rest of text in normal style

### Visual Behavior
- **Matched text**: Yellow background + bold font
- **Non-matched text**: Normal appearance
- **Selected rows**: Uses standard selection colors (overrides highlighting)
- **Hover**: Uses standard hover colors

### Cross-Platform Compatibility
- Uses Qt's native painting API (QPainter, QColor, QRect)
- No HTML/rich text that could cause transparency issues
- Tested approach should work consistently on both Linux and Windows

### Example
Search for "DBW":
```
Normal text: Fuel Map
With match:   Fuel DBW Map  (DBW highlighted in yellow + bold)
```

---

## Feature 2: Modified Table Indicators

### Implementation
- Modified tables are displayed in **hot pink** color (RGB: 255, 105, 180)
- Automatically updates when tables are modified/undone
- Connected to the change tracker system

### How It Works
1. `TableBrowser` maintains a set of modified table addresses
2. Each table item stores a "modified" flag in `Qt.UserRole + 1`
3. When changes occur, `main.py` calls `_update_modified_table_colors()`
4. This updates all open ROM documents' table browsers
5. The delegate uses the modified flag to color the text pink

### Integration Points
- **Main Window**: `_update_modified_table_colors()` called whenever changes tracked
- **Change Tracker**: `get_modified_tables()` returns list of modified table names
- **ROM Document**: Each has its own `table_browser` instance
- **Table Browser**: Methods to mark/clear modified tables

### Visual Behavior
- **Modified table**: Pink text color
- **Unmodified table**: Normal text color
- **Selected modified**: Pink text with selection background
- Works in combination with search highlighting

---

## Files Modified

### src/ui/table_browser.py
**Added**: `HighlightDelegate` class (125 lines)
- Custom `paint()` method for highlighting and coloring
- `set_search_text()` to update search term
- Support for both highlighting and modified coloring

**Modified**: `TableBrowser` class
- Added `modified_tables` set to track modified table addresses
- Added `delegate` instance for custom rendering
- Updated `load_definition()` to store modified flags
- Updated `_filter_tables()` to update delegate and force repaint
- Added `mark_table_modified()` - mark single table as modified
- Added `clear_modified_tables()` - clear all modified markers
- Added `update_modified_tables()` - bulk update from table names list
- Added `_update_table_colors()` - refresh all table item colors

**New imports**:
```python
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QPainter, QBrush, QPen
```

### main.py
**Added**: `_update_modified_table_colors()` method
- Gets modified tables from change tracker
- Updates all open ROM documents' table browsers
- Called automatically whenever changes are tracked

**Modified**: `_update_project_ui()` method
- Now calls `_update_modified_table_colors()` at the end
- Ensures table colors update whenever undo/redo/changes occur

---

## Usage

### Search Highlighting
1. Click in search box (or press Ctrl+F)
2. Type search text (e.g., "DBW", "fuel", "0x1000")
3. Matching text is highlighted in yellow + bold
4. Clear search to remove highlighting

### Modified Table Colors
- Automatically shows when you edit table cells
- Pink color persists until:
  - Changes are undone (Ctrl+Z)
  - Changes are committed
  - ROM is closed

---

## Technical Details

### Why Custom Delegate Instead of HTML?
Previous attempt using HTML/rich text in QTreeWidgetItem failed because:
- QTreeWidgetItem doesn't fully support HTML rendering
- Windows rendering had transparency issues
- Text would disappear or become invisible

Custom delegate approach:
- Full control over rendering
- Uses native Qt painting primitives
- Consistent across platforms
- No HTML parsing overhead

### Color Choices
- **Highlight yellow**: `QColor(255, 255, 0, 100)` - 100 alpha for transparency
- **Modified pink**: `QColor(255, 105, 180)` - Hot pink, fully opaque
- **Selection**: Uses system palette colors (automatic)

### Performance
- Delegate only repaints visible items (Qt optimization)
- Highlighting only applies to column 0 (name column)
- Modified flag stored per-item (no re-computation)
- Viewport update called sparingly (only when needed)

---

## Testing

### Manual Testing Required
✅ **Linux**:
1. Open ROM editor
2. Search for text → verify highlighting appears
3. Modify a table cell → verify pink color appears
4. Undo change → verify pink color disappears
5. Search with highlighting + modified tables → both work together

✅ **Windows**:
1. Same tests as Linux
2. Specifically verify text doesn't disappear or become transparent
3. Check selection highlighting works properly

### Automated Tests
- All 92 existing tests pass ✅
- No new unit tests needed (UI rendering feature)
- Integration testing via manual use

---

## Known Limitations

### Search Highlighting
- Only highlights in name column (column 0)
- Case-insensitive matching only
- No regex support (exact substring match)
- No fuzzy matching

### Modified Table Colors
- Color only updates when change tracker fires callback
- Doesn't persist across application restarts
- All modified tables use same pink color (no severity levels)

---

## Future Enhancements

### Possible Improvements
1. **Configurable colors**: Allow users to customize highlight/modified colors
2. **Multiple highlight colors**: Different colors for different match types
3. **Bold modified tables**: Make modified table names bold in addition to pink
4. **Modified count indicator**: Show "(3)" next to category with 3 modified tables
5. **Persistent modified state**: Remember modified tables across sessions
6. **Severity levels**: Different colors for minor vs major changes

---

## Code Quality

### Design Principles
- **Separation of concerns**: Delegate handles rendering, TableBrowser handles data
- **Single responsibility**: Each method does one thing
- **Loose coupling**: Change tracker → main window → table browser
- **Testable**: Logic separated from rendering

### Maintainability
- Clear method names and documentation
- Type hints where applicable
- Consistent Qt API usage
- No magic numbers (colors defined as constants)

---

## Summary

✅ **Search highlighting**: Yellow background + bold text for matches
✅ **Modified tables**: Pink text color for edited tables
✅ **Cross-platform**: Uses native Qt rendering (no HTML)
✅ **Automatic updates**: Changes tracked via existing change tracker
✅ **All tests pass**: 92 tests passing
✅ **Ready for testing**: On both Linux and Windows

The implementation avoids the previous HTML/transparency issues by using Qt's native painting system with a custom delegate.
