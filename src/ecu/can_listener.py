"""
CAN Bus Listener

Opens a raw CAN channel (J2534 Protocol ID 5) on the Tactrix OpenPort 2.0
and polls for frames. Designed to run in a background thread with frame
batches delivered via callback.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from .constants import (
    J2534_PROTOCOL_CAN,
    CAN_ID_BOTH,
    CAN_BAUDRATE,
    PASS_FILTER,
)
from .exceptions import J2534Error
from .j2534 import J2534Device, PassThruMsg

logger = logging.getLogger(__name__)


@dataclass
class CANFrame:
    """A single decoded CAN bus frame."""

    timestamp_us: int
    can_id: int
    dlc: int
    data: bytes


def parse_can_msg(msg: PassThruMsg) -> CANFrame:
    """Extract a CANFrame from a raw J2534 PassThruMsg.

    The first 4 bytes of the message data contain the CAN ID (big-endian).
    The remaining bytes are the CAN payload.
    """
    raw = bytes(msg.Data[: msg.DataSize])
    can_id = int.from_bytes(raw[:4], "big")
    data = raw[4:]
    return CANFrame(
        timestamp_us=msg.Timestamp,
        can_id=can_id,
        dlc=len(data),
        data=data,
    )


class CANListener:
    """Manages a raw CAN channel lifecycle and polling loop."""

    def __init__(self, dll_path: str, baudrate: int = CAN_BAUDRATE):
        self._dll_path = dll_path
        self._baudrate = baudrate
        self._device: J2534Device | None = None
        self._channel_id: int | None = None
        self._filter_id: int | None = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self) -> None:
        """Open the device, connect a raw CAN channel, and set a pass-all filter."""
        self._device = J2534Device(self._dll_path)
        self._device.open()

        self._channel_id = self._device.connect(
            J2534_PROTOCOL_CAN, CAN_ID_BOTH, self._baudrate
        )

        # Build pass-all filter: mask and pattern with all-zero data
        mask_msg = PassThruMsg()
        mask_msg.ProtocolID = J2534_PROTOCOL_CAN
        mask_msg.DataSize = 4
        # Data bytes are already zero-initialized by ctypes

        pattern_msg = PassThruMsg()
        pattern_msg.ProtocolID = J2534_PROTOCOL_CAN
        pattern_msg.DataSize = 4

        self._filter_id = self._device.start_msg_filter(
            self._channel_id, PASS_FILTER, mask_msg, pattern_msg
        )

        self._running = True
        logger.info(
            "CAN listener started (channel=%d, filter=%d, baud=%d)",
            self._channel_id,
            self._filter_id,
            self._baudrate,
        )

    def poll_loop(self, frame_callback: Callable[[list[CANFrame]], None]) -> None:
        """Poll for CAN frames until stopped.

        Args:
            frame_callback: Called with a list of parsed CANFrame objects
                whenever messages are received.

        Raises:
            J2534Error: If a device communication error occurs.
        """
        while not self._stop_event.is_set():
            try:
                msgs = self._device.read_msgs(self._channel_id, 16, 50)
            except J2534Error:
                self._stop_event.set()
                self._running = False
                raise

            if msgs:
                frames = [parse_can_msg(m) for m in msgs]
                frame_callback(frames)

    def stop(self) -> None:
        """Signal the poll loop to stop and tear down J2534 resources.

        Error-tolerant: each teardown step is wrapped in try/except so
        cleanup proceeds even if the device is unresponsive.
        """
        self._stop_event.set()
        self._running = False

        if self._filter_id is not None and self._device and self._channel_id:
            try:
                self._device.stop_msg_filter(self._channel_id, self._filter_id)
            except Exception:
                pass
            self._filter_id = None

        if self._channel_id is not None and self._device:
            try:
                self._device.disconnect(self._channel_id)
            except Exception:
                pass
            self._channel_id = None

        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

        logger.info("CAN listener stopped")

    @property
    def is_running(self) -> bool:
        """Return True if the listener is actively polling."""
        return self._running
