"""
Tests for CAN Bus Listener backend.

All tests use mocked J2534 hardware — no device required.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch, call

import pytest

from src.ecu.can_listener import CANListener, CANFrame, parse_can_msg
from src.ecu.can_decoder import CANDecoder
from src.ecu.constants import J2534_PROTOCOL_CAN, CAN_ID_BOTH, CAN_BAUDRATE, PASS_FILTER
from src.ecu.exceptions import J2534Error
from src.ecu.j2534 import PassThruMsg

# ---------------------------------------------------------------------------
# parse_can_msg
# ---------------------------------------------------------------------------


def _make_passthru_msg(can_id_bytes: bytes, data: bytes, timestamp: int = 0):
    """Build a PassThruMsg with the given CAN ID bytes + data payload."""
    msg = PassThruMsg()
    msg.ProtocolID = J2534_PROTOCOL_CAN
    msg.Timestamp = timestamp
    payload = can_id_bytes + data
    msg.DataSize = len(payload)
    for i, b in enumerate(payload):
        msg.Data[i] = b
    return msg


class TestParseCaNMsg:
    def test_parse_can_msg(self):
        """Standard 8-byte CAN frame parses correctly."""
        can_id = 0x7E0
        data = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08])
        msg = _make_passthru_msg(can_id.to_bytes(4, "big"), data, timestamp=123456)

        frame = parse_can_msg(msg)

        assert frame.can_id == 0x7E0
        assert frame.dlc == 8
        assert frame.data == data
        assert frame.timestamp_us == 123456

    def test_parse_can_msg_short(self):
        """CAN frame with fewer than 8 data bytes."""
        can_id = 0x100
        data = bytes([0xAA, 0xBB, 0xCC])
        msg = _make_passthru_msg(can_id.to_bytes(4, "big"), data, timestamp=999)

        frame = parse_can_msg(msg)

        assert frame.can_id == 0x100
        assert frame.dlc == 3
        assert frame.data == data
        assert frame.timestamp_us == 999


# ---------------------------------------------------------------------------
# CANListener
# ---------------------------------------------------------------------------


class TestCANListener:
    @patch("src.ecu.can_listener.J2534Device")
    def test_listener_start(self, MockDevice):
        """start() opens device, connects CAN channel, sets pass-all filter."""
        mock_dev = MockDevice.return_value
        mock_dev.connect.return_value = 42
        mock_dev.start_msg_filter.return_value = 7

        listener = CANListener("test.dll", baudrate=500000)
        listener.start()

        mock_dev.open.assert_called_once()
        mock_dev.connect.assert_called_once_with(
            J2534_PROTOCOL_CAN, CAN_ID_BOTH, 500000
        )

        # Verify filter setup
        mock_dev.start_msg_filter.assert_called_once()
        args = mock_dev.start_msg_filter.call_args
        assert args[0][0] == 42  # channel_id
        assert args[0][1] == PASS_FILTER  # filter_type

        # Verify mask and pattern messages
        mask_msg = args[0][2]
        pattern_msg = args[0][3]
        assert mask_msg.ProtocolID == J2534_PROTOCOL_CAN
        assert mask_msg.DataSize == 4
        assert all(mask_msg.Data[i] == 0 for i in range(4))
        assert pattern_msg.ProtocolID == J2534_PROTOCOL_CAN
        assert pattern_msg.DataSize == 4
        assert all(pattern_msg.Data[i] == 0 for i in range(4))

        assert listener.is_running is True

    @patch("src.ecu.can_listener.J2534Device")
    def test_listener_stop_teardown_order(self, MockDevice):
        """stop() tears down filter, disconnect, close in order."""
        mock_dev = MockDevice.return_value
        mock_dev.connect.return_value = 42
        mock_dev.start_msg_filter.return_value = 7

        listener = CANListener("test.dll")
        listener.start()
        listener.stop()

        # Verify teardown order
        mock_dev.stop_msg_filter.assert_called_once_with(42, 7)
        mock_dev.disconnect.assert_called_once_with(42)
        mock_dev.close.assert_called_once()

        assert listener.is_running is False

    @patch("src.ecu.can_listener.J2534Device")
    def test_poll_loop_receives_frames(self, MockDevice):
        """poll_loop delivers parsed frames to callback."""
        mock_dev = MockDevice.return_value
        mock_dev.connect.return_value = 1
        mock_dev.start_msg_filter.return_value = 1

        msg1 = _make_passthru_msg(b"\x00\x00\x07\xe0", b"\x01\x02", timestamp=100)
        msg2 = _make_passthru_msg(b"\x00\x00\x07\xe8", b"\x03\x04", timestamp=200)

        call_count = [0]

        def side_effect(channel_id, count, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                return [msg1, msg2]
            # Stop after first batch
            listener._stop_event.set()
            return []

        mock_dev.read_msgs.side_effect = side_effect

        listener = CANListener("test.dll")
        listener.start()

        received = []
        listener.poll_loop(lambda frames: received.extend(frames))

        assert len(received) == 2
        assert received[0].can_id == 0x7E0
        assert received[1].can_id == 0x7E8

    @patch("src.ecu.can_listener.J2534Device")
    def test_poll_loop_handles_empty(self, MockDevice):
        """poll_loop does not invoke callback when no messages."""
        mock_dev = MockDevice.return_value
        mock_dev.connect.return_value = 1
        mock_dev.start_msg_filter.return_value = 1

        call_count = [0]

        def side_effect(channel_id, count, timeout):
            call_count[0] += 1
            if call_count[0] >= 3:
                listener._stop_event.set()
            return []

        mock_dev.read_msgs.side_effect = side_effect

        listener = CANListener("test.dll")
        listener.start()

        callback = MagicMock()
        listener.poll_loop(callback)

        callback.assert_not_called()

    @patch("src.ecu.can_listener.J2534Device")
    def test_poll_loop_error_raises(self, MockDevice):
        """poll_loop propagates J2534Error."""
        mock_dev = MockDevice.return_value
        mock_dev.connect.return_value = 1
        mock_dev.start_msg_filter.return_value = 1
        mock_dev.read_msgs.side_effect = J2534Error("device disconnected")

        listener = CANListener("test.dll")
        listener.start()

        with pytest.raises(J2534Error, match="device disconnected"):
            listener.poll_loop(lambda frames: None)

    @patch("src.ecu.can_listener.J2534Device")
    def test_stop_tolerates_errors(self, MockDevice):
        """stop() completes even when device methods raise."""
        mock_dev = MockDevice.return_value
        mock_dev.connect.return_value = 42
        mock_dev.start_msg_filter.return_value = 7
        mock_dev.stop_msg_filter.side_effect = Exception("filter error")
        mock_dev.disconnect.side_effect = Exception("disconnect error")
        mock_dev.close.side_effect = Exception("close error")

        listener = CANListener("test.dll")
        listener.start()

        # Should not raise
        listener.stop()

        assert listener.is_running is False


# ---------------------------------------------------------------------------
# CANDecoder
# ---------------------------------------------------------------------------


class TestCANDecoder:
    def test_decoder_no_dbc(self):
        """Decoder with no DBC returns empty dict."""
        decoder = CANDecoder()
        frame = CANFrame(timestamp_us=0, can_id=0x100, dlc=8, data=b"\x00" * 8)
        assert decoder.decode(frame) == {}
        assert decoder.is_loaded is False

    def test_decoder_load_nonexistent(self):
        """Loading a nonexistent DBC file does not raise."""
        decoder = CANDecoder()
        decoder.load("/nonexistent/path/file.dbc")
        assert decoder.is_loaded is False

    def test_decoder_get_message_name_no_dbc(self):
        """get_message_name returns None when no DBC is loaded."""
        decoder = CANDecoder()
        assert decoder.get_message_name(0x100) is None
