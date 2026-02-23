"""
ROM Comparison Window

Side-by-side comparison of two ROM files, showing only tables that differ.
Read-only view with synchronized scrolling and keyboard navigation.
"""

import logging
import re

import numpy as np
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QTreeWidget,
    QTreeWidgetItem, QLabel, QToolBar, QToolButton, QApplication,
    QStyledItemDelegate,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import (
    QColor, QBrush, QIcon, QPainter, QPen, QPixmap,
    QKeySequence, QShortcut,
)

from ..core.rom_definition import Table, TableType, AxisType, RomDefinition
from ..core.rom_reader import RomReader
from ..utils.colormap import get_colormap
from ..utils.settings import get_settings

logger = logging.getLogger(__name__)

_PRINTF_PATTERN = re.compile(r'%[-+0 #]*(\d*)\.?(\d*)([diouxXeEfFgGaAcspn%])')


def _printf_to_python_format(printf_format: str) -> str:
    """Convert printf-style format to Python format spec."""
    if not printf_format:
        return ".2f"
    match = _PRINTF_PATTERN.match(printf_format)
    if not match:
        return ".2f"
    width = match.group(1)
    precision = match.group(2)
    specifier = match.group(3)
    result = ""
    if width:
        result += width
    if precision:
        result += f".{precision}"
    result += specifier
    return result


def _format_value(value: float, format_spec: str) -> str:
    """Format a value using the given format spec with error handling."""
    try:
        return f"{value:{format_spec}}"
    except (ValueError, TypeError):
        return f"{value:.2f}"


def _get_scaling_format(rom_definition: RomDefinition, scaling_name: str) -> str:
    """Get Python format spec for a scaling name."""
    if not rom_definition or not scaling_name:
        return ".2f"
    scaling = rom_definition.get_scaling(scaling_name)
    if not scaling or not scaling.format:
        return ".2f"
    return _printf_to_python_format(scaling.format)


def _get_scaling_range(rom_definition: RomDefinition, scaling_name: str):
    """Get (min, max) from scaling, or None if not defined."""
    if not rom_definition or not scaling_name:
        return None
    scaling = rom_definition.get_scaling(scaling_name)
    if not scaling:
        return None
    if scaling.min == 0 and scaling.max == 0:
        return None
    if scaling.min == scaling.max:
        return None
    return (scaling.min, scaling.max)


class _CompareCellDelegate(QStyledItemDelegate):
    """Draws a 2px gray border around changed cells, matching ModifiedCellDelegate."""

    BORDER_COLOR = QColor(100, 100, 100)
    BORDER_WIDTH = 2

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.data(Qt.UserRole):
            painter.save()
            pen = QPen(self.BORDER_COLOR, self.BORDER_WIDTH)
            pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen)
            rect = option.rect.adjusted(1, 1, -1, -1)
            painter.drawRect(rect)
            painter.restore()


