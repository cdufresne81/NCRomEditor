"""
History Viewer Widget

Displays commit history with ability to view details.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QLabel,
    QTableWidget, QTableWidgetItem, QGroupBox, QHeaderView,
    QDialog, QPushButton, QLineEdit
)
from PySide6.QtCore import Qt, Signal
from typing import Optional, List

from ..core.version_models import Commit
from ..core.project_manager import ProjectManager


class HistoryViewer(QDialog):
    """Dialog for browsing commit history"""

    commit_selected = Signal(str)  # Emits commit ID

    def __init__(self, project_manager: ProjectManager, parent=None):
        super().__init__(parent)
        self.project_manager = project_manager
        self.setWindowTitle("Commit History")
        self.setMinimumSize(900, 600)
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Search bar
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter commits by message...")
        self.search_edit.textChanged.connect(self._filter_commits)
        search_layout.addWidget(self.search_edit)
        layout.addLayout(search_layout)

        # Splitter for list and details
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Left: Commit list
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_widget.setLayout(left_layout)

        left_layout.addWidget(QLabel("<b>Commits</b> (newest first)"))

        self.commit_tree = QTreeWidget()
        self.commit_tree.setHeaderLabels(["Message", "Date", "Tables"])
        self.commit_tree.setColumnWidth(0, 250)
        self.commit_tree.setColumnWidth(1, 120)
        self.commit_tree.setRootIsDecorated(False)
        self.commit_tree.itemClicked.connect(self._on_commit_selected)
        left_layout.addWidget(self.commit_tree)

        splitter.addWidget(left_widget)

        # Right: Commit details
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_widget.setLayout(right_layout)

        right_layout.addWidget(QLabel("<b>Commit Details</b>"))

        # Details area
        self.details_widget = CommitDetailsWidget()
        right_layout.addWidget(self.details_widget)

        splitter.addWidget(right_widget)
        splitter.setSizes([350, 550])

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)

    def refresh(self):
        """Reload commit history"""
        self.commit_tree.clear()
        self.details_widget.clear()

        commits = self.project_manager.get_recent_commits(100)

        for commit in commits:
            self._add_commit_item(commit)

    def _add_commit_item(self, commit: Commit):
        """Add a commit to the tree"""
        date_str = commit.timestamp.strftime("%Y-%m-%d %H:%M")

        tables_str = ", ".join(commit.tables_modified[:2])
        if len(commit.tables_modified) > 2:
            tables_str += f" +{len(commit.tables_modified) - 2}"
        elif not commit.tables_modified:
            tables_str = "(initial)"

        # Truncate message for display
        msg = commit.message.split('\n')[0]  # First line only
        if len(msg) > 40:
            msg = msg[:37] + "..."

        item = QTreeWidgetItem([msg, date_str, tables_str])
        item.setData(0, Qt.UserRole, commit.id)
        item.setToolTip(0, commit.message)

        # Style initial commit differently
        if commit.parent_id is None:
            item.setForeground(0, Qt.gray)

        self.commit_tree.addTopLevelItem(item)

    def _filter_commits(self, text: str):
        """Filter commits by search text"""
        text = text.lower()

        for i in range(self.commit_tree.topLevelItemCount()):
            item = self.commit_tree.topLevelItem(i)
            commit_id = item.data(0, Qt.UserRole)
            commit = self.project_manager.get_commit(commit_id)

            if commit:
                visible = (
                    text in commit.message.lower() or
                    any(text in t.lower() for t in commit.tables_modified)
                )
                item.setHidden(not visible)
            else:
                item.setHidden(True)

    def _on_commit_selected(self, item, column):
        """Handle commit selection"""
        commit_id = item.data(0, Qt.UserRole)
        commit = self.project_manager.get_commit(commit_id)
        if commit:
            self.details_widget.show_commit(commit)
            self.commit_selected.emit(commit_id)


class CommitDetailsWidget(QWidget):
    """Shows detailed information about a single commit"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Commit info
        info_group = QGroupBox("Information")
        info_layout = QVBoxLayout()
        info_group.setLayout(info_layout)

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(140)
        info_layout.addWidget(self.info_text)

        layout.addWidget(info_group)

        # Changes table
        changes_group = QGroupBox("Cell Changes")
        changes_layout = QVBoxLayout()
        changes_group.setLayout(changes_layout)

        self.changes_table = QTableWidget()
        self.changes_table.setColumnCount(5)
        self.changes_table.setHorizontalHeaderLabels([
            "Table", "Row", "Col", "Old Value", "New Value"
        ])
        self.changes_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.changes_table.setAlternatingRowColors(True)
        changes_layout.addWidget(self.changes_table)

        layout.addWidget(changes_group)

        # Stats label
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.stats_label)

    def show_commit(self, commit: Commit):
        """Display commit details"""
        # Show info
        snapshot_str = "Yes" if commit.has_snapshot else "No"
        info = (
            f"<b>Commit:</b> {commit.id}<br>"
            f"<b>Date:</b> {commit.timestamp.strftime('%Y-%m-%d %H:%M:%S')}<br>"
            f"<b>Author:</b> {commit.author}<br>"
            f"<b>Snapshot:</b> {snapshot_str}<br>"
            f"<hr>"
            f"<b>Message:</b><br>{commit.message}"
        )
        self.info_text.setHtml(info)

        # Show changes
        self.changes_table.setRowCount(0)

        total_cells = 0
        row = 0
        for table_change in commit.changes:
            for cell in table_change.cell_changes:
                self.changes_table.insertRow(row)
                self.changes_table.setItem(row, 0, QTableWidgetItem(cell.table_name))
                self.changes_table.setItem(row, 1, QTableWidgetItem(str(cell.row)))
                self.changes_table.setItem(row, 2, QTableWidgetItem(str(cell.col)))

                old_item = QTableWidgetItem(f"{cell.old_value:.4g}")
                new_item = QTableWidgetItem(f"{cell.new_value:.4g}")

                # Color code changes
                if cell.new_value > cell.old_value:
                    new_item.setForeground(Qt.darkGreen)
                elif cell.new_value < cell.old_value:
                    new_item.setForeground(Qt.darkRed)

                self.changes_table.setItem(row, 3, old_item)
                self.changes_table.setItem(row, 4, new_item)
                row += 1
                total_cells += 1

        # Update stats
        self.stats_label.setText(
            f"{len(commit.tables_modified)} table(s), {total_cells} cell change(s)"
        )

    def clear(self):
        """Clear the details view"""
        self.info_text.clear()
        self.changes_table.setRowCount(0)
        self.stats_label.setText("")


