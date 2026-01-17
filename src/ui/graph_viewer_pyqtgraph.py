"""
Graph Viewer (PyQtGraph Implementation)

Displays 3D visualization of table data using pyqtgraph with OpenGL hardware acceleration.
Provides an embeddable widget (GraphWidget) with the same interface as the matplotlib version.

This is the default renderer when OpenGL is available. Falls back to matplotlib in
headless environments or when NCROM_GRAPH_RENDERER=matplotlib is set.

Configuration:
- Set NCROM_GRAPH_RENDERER environment variable to 'matplotlib' or 'pyqtgraph'
- Or use AppSettings.set_graph_renderer()
"""

import numpy as np
from PySide6.QtWidgets import QVBoxLayout, QWidget, QSizePolicy
from PySide6.QtCore import Qt

import pyqtgraph as pg
import pyqtgraph.opengl as gl

from ..core.rom_definition import Table, TableType, RomDefinition, AxisType
from ..utils.colormap import get_colormap


class GraphWidget(QWidget):
    """
    Embeddable graph widget for table data visualization using pyqtgraph

    Features:
    - 3D surface plot for 3D tables (OpenGL accelerated)
    - 2D plot for 2D tables
    - Interactive rotation with mouse
    - Highlight selected cells
    - Color gradient matching table viewer
    """

    def __init__(self, parent=None):
        """Initialize graph widget without data (set later with set_data)"""
        super().__init__(parent)

        self.table = None
        self.data = None
        self.rom_definition = None
        self.selected_cells = []

        # Current view state (for 3D)
        self._view_widget = None
        self._mesh_item = None
        self._is_3d = False
        self._saved_camera_params = None

        # Set up layout
        self._layout = QVBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self._layout)

        # Set size policy to expand
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumWidth(300)

        # Enable focus for keyboard handling
        self.setFocusPolicy(Qt.StrongFocus)

    def set_data(self, table: Table, data: dict, rom_definition: RomDefinition = None,
                 selected_cells: list = None):
        """
        Set or update the graph data

        Args:
            table: Table definition
            data: Table data dictionary
            rom_definition: ROM definition containing scalings
            selected_cells: List of (row, col) tuples for selected cells
        """
        self.table = table
        self.data = data
        self.rom_definition = rom_definition
        self.selected_cells = selected_cells or []
        self._plot_data()

    def update_selection(self, selected_cells: list):
        """Update the selected cells and redraw the graph"""
        self.selected_cells = selected_cells
        if self.table is not None:
            self._plot_data()

    def update_data(self, data: dict):
        """Update just the data values (e.g., after cell edit)"""
        self.data = data
        if self.table is not None:
            self._plot_data()

    def _plot_data(self):
        """Plot the table data based on table type"""
        if self.table is None or self.data is None:
            return

        # Save camera state before recreating (for 3D)
        self._save_camera_state()

        # Clear existing view widget
        self._clear_view()

        if self.table.type == TableType.THREE_D:
            self._plot_3d()
            self._is_3d = True
        elif self.table.type == TableType.TWO_D:
            self._plot_2d()
            self._is_3d = False
        else:
            self._plot_1d()
            self._is_3d = False

    def _clear_view(self):
        """Clear the current view widget"""
        if self._view_widget is not None:
            self._layout.removeWidget(self._view_widget)
            self._view_widget.deleteLater()
            self._view_widget = None
            self._mesh_item = None

    def _save_camera_state(self):
        """Save current camera state for 3D view"""
        if self._is_3d and self._view_widget is not None:
            try:
                # Get camera parameters from GLViewWidget
                self._saved_camera_params = self._view_widget.cameraParams()
            except Exception:
                pass

    def _restore_camera_state(self):
        """Restore camera state for 3D view"""
        if self._saved_camera_params is not None and self._view_widget is not None:
            try:
                self._view_widget.setCameraParams(**self._saved_camera_params)
            except Exception:
                pass

    def _plot_3d(self):
        """Plot 3D table as surface using GLMeshItem"""
        # Create GL view widget
        self._view_widget = gl.GLViewWidget()
        self._layout.addWidget(self._view_widget)

        values = self.data['values']
        x_axis = self.data.get('x_axis')
        y_axis = self.data.get('y_axis')

        rows, cols = values.shape

        # Build vertex grid for mesh
        if x_axis is not None and y_axis is not None:
            X, Y = np.meshgrid(x_axis, y_axis)
        else:
            X, Y = np.meshgrid(np.arange(cols), np.arange(rows))

        # Normalize X and Y for better visualization
        x_min, x_max = X.min(), X.max()
        y_min, y_max = Y.min(), Y.max()
        z_min, z_max = values.min(), values.max()

        # Scale to reasonable ranges
        x_range = x_max - x_min if x_max != x_min else 1
        y_range = y_max - y_min if y_max != y_min else 1
        z_range = z_max - z_min if z_max != z_min else 1

        # Normalize coordinates to roughly -10 to 10 range
        scale = 10.0
        X_norm = (X - x_min) / x_range * scale * 2 - scale
        Y_norm = (Y - y_min) / y_range * scale * 2 - scale
        Z_norm = (values - z_min) / z_range * scale * 2 - scale

        # Build vertices: flatten X, Y, Z arrays
        verts = np.zeros((rows * cols, 3))
        for i in range(rows):
            for j in range(cols):
                idx = i * cols + j
                verts[idx] = [X_norm[i, j], Y_norm[i, j], Z_norm[i, j]]

        # Build faces (triangles) and colors
        # Each cell becomes 2 triangles
        faces = []
        colors = []

        # Calculate color ratios
        if z_max == z_min:
            ratios = np.full_like(values, 0.5)
        else:
            ratios = (values - z_min) / (z_max - z_min)

        for i in range(rows - 1):
            for j in range(cols - 1):
                # Vertex indices for this cell
                v00 = i * cols + j
                v01 = i * cols + (j + 1)
                v10 = (i + 1) * cols + j
                v11 = (i + 1) * cols + (j + 1)

                # Two triangles per cell
                faces.append([v00, v10, v01])  # Lower-left triangle
                faces.append([v01, v10, v11])  # Upper-right triangle

                # Color for this cell (average of corners or just use [i,j])
                rgba = self._get_cell_color(i, j, ratios)
                colors.append(rgba)
                colors.append(rgba)

        faces = np.array(faces)
        colors = np.array(colors)

        # Create mesh item
        self._mesh_item = gl.GLMeshItem(
            vertexes=verts,
            faces=faces,
            faceColors=colors,
            smooth=False,
            drawEdges=True,
            edgeColor=(0.5, 0.5, 0.5, 1.0)
        )
        self._view_widget.addItem(self._mesh_item)

        # Add axis grid for reference
        grid = gl.GLGridItem()
        grid.setSize(scale * 2.5, scale * 2.5)
        grid.translate(0, 0, -scale)
        self._view_widget.addItem(grid)

        # Set initial camera position
        if self._saved_camera_params is not None:
            self._restore_camera_state()
        else:
            self._view_widget.setCameraPosition(distance=40, elevation=30, azimuth=45)

        # Connect click to grab focus
        self._view_widget.mousePressEvent = self._on_view_click

    def _get_cell_color(self, row: int, col: int, ratios: np.ndarray):
        """Get color for a cell, considering selection"""
        # Check if this cell is selected
        if (row, col) in self.selected_cells:
            return (0.0, 0.5, 1.0, 1.0)  # Blue for selected

        # Get color from colormap
        ratio = ratios[row, col]
        return get_colormap().ratio_to_rgba_float(ratio)

    def _plot_2d(self):
        """Plot 2D table as line"""
        # Create standard plot widget
        self._view_widget = pg.PlotWidget()
        self._view_widget.setBackground('w')
        self._layout.addWidget(self._view_widget)

        values = self.data['values']
        y_axis = self.data.get('y_axis')

        if y_axis is not None:
            x = y_axis
        else:
            x = np.arange(len(values))

        # Calculate colors for segments
        min_val = np.min(values)
        max_val = np.max(values)
        if max_val == min_val:
            ratios = np.full_like(values, 0.5)
        else:
            ratios = (values - min_val) / (max_val - min_val)

        # Plot colored line segments
        for i in range(len(x) - 1):
            rgba = get_colormap().ratio_to_rgba_float(ratios[i])
            color = pg.mkColor(int(rgba[0]*255), int(rgba[1]*255), int(rgba[2]*255))
            pen = pg.mkPen(color=color, width=2)
            self._view_widget.plot(x[i:i+2], values[i:i+2], pen=pen)

        # Highlight selected cells with blue scatter
        if self.selected_cells:
            selected_x = []
            selected_y = []
            for row, col in self.selected_cells:
                if row < len(values):
                    selected_x.append(x[row])
                    selected_y.append(values[row])
            if selected_x:
                scatter = pg.ScatterPlotItem(
                    x=selected_x, y=selected_y,
                    size=12, pen=pg.mkPen(None),
                    brush=pg.mkBrush(0, 128, 255, 200)
                )
                self._view_widget.addItem(scatter)

        # Labels
        y_label = self._get_axis_label(AxisType.Y_AXIS) if y_axis is not None else 'Index'
        self._view_widget.setLabel('bottom', y_label)
        self._view_widget.setLabel('left', 'Value')
        self._view_widget.showGrid(x=True, y=True, alpha=0.3)

        # Connect click to grab focus
        self._view_widget.mousePressEvent = self._on_view_click

    def _plot_1d(self):
        """Plot 1D table as single bar"""
        self._view_widget = pg.PlotWidget()
        self._view_widget.setBackground('w')
        self._layout.addWidget(self._view_widget)

        values = self.data['values']

        # Get color for bar
        rgba = get_colormap().ratio_to_rgba_float(0.5)
        color = pg.mkColor(int(rgba[0]*255), int(rgba[1]*255), int(rgba[2]*255))

        # Create bar graph
        bar = pg.BarGraphItem(x=[0], height=[values[0]], width=0.5, brush=color)
        self._view_widget.addItem(bar)

        self._view_widget.setLabel('left', 'Value')
        self._view_widget.getAxis('bottom').setTicks([])

        # Connect click to grab focus
        self._view_widget.mousePressEvent = self._on_view_click

    def _on_view_click(self, event):
        """Handle view click - grab focus for keyboard events"""
        self.setFocus()
        # Call original handler
        if self._is_3d:
            gl.GLViewWidget.mousePressEvent(self._view_widget, event)
        else:
            pg.PlotWidget.mousePressEvent(self._view_widget, event)

    def _get_axis_label(self, axis_type: AxisType) -> str:
        """Get axis label with unit"""
        axis_table = self.table.get_axis(axis_type)
        if not axis_table:
            return "X Axis" if axis_type == AxisType.X_AXIS else "Y Axis"

        name = axis_table.name
        unit = ""

        if self.rom_definition and axis_table.scaling:
            scaling = self.rom_definition.get_scaling(axis_table.scaling)
            if scaling and scaling.units:
                unit = scaling.units

        if unit:
            return f"{name} ({unit})"
        return name

    def keyPressEvent(self, event):
        """Handle key presses for graph rotation and zoom"""
        if not self._is_3d or self._view_widget is None:
            super().keyPressEvent(event)
            return

        # Get current camera params
        params = self._view_widget.cameraParams()
        elev = params.get('elevation', 30)
        azim = params.get('azimuth', 45)
        dist = params.get('distance', 40)
        rotation_step = 10
        zoom_factor = 1.1

        if event.key() == Qt.Key_Left:
            azim -= rotation_step
            self._view_widget.setCameraPosition(azimuth=azim)
        elif event.key() == Qt.Key_Right:
            azim += rotation_step
            self._view_widget.setCameraPosition(azimuth=azim)
        elif event.key() == Qt.Key_Up:
            elev = min(90, elev + rotation_step)
            self._view_widget.setCameraPosition(elevation=elev)
        elif event.key() == Qt.Key_Down:
            elev = max(-90, elev - rotation_step)
            self._view_widget.setCameraPosition(elevation=elev)
        elif event.key() in (Qt.Key_Plus, Qt.Key_Equal):
            self._view_widget.setCameraPosition(distance=dist / zoom_factor)
        elif event.key() == Qt.Key_Minus:
            self._view_widget.setCameraPosition(distance=dist * zoom_factor)
        else:
            super().keyPressEvent(event)
