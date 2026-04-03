"""
CAN Signal Decoder

Decodes raw CAN frames into human-readable signal values using a DBC database file.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import cantools
    import cantools.database
except ImportError:
    cantools = None  # type: ignore[assignment]


class CANDecoder:
    """Decodes CAN frames using a DBC database."""

    def __init__(self, dbc_path: str | None = None):
        self._db = None
        if dbc_path is not None:
            self.load(dbc_path)

    def load(self, dbc_path: str) -> None:
        """Load or reload a DBC database file.

        Logs a warning and leaves ``_db`` as None if the file cannot be loaded.
        """
        if cantools is None:
            logger.warning("cantools is not installed; DBC decoding disabled")
            self._db = None
            return

        try:
            self._db = cantools.database.load_file(dbc_path)
            logger.info("Loaded DBC file: %s", dbc_path)
        except FileNotFoundError:
            logger.warning("DBC file not found: %s", dbc_path)
            self._db = None
        except Exception as exc:
            logger.warning("Failed to load DBC file %s: %s", dbc_path, exc)
            self._db = None

    def decode(self, frame) -> dict[str, str]:
        """Decode a CAN frame into signal name/value strings.

        Args:
            frame: A CANFrame with ``can_id`` and ``data`` attributes.

        Returns:
            Dict mapping signal names to formatted value strings
            (e.g. ``{"EngineRPM": "3200.00 rpm"}``).  Returns an empty
            dict if no DBC is loaded or the frame is unknown.
        """
        if self._db is None:
            return {}

        try:
            msg = self._db.get_message_by_frame_id(frame.can_id)
            decoded = msg.decode(frame.data)
            result = {}
            for name, value in decoded.items():
                signal = msg.get_signal_by_name(name)
                unit = signal.unit if signal and signal.unit else ""
                if isinstance(value, (int, float)):
                    result[name] = f"{value:.2f} {unit}".strip()
                else:
                    result[name] = f"{value} {unit}".strip()
            return result
        except KeyError:
            return {}
        except Exception:
            return {}

    def get_message_name(self, can_id: int) -> str | None:
        """Look up the message name for a CAN ID.

        Returns None if no DBC is loaded or the ID is unknown.
        """
        if self._db is None:
            return None
        try:
            return self._db.get_message_by_frame_id(can_id).name
        except KeyError:
            return None

    @property
    def is_loaded(self) -> bool:
        """Return True if a DBC database is loaded."""
        return self._db is not None
