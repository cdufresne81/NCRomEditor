"""
Patch ROM Dialog

Wizard-style dialog to apply a RomDrop XOR patch to a stock OEM ROM.
"""

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QGroupBox,
    QMessageBox,
    QLineEdit,
)
from src.ecu.rom_utils import patch_rom, validate_rom_size, get_cal_id
from src.ecu.exceptions import ROMValidationError

logger = logging.getLogger(__name__)


class PatchDialog(QDialog):
    """Dialog for applying a RomDrop patch to a stock ROM."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Apply Patch to Stock ROM")
        self.setMinimumWidth(550)

        self._stock_data = None
        self._patch_data = None
        self._result = None

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # --- Stock ROM ---
        stock_group = QGroupBox("1. Select Stock OEM ROM")
        stock_layout = QVBoxLayout()
        stock_group.setLayout(stock_layout)

        file_row = QHBoxLayout()
        self._stock_path_edit = QLineEdit()
        self._stock_path_edit.setReadOnly(True)
        self._stock_path_edit.setPlaceholderText("No file selected")
        file_row.addWidget(self._stock_path_edit)

        browse_stock = QPushButton("Browse...")
        browse_stock.clicked.connect(self._browse_stock)
        file_row.addWidget(browse_stock)
        stock_layout.addLayout(file_row)

        self._stock_info = QLabel("")
        self._stock_info.setStyleSheet("color: gray; font-size: 10px;")
        stock_layout.addWidget(self._stock_info)

        layout.addWidget(stock_group)

        # --- Patch file ---
        patch_group = QGroupBox("2. Select Patch File")
        patch_layout = QVBoxLayout()
        patch_group.setLayout(patch_layout)

        file_row2 = QHBoxLayout()
        self._patch_path_edit = QLineEdit()
        self._patch_path_edit.setReadOnly(True)
        self._patch_path_edit.setPlaceholderText("No file selected")
        file_row2.addWidget(self._patch_path_edit)

        browse_patch = QPushButton("Browse...")
        browse_patch.clicked.connect(self._browse_patch)
        file_row2.addWidget(browse_patch)
        patch_layout.addLayout(file_row2)

        self._patch_info = QLabel("")
        self._patch_info.setStyleSheet("color: gray; font-size: 10px;")
        patch_layout.addWidget(self._patch_info)

        layout.addWidget(patch_group)

        # --- Result ---
        result_group = QGroupBox("3. Result")
        result_layout = QFormLayout()
        result_group.setLayout(result_layout)

        self._result_cal_id = QLabel("-")
        self._result_crc_status = QLabel("-")
        self._result_warnings = QLabel("")
        self._result_warnings.setWordWrap(True)
        self._result_output = QLineEdit()
        self._result_output.setReadOnly(True)

        result_layout.addRow("Cal ID:", self._result_cal_id)
        result_layout.addRow("CRC Verification:", self._result_crc_status)
        result_layout.addRow("", self._result_warnings)
        result_layout.addRow("Output file:", self._result_output)

        layout.addWidget(result_group)

        # --- Buttons ---
        button_row = QHBoxLayout()
        button_row.addStretch()

        self._apply_button = QPushButton("Apply Patch")
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._apply_patch)
        button_row.addWidget(self._apply_button)

        self._save_button = QPushButton("Save")
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._save_result)
        button_row.addWidget(self._save_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)

    def _browse_stock(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Stock OEM ROM",
            "",
            "ROM Files (*.bin);;All Files (*)",
        )
        if not path:
            return

        data = Path(path).read_bytes()
        if not validate_rom_size(data):
            QMessageBox.warning(
                self, "Invalid ROM", f"File must be exactly 1 MB, got {len(data):,} bytes."
            )
            return

        try:
            cal_id = get_cal_id(data)
        except ROMValidationError as e:
            QMessageBox.warning(self, "Invalid ROM", str(e))
            return

        self._stock_data = data
        self._stock_path_edit.setText(path)
        self._stock_info.setText(f"Cal ID: {cal_id.decode('ascii', errors='replace')}  |  Size: 1 MB")
        self._stock_info.setStyleSheet("color: green; font-size: 10px;")

        self._clear_result()
        self._update_apply_button()

    def _browse_patch(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Patch File",
            "",
            "Patch Files (*.patch);;All Files (*)",
        )
        if not path:
            return

        data = Path(path).read_bytes()
        if not validate_rom_size(data):
            QMessageBox.warning(
                self, "Invalid Patch", f"Patch file must be exactly 1 MB, got {len(data):,} bytes."
            )
            return

        if data[0:1] != b"L":
            QMessageBox.warning(
                self, "Invalid Patch", "Patch file does not have a valid header (first byte must be 'L')."
            )
            return

        self._patch_data = data
        self._patch_path_edit.setText(path)
        self._patch_info.setText("Valid patch file  |  Size: 1 MB")
        self._patch_info.setStyleSheet("color: green; font-size: 10px;")

        self._clear_result()
        self._update_apply_button()

    def _update_apply_button(self):
        self._apply_button.setEnabled(
            self._stock_data is not None and self._patch_data is not None
        )

    def _clear_result(self):
        self._result = None
        self._result_cal_id.setText("-")
        self._result_crc_status.setText("-")
        self._result_crc_status.setStyleSheet("")
        self._result_warnings.setText("")
        self._result_output.setText("")
        self._save_button.setEnabled(False)

    def _apply_patch(self):
        try:
            result = patch_rom(self._stock_data, self._patch_data)
        except ROMValidationError as e:
            QMessageBox.critical(self, "Patch Failed", str(e))
            return

        self._result = result

        cal_id_str = bytes(result.cal_id).decode("ascii", errors="replace")
        self._result_cal_id.setText(cal_id_str)

        if result.crc_verified:
            self._result_crc_status.setText("Verified")
            self._result_crc_status.setStyleSheet("color: green; font-weight: bold;")
        else:
            self._result_crc_status.setText("Unverified")
            self._result_crc_status.setStyleSheet("color: orange; font-weight: bold;")

        if result.crc_warnings:
            self._result_warnings.setText("\n".join(result.crc_warnings))
            self._result_warnings.setStyleSheet("color: orange; font-size: 10px;")
        else:
            self._result_warnings.setText("")

        # Default output path: same directory as stock ROM
        stock_dir = Path(self._stock_path_edit.text()).parent
        output_name = f"{cal_id_str}_Rev_{result.rom_id}.bin"
        self._result_output.setText(str(stock_dir / output_name))

        self._save_button.setEnabled(True)
        logger.info(f"Patch applied: {cal_id_str} (CRC verified: {result.crc_verified})")

    def _save_result(self):
        output_path = self._result_output.text()
        if not output_path:
            return

        # Let user change the save location
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Patched ROM",
            output_path,
            "ROM Files (*.bin);;All Files (*)",
        )
        if not path:
            return

        try:
            Path(path).write_bytes(bytes(self._result.patched_rom))
            QMessageBox.information(
                self,
                "Patch Saved",
                f"Patched ROM saved to:\n{path}",
            )
            logger.info(f"Patched ROM saved: {path}")
        except OSError as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save file:\n{e}")
