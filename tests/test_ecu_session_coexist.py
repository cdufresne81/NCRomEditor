"""Unit tests for the WiCAN no-reboot coexistence-port capability probe
(``ECUSession._try_open_coexist_port``).

The probe opens the always-on dedicated SLCAN port, version-pings it, and only
adopts it when the firmware rev is new enough (``COEXIST_MIN_FW_REV``). It must
NEVER raise — but it must report WHY it failed, because only CONCLUSIVE evidence
of old firmware (a refused connect, or a real marker below the threshold) may
authorise the caller to reboot the device into bench mode. An inconclusive
failure that took the legacy path is what stranded devices in #92.
"""

import socket
from unittest.mock import MagicMock, patch

import pytest

from src.ecu.session import ECUSession, ECUSessionState, ProbeVerdict
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
            result, verdict = _session(_qapp)._try_open_coexist_port()

        assert result is probe  # adopted -- handed back OPEN
        assert verdict is ProbeVerdict.COEXIST
        probe.open.assert_called_once()
        probe.close.assert_not_called()
        # Probed the dedicated port with the short capability timeout.
        cfg = mock_create.call_args.args[0]
        assert cfg["port"] == WICAN_DEDICATED_SLCAN_PORT
        assert cfg["connect_timeout_ms"] == COEXIST_PROBE_TIMEOUT_MS

    def test_newer_firmware_adopted(self, _qapp):
        probe = _fake_probe(b"NCFRv%d" % (COEXIST_MIN_FW_REV + 3))
        with patch("src.ecu.transport.create_ecu_transport", return_value=probe):
            result, verdict = _session(_qapp)._try_open_coexist_port()
        assert result is probe
        assert verdict is ProbeVerdict.COEXIST

    def test_old_firmware_rejected_and_closed(self, _qapp):
        # A pre-coexistence build (e.g. the fastwrite NCFRv5) answers the port but
        # is below the threshold. A REAL marker is conclusive evidence, so the
        # legacy reboot path -- and its mode write -- stays correct here.
        probe = _fake_probe(b"NCFRv%d" % (COEXIST_MIN_FW_REV - 1))
        with patch("src.ecu.transport.create_ecu_transport", return_value=probe):
            result, verdict = _session(_qapp)._try_open_coexist_port()
        assert result is None
        assert verdict is ProbeVerdict.OLD_FIRMWARE
        probe.close.assert_called_once()

    def test_no_marker_is_inconclusive_not_old_firmware(self, _qapp):
        # The port ACCEPTED the connection and then said nothing. Only the
        # coexistence listener ever binds that port, so silence is far more
        # likely to be a slow link than old firmware -- and it must not be
        # treated as permission to rewrite the device's mode (#92).
        probe = _fake_probe(None)
        with patch("src.ecu.transport.create_ecu_transport", return_value=probe):
            result, verdict = _session(_qapp)._try_open_coexist_port()
        assert result is None
        assert verdict is ProbeVerdict.INCONCLUSIVE
        # Silence earns one longer retry before we give up on it.
        assert probe.version_ping.call_count == 2
        probe.close.assert_called_once()

    def test_connect_refused_is_conclusive_old_firmware(self, _qapp):
        # Old firmware has no dedicated port -> the OS refuses the connect.
        # Nothing is listening, which IS proof. Note the cause chain, not the
        # message, is what the implementation inspects.
        probe = MagicMock()
        err = WiCANError("connection refused")
        err.__cause__ = ConnectionRefusedError(111, "Connection refused")
        probe.open.side_effect = err
        with patch("src.ecu.transport.create_ecu_transport", return_value=probe):
            result, verdict = _session(_qapp)._try_open_coexist_port()
        assert result is None
        assert verdict is ProbeVerdict.OLD_FIRMWARE
        probe.close.assert_called_once()

    def test_create_transport_raises_is_inconclusive(self, _qapp):
        with patch(
            "src.ecu.transport.create_ecu_transport",
            side_effect=RuntimeError("boom"),
        ):
            # No probe was created, nothing to close. An unexpected error proves
            # nothing about the firmware, so it must not license a mode write.
            result, verdict = _session(_qapp)._try_open_coexist_port()
        assert result is None
        assert verdict is ProbeVerdict.INCONCLUSIVE


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
        # Explicit: this models TODAY's fleet, which has no /host_caps endpoint.
        # Without this the guard would receive a truthy MagicMock and fall into
        # the fallback branch by accident of mock semantics rather than by test
        # design -- and the branch this test claims to cover would be untested.
        inst.host_caps.return_value = None

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


