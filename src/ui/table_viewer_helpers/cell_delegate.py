"""
Cell Delegate for Modified Cell Borders

Renders a thin gray border around cells that have been modified during the session.
"""

from PySide6.QtWidgets import QStyledItemDelegate
from PySide6.QtCore import Qt
from PySide6.QtGui import QPen, QColor


class ModifiedCellDelegate(QStyledItemDelegate):
    """Delegate that draws gray borders around modified cells"""

    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer

    def paint(self, painter, option, index):
        """Paint cell with modified border if applicable"""
        # Let the default delegate paint the cell first
        super().paint(painter, option, index)

        # Check if this cell is modified
        if self.viewer.is_cell_modified(index.row(), index.column()):
            # Draw a thin gray border around the cell
            painter.save()
            pen = QPen(QColor(100, 100, 100), 2)  # 2px gray border
            pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen)
            # Draw rectangle slightly inset to avoid clipping
            rect = option.rect.adjusted(1, 1, -1, -1)
            painter.drawRect(rect)
            painter.restore()
