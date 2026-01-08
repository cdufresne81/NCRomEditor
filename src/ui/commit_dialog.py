"""
Commit Dialog

Dialog for entering commit message when saving changes.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QGroupBox, QCheckBox
)
from PySide6.QtCore import Qt
from typing import List

from ..core.version_models import TableChanges


class CommitDialog(QDialog):
    """Dialog for committing changes with a message"""

    def __init__(self, pending_changes: List[TableChanges], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Commit Changes")
        self.setMinimumSize(500, 400)

        self.pending_changes = pending_changes
        self.commit_message = ""
        self.create_snapshot = False

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Summary label
        total_cells = sum(len(tc.cell_changes) for tc in self.pending_changes)
        summary_label = QLabel(
            f"<b>{len(self.pending_changes)} table(s)</b> modified with "
            f"<b>{total_cells} cell change(s)</b>"
        )
        layout.addWidget(summary_label)

        # Modified tables tree
        tables_group = QGroupBox("Changes to Commit")
        tables_layout = QVBoxLayout()
        tables_group.setLayout(tables_layout)

        self.tables_tree = QTreeWidget()
        self.tables_tree.setHeaderLabels(["Table / Change", "Details"])
        self.tables_tree.setColumnWidth(0, 250)
        self.tables_tree.setRootIsDecorated(True)

        # Populate tree with changes
        for table_change in self.pending_changes:
            table_item = QTreeWidgetItem([
                table_change.table_name,
                f"{len(table_change.cell_changes)} cell(s)"
            ])
            table_item.setFlags(table_item.flags() | Qt.ItemIsUserCheckable)
            table_item.setCheckState(0, Qt.Checked)

            # Add cell changes as children
            for cell in table_change.cell_changes:
                cell_item = QTreeWidgetItem([
                    f"[{cell.row}, {cell.col}]",
                    f"{cell.old_value:.4g} -> {cell.new_value:.4g}"
                ])
                table_item.addChild(cell_item)

            self.tables_tree.addTopLevelItem(table_item)

        self.tables_tree.expandAll()
        tables_layout.addWidget(self.tables_tree)

        layout.addWidget(tables_group)

        # Commit message
        msg_group = QGroupBox("Commit Message")
        msg_layout = QVBoxLayout()
        msg_group.setLayout(msg_layout)

        self.message_edit = QTextEdit()
        self.message_edit.setPlaceholderText(
            "Describe what you changed and why...\n\n"
            "Examples:\n"
            "- Increased fuel enrichment at high RPM for safer WOT\n"
            "- Adjusted timing for 91 octane fuel\n"
            "- Disabled closed-loop fuel correction"
        )
        self.message_edit.setMaximumHeight(120)
        msg_layout.addWidget(self.message_edit)

        layout.addWidget(msg_group)

        # Options
        options_layout = QHBoxLayout()
        self.snapshot_checkbox = QCheckBox("Create ROM snapshot (for reverting later)")
        self.snapshot_checkbox.setToolTip(
            "Creates a full copy of the ROM at this commit point.\n"
            "Useful for major changes you might want to revert to."
        )
        options_layout.addWidget(self.snapshot_checkbox)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.button(QDialogButtonBox.Ok).setText("Commit")
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_accept(self):
        """Validate and accept"""
        message = self.message_edit.toPlainText().strip()
        if not message:
            self.message_edit.setFocus()
            self.message_edit.setStyleSheet("border: 2px solid red;")
            return

        self.commit_message = message
        self.create_snapshot = self.snapshot_checkbox.isChecked()
        self.accept()

    def get_commit_message(self) -> str:
        """Get the commit message"""
        return self.commit_message

    def get_create_snapshot(self) -> bool:
        """Get whether to create a snapshot"""
        return self.create_snapshot

    def get_selected_tables(self) -> List[str]:
        """Get list of selected table names"""
        selected = []
        for i in range(self.tables_tree.topLevelItemCount()):
            item = self.tables_tree.topLevelItem(i)
            if item.checkState(0) == Qt.Checked:
                selected.append(item.text(0))
        return selected


class QuickCommitDialog(QDialog):
    """Simplified commit dialog for quick saves"""

    def __init__(self, tables_modified: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quick Commit")
        self.setMinimumSize(400, 200)

        self.tables_modified = tables_modified
        self.commit_message = ""

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Tables summary
        tables_str = ", ".join(self.tables_modified[:3])
        if len(self.tables_modified) > 3:
            tables_str += f" (+{len(self.tables_modified) - 3} more)"

        summary = QLabel(f"Modified: <b>{tables_str}</b>")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        # Commit message
        layout.addWidget(QLabel("Commit Message:"))
        self.message_edit = QTextEdit()
        self.message_edit.setPlaceholderText("What did you change?")
        self.message_edit.setMaximumHeight(80)
        layout.addWidget(self.message_edit)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.button(QDialogButtonBox.Ok).setText("Commit")
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_accept(self):
        """Validate and accept"""
        message = self.message_edit.toPlainText().strip()
        if not message:
            self.message_edit.setFocus()
            return

        self.commit_message = message
        self.accept()

    def get_commit_message(self) -> str:
        return self.commit_message