class TestInconclusiveGuardUsesHostCaps:
    """#92: what the guard does with /host_caps, including the WRITE branch.

    These branches decide whether the tool may reboot a device into bench mode.
    They currently never execute anywhere -- the endpoint does not exist in
    firmware yet -- so without these tests an inverted comparison here would
    re-create the original defect the day that firmware ships, silently.
    """

    @staticmethod
    def _guard(_qapp, caps, stored="poll_log"):
        cfg = MagicMock()
        cfg.host_caps.return_value = caps
        cfg.current_protocol.return_value = stored
        return _session(_qapp)._guard_inconclusive_probe(cfg), cfg

    def test_caps_confirming_coexistence_refuses_the_write(self, _qapp):
        # The device SAYS it has no-reboot firmware, but its port did not answer.
        # There is nothing to connect to and no justification for a mode write.
        from src.ecu.exceptions import CoexistProbeInconclusive

        with pytest.raises(CoexistProbeInconclusive):
            self._guard(_qapp, {"ncfr_rev": COEXIST_MIN_FW_REV, "protocol": "poll_log"})

    def test_caps_reporting_old_firmware_allows_the_write(self, _qapp):
        # A rev BELOW the threshold is conclusive: this really is a build with
        # no dedicated port, so the legacy reboot path is the correct answer.
        # Returning (rather than raising) is what authorises the write.
        result, cfg = self._guard(
            _qapp, {"ncfr_rev": COEXIST_MIN_FW_REV - 1, "protocol": "poll_log"}
        )
        assert result is None
        cfg.current_protocol.assert_not_called()  # settled without the config blob

    def test_caps_absent_falls_back_to_the_stored_protocol(self, _qapp):
        # Today's fleet: no /host_caps. Must fall back, not treat the missing
        # endpoint as evidence of anything.
        from src.ecu.exceptions import CoexistProbeInconclusive

        with pytest.raises(CoexistProbeInconclusive):
            self._guard(_qapp, None, stored="poll_log")

    def test_caps_absent_and_already_slcan_allows_the_write_free_path(self, _qapp):
        # Already in slcan: the legacy path performs NO write, so continuing is
        # safe -- and refusing here would lock the user out of a device this
        # tool may itself have stranded earlier.
        result, _cfg = self._guard(_qapp, None, stored="slcan")
        assert result is None

    def test_non_integer_rev_is_treated_as_absent(self, _qapp):
        # A firmware that answers with "6" instead of 6 must not be trusted as a
        # number; fall back rather than guess.
        from src.ecu.exceptions import CoexistProbeInconclusive

        with pytest.raises(CoexistProbeInconclusive):
            self._guard(_qapp, {"ncfr_rev": "6"}, stored="poll_log")

    def test_unreachable_over_http_too_refuses(self, _qapp):
        from src.ecu.exceptions import CoexistProbeInconclusive
        from src.ecu.wican_config import WiCANConfigError

        cfg = MagicMock()
        cfg.host_caps.return_value = None
        cfg.current_protocol.side_effect = WiCANConfigError("cannot reach")
        with pytest.raises(CoexistProbeInconclusive):
            _session(_qapp)._guard_inconclusive_probe(cfg)
