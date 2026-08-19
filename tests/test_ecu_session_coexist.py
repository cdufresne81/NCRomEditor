"""Unit tests for the WiCAN no-reboot coexistence-port capability probe
(``ECUSession._try_open_coexist_port``).

The probe opens the always-on dedicated SLCAN port, version-pings it, and only
adopts it when the firmware rev is new enough (``COEXIST_MIN_FW_REV``). Every
failure mode must degrade to ``None`` so the caller falls back to the proven
reboot-switch path — the probe must NEVER raise.
"""

import socket
from unittest.mock import MagicMock, patch

import pytest

from src.ecu.session import ECUSession, ECUSessionState
from src.ecu.constants import (
    WICAN_DEDICATED_SLCAN_PORT,
    COEXIST_MIN_FW_REV,
    COEXIST_PROBE_TIMEOUT_MS,
)
from src.ecu.wican_transport import WiCANError

WICAN_CFG = {
    "kind": "wican",
    "host": "192.168.1.169",
    "port": 35000,
    "auto_config": True,
}


@pytest.fixture
def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _session(_qapp):
    return ECUSession(adapter_config=dict(WICAN_CFG))


def _fake_probe(marker):
    """A probe transport whose version_ping yields ``marker`` bytes."""
    probe = MagicMock()
    probe.port = WICAN_DEDICATED_SLCAN_PORT
    probe.version_ping.return_value = marker
    return probe


class TestCoexistProbe:
    def test_coexist_firmware_adopted(self, _qapp):
        probe = _fake_probe(b"NCFRv%d" % COEXIST_MIN_FW_REV)
        with patch(
            "src.ecu.transport.create_ecu_transport", return_value=probe
        ) as mock_create:
            result = _session(_qapp)._try_open_coexist_port()

        assert result is probe  # adopted — handed back OPEN
        probe.open.assert_called_once()
        probe.close.assert_not_called()
        # Probed the dedicated port with the short capability timeout.
        cfg = mock_create.call_args.args[0]
        assert cfg["port"] == WICAN_DEDICATED_SLCAN_PORT
        assert cfg["connect_timeout_ms"] == COEXIST_PROBE_TIMEOUT_MS

    def test_newer_firmware_adopted(self, _qapp):
        probe = _fake_probe(b"NCFRv%d" % (COEXIST_MIN_FW_REV + 3))
        with patch("src.ecu.transport.create_ecu_transport", return_value=probe):
            assert _session(_qapp)._try_open_coexist_port() is probe

    def test_old_firmware_rejected_and_closed(self, _qapp):
        # A pre-coexistence build (e.g. the fastwrite NCFRv5) answers the port but
        # is below the threshold → reject and close, fall back to reboot path.
        probe = _fake_probe(b"NCFRv%d" % (COEXIST_MIN_FW_REV - 1))
        with patch("src.ecu.transport.create_ecu_transport", return_value=probe):
            assert _session(_qapp)._try_open_coexist_port() is None
        probe.close.assert_called_once()

    def test_no_marker_rejected_and_closed(self, _qapp):
        probe = _fake_probe(None)  # port open but no NCFRv marker
        with patch("src.ecu.transport.create_ecu_transport", return_value=probe):
            assert _session(_qapp)._try_open_coexist_port() is None
        probe.close.assert_called_once()

    def test_connect_refused_returns_none(self, _qapp):
        # Old firmware has no dedicated port → TCP connect refused. Must not raise.
        probe = MagicMock()
        probe.open.side_effect = WiCANError("connection refused")
        with patch("src.ecu.transport.create_ecu_transport", return_value=probe):
            assert _session(_qapp)._try_open_coexist_port() is None
        probe.close.assert_called_once()

    def test_create_transport_raises_returns_none(self, _qapp):
        with patch(
            "src.ecu.transport.create_ecu_transport",
            side_effect=RuntimeError("boom"),
        ):
            # No probe was created, nothing to close — just a clean None.
            assert _session(_qapp)._try_open_coexist_port() is None