class CompareWindow(QMainWindow):
    """Side-by-side ROM comparison window"""

    def __init__(self, rom_reader_a: RomReader, rom_reader_b: RomReader,
                 rom_definition: RomDefinition,
                 color_a: QColor, color_b: QColor,
                 name_a: str, name_b: str,
                 parent=None):
        super().__init__(parent)

        self._reader_a = rom_reader_a
        self._reader_b = rom_reader_b
        self._definition = rom_definition
        self._color_a = color_a
        self._color_b = color_b
        self._name_a = name_a
        self._name_b = name_b
        self._changed_only = False
        self._syncing_scroll = False
        self._current_index = -1

        self.setWindowFlags(
            Qt.Window |
            Qt.WindowCloseButtonHint |
            Qt.WindowMaximizeButtonHint |
            Qt.CustomizeWindowHint |
            Qt.WindowTitleHint
        )
        self.setWindowTitle(f"ROM Compare \u2014 {name_a} vs {name_b}")

        # Compute diffs for all tables
        self._modified_tables = []
        self._compute_diffs()

        if not self._modified_tables:
            # Will be handled by caller — show message and don't open
            return

        # Build UI
        self._build_ui()
        self._setup_shortcuts()

        # Select first table
        self._select_table(0)

        # Auto-size window
        self._auto_size()

    @property
    def has_diffs(self):
        return len(self._modified_tables) > 0

    def _compute_diffs(self):
        """Compare all tables between the two ROMs and collect differences."""
        for table in self._definition.tables:
            try:
                data_a = self._reader_a.read_table_data(table)
                data_b = self._reader_b.read_table_data(table)
            except Exception as e:
                logger.warning(f"Skipping table {table.name}: {e}")
                continue

            values_a = data_a.get('values')
            values_b = data_b.get('values')
            if values_a is None or values_b is None:
                continue

            # Compare values
            if values_a.shape != values_b.shape:
                # Shape mismatch — treat all cells as changed
                changed = set()
                for idx in np.ndindex(values_b.shape):
                    changed.add(idx)
            elif np.array_equal(values_a, values_b):
                # Also check axes
                axes_differ = False
                for key in ('x_axis', 'y_axis'):
                    ax_a = data_a.get(key)
                    ax_b = data_b.get(key)
                    if ax_a is not None and ax_b is not None:
                        if not np.array_equal(ax_a, ax_b):
                            axes_differ = True
                            break
                if not axes_differ:
                    continue
                changed = set()  # Only axes differ, no data cell changes
            else:
                # Find which cells differ
                changed = set()
                if values_a.ndim == 1:
                    for i in range(len(values_a)):
                        if values_a[i] != values_b[i]:
                            changed.add((i, 0))
                else:
                    diff_mask = values_a != values_b
                    for idx in zip(*np.where(diff_mask)):
                        changed.add(tuple(idx))

            # Check axis changes
            changed_axes = {}
            for key in ('x_axis', 'y_axis'):
                ax_a = data_a.get(key)
                ax_b = data_b.get(key)
                if ax_a is not None and ax_b is not None and not np.array_equal(ax_a, ax_b):
                    axis_changed = set()
                    for i in range(min(len(ax_a), len(ax_b))):
                        if ax_a[i] != ax_b[i]:
                            axis_changed.add(i)
                    if axis_changed:
                        changed_axes[key] = axis_changed

            total_changes = len(changed) + sum(len(v) for v in changed_axes.values())
            if total_changes == 0 and not changed_axes:
                continue

            self._modified_tables.append({
                'table': table,
                'data_a': data_a,
                'data_b': data_b,
                'changed_cells': changed,
                'changed_axes': changed_axes,
                'change_count': total_changes,
            })

        # Sort by category then name for consistent ordering
        self._modified_tables.sort(key=lambda d: (d['table'].category or '', d['table'].name))

    def _build_ui(self):
        """Build the complete window UI."""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        self._build_toolbar()

        # Main splitter: sidebar + compare area
        self._main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self._main_splitter)

        # Sidebar
        self._build_sidebar()
        self._main_splitter.addWidget(self._sidebar)

        # Compare area (right side)
        compare_widget = QWidget()
        compare_layout = QVBoxLayout(compare_widget)
        compare_layout.setContentsMargins(0, 0, 0, 0)
        compare_layout.setSpacing(0)

        # Table panels splitter (includes compact "Original" / "Modified" labels)
        self._table_splitter = QSplitter(Qt.Horizontal)
        self._build_table_panels()
        compare_layout.addWidget(self._table_splitter)

        self._main_splitter.addWidget(compare_widget)
        self._main_splitter.setSizes([220, 800])
        self._main_splitter.setStretchFactor(0, 0)  # Sidebar fixed
        self._main_splitter.setStretchFactor(1, 1)  # Compare area stretches

        # Status bar
        self._status_label = QLabel()
        self.statusBar().addWidget(self._status_label, 1)
        self._shortcut_label = QLabel()
        self._shortcut_label.setStyleSheet("color: #888; font-size: 11px;")
        self.statusBar().addPermanentWidget(self._shortcut_label)
        self._shortcut_label.setText("\u2191\u2193 Navigate   T Toggle changed only   Esc Close")

    def _build_toolbar(self):
        """Create the toolbar with navigation and toggle controls."""
        tb = self.addToolBar("Compare")
        tb.setObjectName("compareToolbar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setStyleSheet("""
            QToolBar {
                spacing: 1px;
                padding: 1px 4px;
                border: none;
            }
            QToolButton {
                padding: 3px;
                border: 1px solid transparent;
                border-radius: 3px;
            }
            QToolButton:hover {
                background: rgba(128, 128, 128, 0.15);
                border: 1px solid rgba(128, 128, 128, 0.25);
            }
            QToolButton:pressed {
                background: rgba(128, 128, 128, 0.3);
            }
        """)

        # ROM labels with color swatches
        rom_label_a = self._make_rom_label(self._name_a, self._color_a)
        tb.addWidget(rom_label_a)

        vs_label = QLabel("  vs  ")
        vs_label.setStyleSheet("color: #999; font-size: 12px;")
        tb.addWidget(vs_label)

        rom_label_b = self._make_rom_label(self._name_b, self._color_b)
        tb.addWidget(rom_label_b)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy().Preferred)
        tb.addWidget(spacer)

        # Navigation
        prev_btn = tb.addAction(self._make_nav_icon("up"), "")
        prev_btn.setToolTip("Previous table (\u2191)")
        prev_btn.triggered.connect(self._prev_table)

        self._counter_label = QLabel(" 0 / 0 ")
        self._counter_label.setStyleSheet("color: #555; font-size: 12px; padding: 0 4px;")
        tb.addWidget(self._counter_label)

        next_btn = tb.addAction(self._make_nav_icon("down"), "")
        next_btn.setToolTip("Next table (\u2193)")
        next_btn.triggered.connect(self._next_table)

        # Separator
        tb.addSeparator()

        # Changed-only toggle
        toggle_label = QLabel(" Changed only ")
        toggle_label.setStyleSheet("font-size: 12px; color: #555;")
        tb.addWidget(toggle_label)

        from .widgets.toggle_switch import ToggleSwitch
        self._toggle = ToggleSwitch()
        self._toggle.setChecked(False)
        self._toggle.toggled.connect(self._on_toggle_changed)
        tb.addWidget(self._toggle)

    def _make_rom_label(self, name: str, color: QColor) -> QWidget:
        """Create a ROM label widget with color swatch."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 8, 2)
        layout.setSpacing(4)

        # Color swatch
        swatch = QLabel()
        swatch.setFixedSize(12, 12)
        fill_color = color if color else self.palette().window().color()
        swatch.setStyleSheet(
            f"background-color: {fill_color.name()}; "
            f"border: 1px solid #888; border-radius: 2px;"
        )
        layout.addWidget(swatch)

        # Name
        label = QLabel(name)
        label.setStyleSheet("font-size: 12px; font-weight: 500;")
        layout.addWidget(label)

        return widget

    def _make_nav_icon(self, direction: str) -> QIcon:
        """Create navigation arrow icons matching existing toolbar style."""
        s = 20
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(s * dpr), int(s * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.palette().windowText().color()
        pen = QPen(c, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)

        if direction == "up":
            p.drawLine(4, 12, 10, 6)
            p.drawLine(10, 6, 16, 12)
        else:
            p.drawLine(4, 8, 10, 14)
            p.drawLine(10, 14, 16, 8)

        p.end()
        return QIcon(pm)

    def _build_sidebar(self):
        """Build the modified tables sidebar with a category tree."""
        self._sidebar = QWidget()
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Header
        header = QLabel(f"  Modified Tables ({len(self._modified_tables)})")
        header.setStyleSheet(
            "padding: 4px 10px; font-weight: 600; font-size: 12px; "
            "background: #f5f5f5; border-bottom: 1px solid #d0d0d0; "
            "color: #444;"
        )
        sidebar_layout.addWidget(header)

        # Tree widget grouped by category
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(14)
        self._tree.setStyleSheet("""
            QTreeWidget {
                border: none;
                outline: none;
                font-size: 12px;
            }
            QTreeWidget::item {
                padding: 1px 0px;
            }
            QTreeWidget::item:selected {
                background: #e0ecf8;
                color: black;
            }
            QTreeWidget::item:hover:!selected {
                background: #f0f4fa;
            }
        """)

        # Group tables by category
        self._tree_items = {}  # diff index -> QTreeWidgetItem
        categories = {}
        for i, entry in enumerate(self._modified_tables):
            cat = entry['table'].category or 'Uncategorized'
            if cat not in categories:
                categories[cat] = []
            categories[cat].append((i, entry))

        for cat_name in sorted(categories.keys()):
            entries = categories[cat_name]
            cat_item = QTreeWidgetItem([f"{cat_name} ({len(entries)})"])
            cat_item.setData(0, Qt.UserRole, None)  # Mark as category
            self._tree.addTopLevelItem(cat_item)

            for idx, entry in entries:
                table = entry['table']
                count = entry['change_count']
                suffix = "cell" if count == 1 else "cells"
                item = QTreeWidgetItem([f"{table.name}  ({count} {suffix})"])
                item.setData(0, Qt.UserRole, idx)
                cat_item.addChild(item)
                self._tree_items[idx] = item

            cat_item.setExpanded(True)

        self._tree.currentItemChanged.connect(self._on_tree_selection)
        sidebar_layout.addWidget(self._tree)

        self._sidebar.setMinimumWidth(200)
        self._sidebar.setMaximumWidth(300)

    def _build_table_panels(self):
        """Create the two QTableWidget panels with compact labels for side-by-side comparison."""
        font_size = get_settings().get_table_font_size()
        table_css = f"""
            QTableWidget {{
                font-size: {font_size}px;
                gridline-color: #a0a0a0;
            }}
            QTableWidget::item {{
                padding: 0px 1px;
            }}
        """
        row_height = font_size + 2
        label_css = "font-size: 11px; color: #888; padding: 2px 4px; border-bottom: 1px solid #d0d0d0;"

        # Left panel: "Original" label + table
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_label = QLabel("  Original")
        left_label.setStyleSheet(label_css)
        left_layout.addWidget(left_label)

        self._table_left = QTableWidget()
        self._table_left.setStyleSheet(table_css)
        self._table_left.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table_left.setSelectionMode(QTableWidget.NoSelection)
        self._table_left.verticalHeader().setVisible(False)
        self._table_left.horizontalHeader().setVisible(False)
        self._table_left.verticalHeader().setDefaultSectionSize(row_height)
        self._table_left.setItemDelegate(_CompareCellDelegate(self._table_left))
        left_layout.addWidget(self._table_left)

        # Right panel: "Modified" label + table
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_label = QLabel("  Modified")
        right_label.setStyleSheet(label_css)
        right_layout.addWidget(right_label)

        self._table_right = QTableWidget()
        self._table_right.setStyleSheet(table_css)
        self._table_right.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table_right.setSelectionMode(QTableWidget.NoSelection)
        self._table_right.verticalHeader().setVisible(False)
        self._table_right.horizontalHeader().setVisible(False)
        self._table_right.verticalHeader().setDefaultSectionSize(row_height)
        self._table_right.setItemDelegate(_CompareCellDelegate(self._table_right))
        right_layout.addWidget(self._table_right)

        self._table_splitter.addWidget(left_panel)
        self._table_splitter.addWidget(right_panel)

        # Sync scrolling
        self._connect_scroll_sync(
            self._table_left.horizontalScrollBar(),
            self._table_right.horizontalScrollBar(),
        )
        self._connect_scroll_sync(
            self._table_left.verticalScrollBar(),
            self._table_right.verticalScrollBar(),
        )

    def _connect_scroll_sync(self, bar_a, bar_b):
        """Synchronize two scrollbars without recursive loops."""
        def sync_a_to_b(value):
            if not self._syncing_scroll:
                self._syncing_scroll = True
                bar_b.setValue(value)
                self._syncing_scroll = False

        def sync_b_to_a(value):
            if not self._syncing_scroll:
                self._syncing_scroll = True
                bar_a.setValue(value)
                self._syncing_scroll = False

        bar_a.valueChanged.connect(sync_a_to_b)
        bar_b.valueChanged.connect(sync_b_to_a)

    def _setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        up = QShortcut(QKeySequence(Qt.Key_Up), self)
        up.activated.connect(self._prev_table)

        down = QShortcut(QKeySequence(Qt.Key_Down), self)
        down.activated.connect(self._next_table)

        toggle = QShortcut(QKeySequence(Qt.Key_T), self)
        toggle.activated.connect(lambda: self._toggle.setChecked(not self._toggle.isChecked()))

        close = QShortcut(QKeySequence(Qt.Key_Escape), self)
        close.activated.connect(self.close)

    # ========== Navigation ==========

    def _select_table(self, index: int):
        """Display the table at the given index in both panels."""
        if index < 0 or index >= len(self._modified_tables):
            return

        self._current_index = index
        entry = self._modified_tables[index]

        # Update sidebar tree
        self._tree.blockSignals(True)
        item = self._tree_items.get(index)
        if item:
            self._tree.setCurrentItem(item)
            self._tree.scrollToItem(item)
        self._tree.blockSignals(False)

        # Update counter
        self._counter_label.setText(f" {index + 1} / {len(self._modified_tables)} ")

        # Display table data in both panels
        table = entry['table']
        self._populate_table(self._table_left, table, entry['data_a'],
                             entry['changed_cells'], entry['changed_axes'])
        self._populate_table(self._table_right, table, entry['data_b'],
                             entry['changed_cells'], entry['changed_axes'])

        # Sync column widths between panels
        self._sync_column_widths()

        # Update status bar
        count = entry['change_count']
        suffix = "cell" if count == 1 else "cells"
        self._status_label.setText(
            f"  {table.name} ({table.address}) \u2014 {count} changed {suffix}"
        )

        # Reset scroll positions
        self._table_left.horizontalScrollBar().setValue(0)
        self._table_left.verticalScrollBar().setValue(0)

    def _on_tree_selection(self, current, previous):
        """Handle sidebar tree selection."""
        if current:
            idx = current.data(0, Qt.UserRole)
            if idx is not None:
                self._select_table(idx)

    def _prev_table(self):
        """Navigate to the previous table."""
        if self._current_index > 0:
            self._select_table(self._current_index - 1)

    def _next_table(self):
        """Navigate to the next table."""
        if self._current_index < len(self._modified_tables) - 1:
            self._select_table(self._current_index + 1)

    # ========== Toggle ==========

    def _on_toggle_changed(self, checked: bool):
        """Handle changed-only toggle."""
        self._changed_only = checked
        # Re-display current table to apply dimming
        if self._current_index >= 0:
            self._select_table(self._current_index)

    # ========== Table Population ==========

    def _populate_table(self, widget: QTableWidget, table: Table,
                        data: dict, changed_cells: set, changed_axes: dict):
        """Populate a QTableWidget with table data, highlighting changed cells."""
        widget.blockSignals(True)
        widget.setUpdatesEnabled(False)
        try:
            values = data['values']

            if table.type == TableType.ONE_D:
                self._populate_1d(widget, table, values, changed_cells)
            elif table.type == TableType.TWO_D:
                self._populate_2d(widget, table, values,
                                  data.get('y_axis'), changed_cells, changed_axes)
            elif table.type == TableType.THREE_D:
                self._populate_3d(widget, table, values,
                                  data.get('x_axis'), data.get('y_axis'),
                                  changed_cells, changed_axes)
        finally:
            widget.blockSignals(False)
            widget.setUpdatesEnabled(True)
            widget.viewport().update()

    def _populate_1d(self, widget: QTableWidget, table: Table,
                     values: np.ndarray, changed_cells: set):
        """Populate 1D table (single value)."""
        widget.setRowCount(1)
        widget.setColumnCount(1)

        value_fmt = _get_scaling_format(self._definition, table.scaling)
        item = QTableWidgetItem(_format_value(values[0], value_fmt))

        color = self._get_cell_color(values[0], values, table)
        is_changed = (0, 0) in changed_cells

        if self._changed_only and not is_changed:
            item.setBackground(QBrush(self._dim_color(color)))
            item.setForeground(QBrush(QColor(0, 0, 0, 60)))
        else:
            item.setBackground(QBrush(color))
        if is_changed:
            item.setData(Qt.UserRole, True)

        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        widget.setItem(0, 0, item)
        widget.resizeColumnsToContents()

    def _populate_2d(self, widget: QTableWidget, table: Table,
                     values: np.ndarray, y_axis: np.ndarray,
                     changed_cells: set, changed_axes: dict):
        """Populate 2D table (Y-axis + data column)."""
        num_values = len(values)
        widget.setRowCount(num_values)
        widget.setColumnCount(2)

        value_fmt = _get_scaling_format(self._definition, table.scaling)
        y_fmt = self._get_axis_format(table, AxisType.Y_AXIS)

        # Flip
        flipy = table.flipy
        display_values = values[::-1] if flipy else values
        display_y = y_axis[::-1] if (y_axis is not None and flipy) else y_axis

        # Y-axis gradient range
        y_min, y_max = self._get_axis_range(table, AxisType.Y_AXIS, display_y)
        y_changed = changed_axes.get('y_axis', set())

        for i in range(num_values):
            data_idx = (num_values - 1 - i) if flipy else i

            # Y-axis cell
            if display_y is not None and i < len(display_y):
                y_item = QTableWidgetItem(_format_value(display_y[i], y_fmt))
                y_color = self._axis_gradient_color(display_y[i], y_min, y_max)
                is_y_changed = data_idx in y_changed
                if self._changed_only and not is_y_changed:
                    y_item.setBackground(QBrush(self._dim_color(y_color)))
                    y_item.setForeground(QBrush(QColor(0, 0, 0, 60)))
                else:
                    y_item.setBackground(QBrush(y_color))
                if is_y_changed:
                    y_item.setData(Qt.UserRole, True)
            else:
                y_item = QTableWidgetItem(str(i))
                y_item.setBackground(QBrush(QColor(220, 220, 220)))
            y_item.setFlags(y_item.flags() & ~Qt.ItemIsEditable)
            widget.setItem(i, 0, y_item)

            # Data cell
            val_item = QTableWidgetItem(_format_value(display_values[i], value_fmt))
            color = self._get_cell_color(display_values[i], values, table)
            is_changed = (data_idx, 0) in changed_cells

            if self._changed_only and not is_changed:
                val_item.setBackground(QBrush(self._dim_color(color)))
                val_item.setForeground(QBrush(QColor(0, 0, 0, 60)))
            else:
                val_item.setBackground(QBrush(color))
            if is_changed:
                val_item.setData(Qt.UserRole, True)
            val_item.setFlags(val_item.flags() & ~Qt.ItemIsEditable)
            widget.setItem(i, 1, val_item)

        widget.resizeColumnsToContents()

    def _populate_3d(self, widget: QTableWidget, table: Table,
                     values: np.ndarray, x_axis: np.ndarray, y_axis: np.ndarray,
                     changed_cells: set, changed_axes: dict):
        """Populate 3D table with ECUFlash-style layout."""
        if values.ndim != 2:
            self._populate_1d(widget, table, values.flatten(), changed_cells)
            return

        rows, cols = values.shape

        widget.setRowCount(rows + 1)
        widget.setColumnCount(cols + 1)

        value_fmt = _get_scaling_format(self._definition, table.scaling)
        x_fmt = self._get_axis_format(table, AxisType.X_AXIS)
        y_fmt = self._get_axis_format(table, AxisType.Y_AXIS)

        # Flips
        flipx = table.flipx
        flipy = table.flipy
        display_x = x_axis[::-1] if (x_axis is not None and flipx) else x_axis
        display_y = y_axis[::-1] if (y_axis is not None and flipy) else y_axis
        display_values = values.copy()
        if flipy:
            display_values = display_values[::-1, :]
        if flipx:
            display_values = display_values[:, ::-1]

        label_bg = QBrush(QColor(220, 220, 220))
        x_changed = changed_axes.get('x_axis', set())
        y_changed = changed_axes.get('y_axis', set())

        # Cell (0,0) - empty corner
        corner = QTableWidgetItem("")
        corner.setFlags(corner.flags() & ~Qt.ItemIsEditable)
        corner.setBackground(label_bg)
        widget.setItem(0, 0, corner)

        # X-axis range
        x_min, x_max = self._get_axis_range(table, AxisType.X_AXIS, display_x)

        # Row 0: X-axis values
        if display_x is not None and len(display_x) == cols:
            for col in range(cols):
                data_idx = (cols - 1 - col) if flipx else col
                x_item = QTableWidgetItem(_format_value(display_x[col], x_fmt))
                x_color = self._axis_gradient_color(display_x[col], x_min, x_max)
                is_x_changed = data_idx in x_changed

                if self._changed_only and not is_x_changed:
                    x_item.setBackground(QBrush(self._dim_color(x_color)))
                    x_item.setForeground(QBrush(QColor(0, 0, 0, 60)))
                else:
                    x_item.setBackground(QBrush(x_color))
                if is_x_changed:
                    x_item.setData(Qt.UserRole, True)
                x_item.setFlags(x_item.flags() & ~Qt.ItemIsEditable)
                widget.setItem(0, col + 1, x_item)
        else:
            for col in range(cols):
                x_item = QTableWidgetItem(str(col))
                x_item.setFlags(x_item.flags() & ~Qt.ItemIsEditable)
                x_item.setBackground(label_bg)
                widget.setItem(0, col + 1, x_item)

        # Y-axis range
        y_min, y_max = self._get_axis_range(table, AxisType.Y_AXIS, display_y)

        # Column 0: Y-axis values (rows 1+)
        if display_y is not None and len(display_y) == rows:
            for row in range(rows):
                data_idx = (rows - 1 - row) if flipy else row
                y_item = QTableWidgetItem(_format_value(display_y[row], y_fmt))
                y_color = self._axis_gradient_color(display_y[row], y_min, y_max)
                is_y_changed = data_idx in y_changed

                if self._changed_only and not is_y_changed:
                    y_item.setBackground(QBrush(self._dim_color(y_color)))
                    y_item.setForeground(QBrush(QColor(0, 0, 0, 60)))
                else:
                    y_item.setBackground(QBrush(y_color))
                if is_y_changed:
                    y_item.setData(Qt.UserRole, True)
                y_item.setFlags(y_item.flags() & ~Qt.ItemIsEditable)
                widget.setItem(row + 1, 0, y_item)
        else:
            for row in range(rows):
                y_item = QTableWidgetItem(str(row))
                y_item.setFlags(y_item.flags() & ~Qt.ItemIsEditable)
                y_item.setBackground(label_bg)
                widget.setItem(row + 1, 0, y_item)

        # Data cells (rows 1+, cols 1+)
        # Cache value range for color calculation
        scaling_range = _get_scaling_range(self._definition, table.scaling)
        if scaling_range:
            v_min, v_max = scaling_range
        else:
            v_min, v_max = float(np.min(values)), float(np.max(values))

        for row in range(rows):
            for col in range(cols):
                data_row = (rows - 1 - row) if flipy else row
                data_col = (cols - 1 - col) if flipx else col

                val_item = QTableWidgetItem(
                    _format_value(display_values[row, col], value_fmt)
                )

                # Color
                if v_max == v_min:
                    ratio = 0.5
                else:
                    ratio = (display_values[row, col] - v_min) / (v_max - v_min)
                    ratio = max(0.0, min(1.0, ratio))
                color = get_colormap().ratio_to_color(ratio)

                is_changed = (data_row, data_col) in changed_cells

                if self._changed_only and not is_changed:
                    val_item.setBackground(QBrush(self._dim_color(color)))
                    val_item.setForeground(QBrush(QColor(0, 0, 0, 60)))
                else:
                    val_item.setBackground(QBrush(color))
                if is_changed:
                    val_item.setData(Qt.UserRole, True)

                val_item.setFlags(val_item.flags() & ~Qt.ItemIsEditable)
                widget.setItem(row + 1, col + 1, val_item)

        # Resize columns
        widget.resizeColumnsToContents()

        # Uniform data column width (match existing pattern)
        max_width = 0
        for col in range(1, widget.columnCount()):
            w = widget.columnWidth(col)
            if w > max_width:
                max_width = w
        if max_width > 0:
            header = widget.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            for col in range(1, widget.columnCount()):
                header.setSectionResizeMode(col, QHeaderView.Fixed)
                widget.setColumnWidth(col, max_width)

    def _sync_column_widths(self):
        """Ensure both table panels have identical column widths."""
        left = self._table_left
        right = self._table_right
        count = min(left.columnCount(), right.columnCount())
        for col in range(count):
            w = max(left.columnWidth(col), right.columnWidth(col))
            left.setColumnWidth(col, w)
            right.setColumnWidth(col, w)
            left.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            right.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)

    # ========== Color Helpers ==========

    def _get_cell_color(self, value: float, values: np.ndarray,
                        table: Table) -> QColor:
        """Get thermal gradient color for a data cell value."""
        scaling_range = _get_scaling_range(self._definition, table.scaling)
        if scaling_range:
            min_val, max_val = scaling_range
        else:
            min_val = float(np.min(values))
            max_val = float(np.max(values))

        if max_val == min_val:
            ratio = 0.5
        else:
            ratio = (value - min_val) / (max_val - min_val)
            ratio = max(0.0, min(1.0, ratio))
        return get_colormap().ratio_to_color(ratio)

    def _axis_gradient_color(self, value: float, min_val: float,
                             max_val: float) -> QColor:
        """Get gradient color for an axis value."""
        if max_val == min_val:
            ratio = 0.5
        else:
            ratio = (value - min_val) / (max_val - min_val)
            ratio = max(0.0, min(1.0, ratio))
        return get_colormap().ratio_to_color(ratio)

    def _get_axis_range(self, table: Table, axis_type: AxisType,
                        display_axis: np.ndarray):
        """Get min/max for axis gradient coloring."""
        axis_table = table.get_axis(axis_type)
        if axis_table and axis_table.scaling:
            sr = _get_scaling_range(self._definition, axis_table.scaling)
            if sr:
                return sr
        if display_axis is not None and len(display_axis) > 0:
            return float(np.min(display_axis)), float(np.max(display_axis))
        return 0.0, 1.0

    def _get_axis_format(self, table: Table, axis_type: AxisType) -> str:
        """Get format spec for axis values."""
        axis_table = table.get_axis(axis_type)
        if axis_table and axis_table.scaling:
            return _get_scaling_format(self._definition, axis_table.scaling)
        return ".2f"

    def _dim_color(self, color: QColor) -> QColor:
        """Return a dimmed version of a color for unchanged cells."""
        # Blend toward white with high transparency
        r, g, b, _ = color.getRgb()
        # Mix 75% white + 25% original
        return QColor(
            r + (255 - r) * 3 // 4,
            g + (255 - g) * 3 // 4,
            b + (255 - b) * 3 // 4,
        )

    # ========== Window Sizing ==========

    def _auto_size(self):
        """Size the window to fit the content, up to screen limits."""
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            max_w = int(avail.width() * 0.9)
            max_h = int(avail.height() * 0.85)
        else:
            max_w = 1400
            max_h = 800

        # Start with a reasonable default
        self.resize(min(1200, max_w), min(700, max_h))

    def closeEvent(self, event):
        """Clean up on close."""
        parent = self.parent()
        if parent and hasattr(parent, 'compare_window'):
            parent.compare_window = None
        event.accept()
        self.deleteLater()
