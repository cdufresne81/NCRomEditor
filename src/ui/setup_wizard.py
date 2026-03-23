"""
Setup Wizard

First-run wizard to configure essential application settings.
Asks for the ROM metadata XML directory.
"""

from pathlib import Path
from PySide6.QtWidgets import (
    QWizard,
    QWizardPage,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QMessageBox,
)

from ..utils.settings import get_settings


class SetupWizard(QWizard):
    """First-run setup wizard for configuring metadata paths."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NC Flash - Setup")
        self.setMinimumSize(500, 300)
        self.setModal(True)
        self.setWizardStyle(QWizard.ModernStyle)
        self.settings = get_settings()

        self.addPage(MetadataPage())

    def accept(self):
        """Save paths on wizard completion."""
        page = self.page(0)
        metadata_path = page.metadata_edit.text().strip()
        if metadata_path:
            self.settings.set_metadata_directory(metadata_path)
        super().accept()


class MetadataPage(QWizardPage):
    """Select ROM metadata XML directory."""

    def __init__(self):
        super().__init__()
        self.setTitle("ROM Metadata Directory")
        self.setSubTitle(
            "Select the directory containing ROM metadata XML files.\n"
            "These files define table layouts for each calibration ID."
        )

        layout = QVBoxLayout()
        self.setLayout(layout)

        layout.addSpacing(10)

        path_layout = QHBoxLayout()
        self.metadata_edit = QLineEdit()
        self.metadata_edit.setPlaceholderText("Path to ROM metadata XML files...")
        self.metadata_edit.textChanged.connect(self._on_path_changed)
        path_layout.addWidget(self.metadata_edit)

        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse)
        path_layout.addWidget(browse_button)

        layout.addLayout(path_layout)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.status_label)

        layout.addStretch()

    def _browse(self):
        current_path = self.metadata_edit.text() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Metadata Directory",
            current_path,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if directory:
            self.metadata_edit.setText(directory)

    def _on_path_changed(self, path):
        if not path:
            self.status_label.setText("")
            self.completeChanged.emit()
            return

        p = Path(path)
        if not p.exists() or not p.is_dir():
            self.status_label.setText(
                "<span style='color: #cc4444;'>&#10008; Directory not found</span>"
            )
        else:
            xml_count = len(list(p.glob("*.xml")))
            if xml_count > 0:
                self.status_label.setText(
                    f"<span style='color: #44aa44;'>&#10004; {xml_count} XML files found</span>"
                )
            else:
                self.status_label.setText(
                    "<span style='color: #cc8800;'>&#9888; No XML files in directory</span>"
                )
        self.completeChanged.emit()

    def isComplete(self):
        path = self.metadata_edit.text().strip()
        if not path:
            return False
        p = Path(path)
        return p.exists() and p.is_dir() and len(list(p.glob("*.xml"))) > 0

    def validatePage(self):
        path = self.metadata_edit.text().strip()
        if not path:
            QMessageBox.warning(
                self, "Path Required", "Please select a metadata directory."
            )
            return False

        p = Path(path)
        if not p.exists() or not p.is_dir():
            QMessageBox.warning(
                self,
                "Directory Not Found",
                f"The directory does not exist:\n{path}",
            )
            return False

        if not list(p.glob("*.xml")):
            response = QMessageBox.question(
                self,
                "No XML Files",
                f"No XML files found in:\n{path}\n\nUse this directory anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return response == QMessageBox.Yes

        return True