# ---------------------------------------------------------------------------
# Issue #92 — an INCONCLUSIVE probe must never rewrite the device's stored mode.
#
# The probe today collapses every failure into ``None``, so the caller takes the
# legacy path and writes ``protocol: slcan`` into stored config. That is correct
# when the failure PROVES old firmware (nothing listens on 35001 -> the OS
# refuses the connect), and wrong when it proves nothing (a timeout on a device
# that is otherwise perfectly reachable). The second case can strand the device
# in Bench SLCAN with the datalogger dead.
#
# The rule these tests pin down:
#   conclusive failure  -> legacy path, mode write allowed  (test_..._guard)
#   inconclusive failure -> refuse to write, fail loudly    (the rest)
# ---------------------------------------------------------------------------


def _timeout_error():
    """A probe failure shaped like a real connect timeout (proves nothing)."""
    err = WiCANError("Failed to connect to 192.168.1.169:35001: timed out")
    err.__cause__ = socket.timeout("timed out")
    return err


def _refused_error():
    """A probe failure shaped like a real TCP refusal (proves old firmware)."""
    err = WiCANError("Failed to connect to 192.168.1.169:35001: refused")
    err.__cause__ = ConnectionRefusedError(111, "Connection refused")
    return err


def _connect_with_probe_error(_qapp, err):
    """Drive a full connect where ONLY the coexist probe fails with ``err``.

    Port 35000 (the legacy data port) still opens fine, so the device is
    "otherwise reachable" — exactly the situation where a mode write is unsafe.
    Returns (session, configurator_mock, connection_lost_messages).
    """
    legacy = MagicMock()

    def _by_port(cfg, *a, **kw):
        if cfg.get("port") == WICAN_DEDICATED_SLCAN_PORT:
            probe = MagicMock()
            probe.open.side_effect = err
            return probe
        return legacy

    with (
        patch("src.ecu.wican_config.WiCANConfigurator") as MockCfg,
        patch("src.ecu.wican_config.WiCANDatalogClient"),
        patch("src.ecu.transport.create_ecu_transport", side_effect=_by_port),
        patch("src.ecu.protocol.UDSConnection"),
    ):
        inst = MockCfg.return_value
        inst.read_recovery.return_value = None
        inst.current_protocol.return_value = "poll_log"

        session = ECUSession(adapter_config=dict(WICAN_CFG))
        lost = []
        session.connection_lost.connect(lost.append)
        session.connect_ecu()

    return session, inst, lost


class TestProbeInconclusivePolicy:
    """#92: a probe that proves nothing must not reboot the device into slcan."""

    def test_timeout_does_not_write_slcan(self, _qapp):
        # The coexist port timed out but port 35000 is fine — the device is up,
        # we simply could not confirm its capability. Writing the mode here is
        # what strands it, so the connect must fail instead.
        session, inst, lost = _connect_with_probe_error(_qapp, _timeout_error())

        inst.set_protocol.assert_not_called()
        inst.write_recovery.assert_not_called()

    def test_timeout_fails_loudly(self, _qapp):
        # Refusing must be visible. A silent no-op would look like a hung app.
        session, inst, lost = _connect_with_probe_error(_qapp, _timeout_error())

        assert session.state == ECUSessionState.DISCONNECTED
        assert len(lost) == 1, f"expected one connection_lost, got {lost!r}"

    def test_refused_still_takes_legacy_path_guard(self, _qapp):
        """GUARD — green before AND after the fix.

        A refused TCP connect proves nothing is listening on 35001, i.e. genuine
        pre-coexistence firmware. Those users have no other way in, so the mode
        write must keep working for them. This pins the other side of the rule so
        the fix cannot 'protect' us by breaking old hardware.
        """
        session, inst, lost = _connect_with_probe_error(_qapp, _refused_error())

        inst.write_recovery.assert_called_once_with("poll_log")
        inst.set_protocol.assert_called_once_with("slcan")
        assert session.state == ECUSessionState.CONNECTED