class HistoryPanel(QWidget):
    """Compact history panel for embedding in main window (optional)"""

    commit_selected = Signal(str)

    def __init__(self, project_manager: ProjectManager, parent=None):
        super().__init__(parent)
        self.project_manager = project_manager
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Header
        header = QLabel("<b>Recent Commits</b>")
        layout.addWidget(header)

        # Commit list
        self.commit_list = QTreeWidget()
        self.commit_list.setHeaderHidden(True)
        self.commit_list.setRootIsDecorated(False)
        self.commit_list.itemClicked.connect(self._on_commit_clicked)
        layout.addWidget(self.commit_list)

    def refresh(self):
        """Refresh the commit list"""
        self.commit_list.clear()

        commits = self.project_manager.get_recent_commits(10)

        for commit in commits:
            date_str = commit.timestamp.strftime("%m/%d %H:%M")
            msg = commit.message.split('\n')[0][:30]

            item = QTreeWidgetItem([f"{date_str} - {msg}"])
            item.setData(0, Qt.UserRole, commit.id)
            item.setToolTip(0, commit.message)
            self.commit_list.addTopLevelItem(item)

    def _on_commit_clicked(self, item, column):
        """Handle commit click"""
        commit_id = item.data(0, Qt.UserRole)
        self.commit_selected.emit(commit_id)
