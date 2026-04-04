"""
Shared error-handling helpers for UI code.

Provides a single ``handle_rom_operation_error`` function used by both
``main.py`` and the project mixin to log errors and show message boxes.
"""

from PySide6.QtWidgets import QMessageBox

from src.utils.logging_config import get_logger

logger = get_logger(__name__)


def handle_rom_operation_error(parent, operation: str, exception: Exception):
    """
    Handle common ROM operation errors with consistent logging and user feedback.

    Args:
        parent: Parent widget for message box
        operation: Description of operation that failed (e.g., "open ROM file")
        exception: The exception that was raised
    """
    error_msg = f"Failed to {operation}:\n{str(exception)}"
    logger.error(error_msg.replace("\n", " "))
    QMessageBox.critical(parent, "Error", error_msg)
