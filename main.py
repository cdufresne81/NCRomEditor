#!/usr/bin/env python3
"""
NC ROM Editor - Main Application Entry Point

An open-source ROM editor for NC Miata ECUs
"""

import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QLabel
)
from PySide6.QtCore import Qt

from src.core.definition_parser import load_definition
from src.core.rom_reader import RomReader
from src.core.rom_detector import RomDetector
from src.ui.table_browser import TableBrowser
from src.ui.table_viewer import TableViewer


class MainWindow(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NC ROM Editor")
        self.setGeometry(100, 100, 1400, 900)

        # ROM data
        self.current_rom_path = None
        self.rom_definition = None
        self.rom_reader = None

        # ROM detector for automatic XML matching
        try:
            self.rom_detector = RomDetector("metadata")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Initialization Error",
                f"Failed to initialize ROM detector:\n{str(e)}"
            )
            self.rom_detector = None

        # Initialize UI
        self.init_ui()
        self.init_menu()

    def init_ui(self):
        """Initialize the user interface"""
        # Central widget with splitter
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QHBoxLayout()
        central_widget.setLayout(layout)

        # Splitter for browser and viewer
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Table browser on the left
        self.table_browser = TableBrowser()
        self.table_browser.table_selected.connect(self.on_table_selected)
        splitter.addWidget(self.table_browser)

        # Table viewer on the right
        self.table_viewer = TableViewer()
        splitter.addWidget(self.table_viewer)

        # Set initial splitter sizes (30% browser, 70% viewer)
        splitter.setSizes([400, 1000])

    def init_menu(self):
        """Initialize the menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        open_action = file_menu.addAction("Open ROM...")
        open_action.triggered.connect(self.open_rom)

        save_action = file_menu.addAction("Save ROM")
        save_action.triggered.connect(self.save_rom)

        save_as_action = file_menu.addAction("Save ROM As...")
        save_as_action.triggered.connect(self.save_rom_as)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        # Help menu
        help_menu = menubar.addMenu("Help")

        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self.show_about)

    def load_definition(self, definition_path: str):
        """
        Load ROM definition file

        Args:
            definition_path: Path to XML definition file
        """
        try:
            self.statusBar().showMessage("Loading ROM definition...")
            self.rom_definition = load_definition(definition_path)

            # Populate table browser
            self.table_browser.load_definition(self.rom_definition)

            self.statusBar().showMessage(
                f"Loaded definition: {self.rom_definition.romid.xmlid} "
                f"({len(self.rom_definition.tables)} tables)"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Loading Definition",
                f"Failed to load ROM definition:\n{str(e)}"
            )
            self.statusBar().showMessage("Failed to load definition")

    def open_rom(self):
        """Open a ROM file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open ROM File",
            "",
            "ROM Files (*.bin *.rom);;All Files (*)"
        )

        if file_path:
            try:
                self.statusBar().showMessage(f"Detecting ROM ID...")

                # Detect ROM ID and find matching XML definition
                if not self.rom_detector:
                    QMessageBox.critical(
                        self,
                        "Error",
                        "ROM detector not initialized. Cannot auto-detect ROM type."
                    )
                    return

                rom_id, xml_path = self.rom_detector.detect_rom_id(file_path)

                if not rom_id or not xml_path:
                    QMessageBox.critical(
                        self,
                        "Unknown ROM",
                        "Could not identify ROM type. No matching definition found.\n\n"
                        "Supported ROM IDs:\n" +
                        "\n".join([f"  - {info['xmlid']} ({info['make']} {info['model']})"
                                   for info in self.rom_detector.get_definitions_summary()])
                    )
                    return

                # Load the matching definition
                self.statusBar().showMessage(f"Detected ROM ID: {rom_id}, loading definition...")
                self.load_definition(xml_path)

                # Create ROM reader
                self.statusBar().showMessage(f"Loading ROM data...")
                self.rom_reader = RomReader(file_path, self.rom_definition)

                # Verify ROM ID (should always pass now, but kept as sanity check)
                if not self.rom_reader.verify_rom_id():
                    QMessageBox.warning(
                        self,
                        "ROM ID Warning",
                        f"ROM ID verification failed. This should not happen after auto-detection.\n"
                        f"Expected: {self.rom_definition.romid.internalidstring}\n"
                        f"This may indicate a detection bug."
                    )

                self.current_rom_path = file_path
                file_name = Path(file_path).name
                self.setWindowTitle(f"NC ROM Editor - {file_name} ({rom_id})")
                self.statusBar().showMessage(
                    f"Loaded: {file_name} - {self.rom_definition.romid.xmlid} "
                    f"({len(self.rom_definition.tables)} tables)"
                )

            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to open ROM file:\n{str(e)}"
                )
                self.rom_reader = None

    def save_rom(self):
        """Save the current ROM file"""
        if not self.rom_reader:
            QMessageBox.warning(self, "No ROM", "No ROM file is currently loaded.")
            return

        if self.current_rom_path:
            self.save_rom_to_path(self.current_rom_path)

    def save_rom_as(self):
        """Save the ROM to a new file"""
        if not self.rom_reader:
            QMessageBox.warning(self, "No ROM", "No ROM file is currently loaded.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save ROM File As",
            "",
            "ROM Files (*.bin);;All Files (*)"
        )

        if file_path:
            self.save_rom_to_path(file_path)

    def save_rom_to_path(self, file_path):
        """Save ROM data to specified path"""
        try:
            self.rom_reader.save_rom(file_path)
            self.statusBar().showMessage(f"Saved: {file_path}")
            QMessageBox.information(
                self,
                "Success",
                f"ROM saved successfully to:\n{file_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save ROM file:\n{str(e)}"
            )

    def on_table_selected(self, table):
        """Handle table selection from browser"""
        if not self.rom_reader:
            QMessageBox.warning(
                self,
                "No ROM Loaded",
                "Please open a ROM file first."
            )
            return

        try:
            # Read table data from ROM
            self.statusBar().showMessage(f"Loading table: {table.name}...")
            data = self.rom_reader.read_table_data(table)

            if data:
                # Display in viewer
                self.table_viewer.display_table(table, data)
                self.statusBar().showMessage(f"Viewing: {table.name}")
            else:
                QMessageBox.warning(
                    self,
                    "Error",
                    f"Failed to read table data for: {table.name}"
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load table:\n{str(e)}"
            )

    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About NC ROM Editor",
            "NC ROM Editor v0.1.0\n\n"
            "An open-source ROM editor for NC Miata ECUs\n\n"
            "Designed to replace EcuFlash for ROM editing tasks.\n"
            "Works with RomDrop for ECU flashing."
        )


def main():
    """Application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("NC ROM Editor")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
