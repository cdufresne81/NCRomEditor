"""
ECU Session Manager

Holds an ECU transport (J2534 device + ISO-TP channel, or a WiCAN SLCAN link)
open for the duration of a session. Operations reuse the open connection
instead of reconnecting each time.

No keepalive polling — the connection stays valid without it. Each UDS
operation sends its own Tester Present as needed. Connect verifies the ECU is
reachable with a single Tester Present, then holds the link open for
subsequent operations.

Two adapters share this one seam (the rest of the app is transport-agnostic):

  * **J2534** (default, wired) — opens a ``J2534Device``/ISO-TP channel. This
    path is byte-for-byte unchanged from the original implementation.
  * **WiCAN** (opt-in, wireless) — opens a ``WiCANTransport`` over SLCAN/TCP.
    If auto-config is on, the device's HTTP ``protocol`` is switched to
    ``slcan`` on the FIRST connect (a ~6 s reboot) and restored only on an
    explicit disconnect / app exit — NOT on the internal auto-reconnect after a
    read — so a single session never reboots the adapter more than once.
"""

import logging
import time
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal

from .constants import DEFAULT_J2534_DLL

logger = logging.getLogger(__name__)

#: Longer window for the ONE version-ping retry when the coexistence port
#: accepted the connection but stayed silent. A busy device or a lossy WiFi link
#: can eat the first window; a retry is far cheaper than wrongly concluding "old
#: firmware" and rebooting the adapter out of its datalogging mode (#92).
_COEXIST_PROBE_RETRY_MS = 3000


class ProbeVerdict(Enum):
    """What the coexistence-port probe actually established.

    The distinction that matters is CONCLUSIVE vs not: only conclusive evidence
    of pre-coexistence firmware may authorise writing the device's stored mode.
    """

    #: Coexistence firmware confirmed; use the dedicated port, no reboot.
    COEXIST = "coexist"
    #: Conclusively pre-coexistence: the port was refused, or a real NCFRv
    #: marker came back below the threshold. The legacy mode write is correct.
    OLD_FIRMWARE = "old_firmware"
    #: Proved nothing (timeout, reset, silence, unexpected error). Must NOT
    #: authorise a mode write.
    INCONCLUSIVE = "inconclusive"


def _is_connection_refused(exc: BaseException) -> bool:
    """True when ``exc`` was ultimately caused by a refused TCP connect.

    The transport wraps socket errors (``raise WiCANError(...) from exc``), so
    the real cause sits on ``__cause__``/``__context__`` rather than in the
    message. Matching on the exception type is reliable on both Windows
    (WSAECONNREFUSED maps to ConnectionRefusedError) and POSIX; matching on the
    text would not be.
    """
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ConnectionRefusedError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class ECUSessionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    BUSY = "busy"  # flash/read has acquired the session


class ECUSession(QObject):
    """
    Persistent ECU session over a J2534 or WiCAN transport.

    Holds the connection (device/channel/filter for J2534, or transport for
    WiCAN) open so that multiple UDS operations can reuse it without
    reconnecting each time.

    Usage:
        # J2534 (default — back-compatible positional form):
        session = ECUSession(dll_path)
        # WiCAN (opt-in):
        session = ECUSession(adapter_config={"kind": "wican", "host": ...})

        session.state_changed.connect(on_state_changed)
        session.connect_ecu()
        # ... operations use session.uds ...
        session.disconnect_ecu()
    """

    state_changed = Signal(str)  # ECUSessionState value
    connection_lost = Signal(str)  # error reason
    progress = Signal(str)  # human-readable connect-step message

    def __init__(
        self,
        dll_path: str = DEFAULT_J2534_DLL,
        parent: Optional[QObject] = None,
        *,
        adapter_config: Optional[dict] = None,
    ):
        super().__init__(parent)
        # Copy the relevant fields out of the config so the session never holds
        # a shared mutable dict (architecture rule).
        cfg = dict(adapter_config or {})
        self._adapter_kind = "wican" if cfg.get("kind") == "wican" else "j2534"
        self._dll_path = cfg.get("dll_path") or dll_path
        self._wican_host = cfg.get("host")
        self._wican_port = cfg.get("port")
        self._wican_auto_config = bool(cfg.get("auto_config", True))

        self._state = ECUSessionState.DISCONNECTED
        self._device = None
        self._channel_id = None
        self._filter_id = None
        self._uds = None

        # WiCAN-only state
        self._transport = None
        self._configurator = None
        self._slcan_prev_protocol = None  # original protocol to restore to
        self._slcan_switched = False  # True once we've switched this session
        # No-reboot coexistence (#36): the WHOLE-session bus reservation. On the
        # dedicated coexist port the datalogger owns the single CAN bus and eats the
        # ECU's UDS replies until the host reserves it, so we hold a refcounted
        # bus-claim+pause for the life of the session (acquired in _connect_wican,
        # released in _teardown_wican). The flash fence nests on this SAME client, so
        # there is exactly one bus owner. None unless connected via the coexist port.
        self._wican_datalog = None

    # --- Public API ---

    @property
    def state(self) -> ECUSessionState:
        return self._state

    @property
    def adapter_kind(self) -> str:
        """``"j2534"`` or ``"wican"`` — which transport this session drives."""
        return self._adapter_kind

    @property
    def is_connected(self) -> bool:
        return self._state in (ECUSessionState.CONNECTED, ECUSessionState.BUSY)

    @property
    def wican_host(self):
        """Address of the WiCAN adapter this session drives (``None`` for J2534).

        Public so callers can tell whether a given adapter is already in use --
        the start-up strand sweep needs it to avoid rebooting a device this app
        is talking to.
        """
        return self._wican_host if self._adapter_kind == "wican" else None

    @property
    def device(self):
        return self._device

    @property
    def channel_id(self):
        return self._channel_id

    @property
    def filter_id(self):
        return self._filter_id

    @property
    def uds(self):
        return self._uds

    @property
    def transport(self):
        """The open ``EcuTransport`` (WiCAN sessions only; ``None`` for J2534)."""
        return self._transport

    @property
    def wican_datalog(self):
        """The session's coexist datalog client holding the whole-session bus
        reservation, or ``None`` (J2534, legacy reboot path, or disconnected). The
        flash driver reuses THIS instance so its fence nests on the one bus owner."""
        return self._wican_datalog

    def connect_ecu(self):
        """
        Open the transport and verify the ECU responds with one Tester Present.

        Dispatches to the J2534 or WiCAN connect path by adapter kind. The
        connection remains open for subsequent operations.
        """
        if self._state != ECUSessionState.DISCONNECTED:
            return

        self._set_state(ECUSessionState.CONNECTING)
        try:
            if self._adapter_kind == "wican":
                self._connect_wican()
            else:
                self._connect_j2534()
            self._set_state(ECUSessionState.CONNECTED)
        except Exception as e:
            logger.error("ECU session connect failed: %s", e)
            # Restore the WiCAN protocol if we switched it before failing.
            self._teardown(restore_protocol=True)
            self._set_state(ECUSessionState.DISCONNECTED)
            self.connection_lost.emit(f"Connect failed: {e}")

    def _connect_j2534(self):
        """Open J2534 device, CAN channel, ISO-TP filter, verify ECU. Unchanged."""
        from .j2534 import J2534Device, setup_isotp_flow_control
        from .protocol import UDSConnection
        from .transport import J2534Transport
        from .constants import (
            J2534_PROTOCOL_ISO15765,
            CAN_BAUDRATE,
            ISO15765_BS,
            ISO15765_STMIN,
        )

        self._device = J2534Device(self._dll_path)
        self._device.open()

        self._channel_id = self._device.connect(
            J2534_PROTOCOL_ISO15765, 0, CAN_BAUDRATE
        )
        self._device.set_config(self._channel_id, {ISO15765_BS: 0, ISO15765_STMIN: 0})
        self._filter_id = setup_isotp_flow_control(self._device, self._channel_id)
        self._uds = UDSConnection(J2534Transport(self._device, self._channel_id))

        # Single Tester Present to verify ECU is alive
        self._uds.tester_present()
        logger.info("ECU session established (J2534)")

    def _connect_wican(self):
        """Open the WiCAN link, verify ECU.

        Prefers the **no-reboot dedicated SLCAN port** when the adapter runs
        coexistence firmware (capability-probed via ``version_ping``): that path
        skips the ``WiCANConfigurator`` protocol switch entirely (no ~6 s reboot)
        and leaves the datalogger undisturbed. Against stock/old firmware the
        probe fails and we fall back to the proven reboot-switch path — strictly
        non-breaking.
        """
        from .protocol import UDSConnection
        from .transport import create_ecu_transport
        from .wican_config import WiCANConfigurator, WiCANDatalogClient

        if not self._wican_host or not self._wican_port:
            raise ValueError("WiCAN adapter requires a host and port")

        # No-reboot coexistence (#36.C) crash recovery: if a prior run was hard-killed
        # mid-flash after pausing the datalogger, resume it now — UNLESS a flash is
        # currently active (a second NC Flash instance mid-flash; its own resume will
        # clear it). Cheap + soft-degrading: a no-op unless this host left a breadcrumb,
        # and any /datalog error is swallowed. MUST run before any flash leans on it.
        try:
            WiCANDatalogClient(self._wican_host).reconcile()
        except Exception as exc:  # never let recovery break a connect
            logger.debug("datalog reconcile at connect failed (non-fatal): %s", exc)

        # No-reboot path: coexistence firmware keeps an always-on dedicated SLCAN
        # port open, so flashing needs neither the protocol-switch reboot nor the
        # WiCANConfigurator. Probe for it first; ANY failure falls back below.
        if self._wican_auto_config and not self._slcan_switched:
            coexist, verdict = self._try_open_coexist_port()
            if coexist is not None:
                self._transport = coexist
                # Reserve the bus for the WHOLE session BEFORE the first UDS frame.
                # Without this the datalogger (poll_log) is the sole TWAI consumer and
                # swallows the ECU's reply, so Tester-Present — and every later DTC /
                # RAM-scan / flash op — would time out. Refcounted + soft-degrading; the
                # firmware dead-man reaper auto-resumes the logger if this host vanishes.
                self._wican_datalog = WiCANDatalogClient(self._wican_host)
                self._wican_datalog.acquire_bus()
                # Drain datalogger frames still in-flight when we took the bus.
                # acquire_bus() pauses poll_log, but Mode-01 PID responses already
                # on the wire keep arriving for a beat; without this they bleed into
                # the first TesterPresent receive and are mis-parsed (the benign but
                # noisy "unexpected response byte 0x41 for SID 0x3E" warnings). Flush
                # until the bus is quiet so the first UDS exchange starts clean.
                coexist.flush()
                self._uds = UDSConnection(coexist)
                self._uds.tester_present()
                logger.info(
                    "ECU session established (WiCAN no-reboot port %s:%s)",
                    self._wican_host,
                    coexist.port,
                )
                return
            # Not coexistence firmware — switch the adapter into SLCAN mode ONCE
            # per session (a ~6 s reboot). Restore only on a real disconnect.
            self._configurator = WiCANConfigurator(self._wican_host)
            if verdict is ProbeVerdict.INCONCLUSIVE:
                # The probe proved nothing. Writing the stored mode from here is
                # what strands devices (#92), so establish the right to do it or
                # abort — this raises unless the device is demonstrably old, or
                # is already in slcan (where the legacy path writes nothing).
                self._guard_inconclusive_probe(self._configurator)
            self.progress.emit("Switching adapter to SLCAN (~6 s reboot)…")
            self._slcan_prev_protocol = self._enter_slcan_durable(self._configurator)
            self._slcan_switched = True

        self.progress.emit("Opening WiCAN link…")
        self._transport = create_ecu_transport(
            {"kind": "wican", "host": self._wican_host, "port": self._wican_port}
        )
        self._transport.open()
        self._uds = UDSConnection(self._transport)

        # Single Tester Present to verify ECU is alive
        self._uds.tester_present()
        logger.info(
            "ECU session established (WiCAN %s:%s)", self._wican_host, self._wican_port
        )

    def _try_open_coexist_port(self):
        """Probe for no-reboot coexistence firmware and report WHY it decided.

        A coexistence build (firmware rev ``>= COEXIST_MIN_FW_REV``) keeps an
        always-on dedicated SLCAN TCP port that routes through the
        protocol-agnostic fast-read/write codecs, so the host can flash without
        the ~6 s protocol-switch reboot and without the ``WiCANConfigurator``.

        This used to collapse EVERY failure into "old firmware", which is only
        true for some of them. Writing the device's stored mode is a reboot that
        stops the datalogger, so it needs real evidence, not a shrug (#92):

          * ``OLD_FIRMWARE`` — the TCP connect was REFUSED (nothing is bound to
            the port; only coexistence firmware ever binds it), or a genuine
            ``NCFRv`` marker below the threshold came back. Conclusive.
          * ``COEXIST`` — a marker at/above the threshold. Transport handed back
            OPEN.
          * ``INCONCLUSIVE`` — a timeout, a reset, a silent port, an unexpected
            error. Proves nothing, so it must NOT authorise a mode write.

        Still never raises: it reports a verdict and lets the caller set policy.

        :returns: ``(open_transport_or_None, ProbeVerdict)``
        """
        from .transport import create_ecu_transport
        from .wican_sd_flash import _parse_fw_rev  # reuse the NCFRv<rev> parser
        from .constants import (
            WICAN_DEDICATED_SLCAN_PORT,
            COEXIST_MIN_FW_REV,
            COEXIST_PROBE_TIMEOUT_MS,
        )

        def _open(timeout_ms):
            transport = create_ecu_transport(
                {
                    "kind": "wican",
                    "host": self._wican_host,
                    "port": WICAN_DEDICATED_SLCAN_PORT,
                    "connect_timeout_ms": timeout_ms,
                }
            )
            try:
                transport.open()
            except Exception:
                # Close here or the half-open socket leaks: the caller only ever
                # sees the exception, never this transport, so this is the only
                # place that can clean it up. Matters doubly now that a failed
                # connect may be retried.
                try:
                    transport.close()
                except Exception:
                    pass
                raise
            return transport

        probe = None
        verdict = ProbeVerdict.INCONCLUSIVE
        t0 = time.monotonic()
        connected_at = None
        retry_note = None
        try:
            try:
                probe = _open(COEXIST_PROBE_TIMEOUT_MS)
            except Exception as first:
                if _is_connection_refused(first):
                    raise
                retry_at = time.monotonic()
                # A timed-out connect and a REFUSED one are the same event seen
                # through too short a window: measured on Windows, the RST for a
                # closed port takes ~2 s to surface, while the probe budget is
                # 1.5 s -- so a genuinely pre-coexistence device looks like a
                # network problem and would be wrongly refused. Retry once, long
                # enough for a refusal to land, purely to tell the two apart.
                # Only failing paths pay this; a healthy port connects in ~20 ms.
                try:
                    probe = _open(_COEXIST_PROBE_RETRY_MS)
                except Exception as second:
                    retry_note = (
                        f"attempt 1 unresolved in {COEXIST_PROBE_TIMEOUT_MS} ms; "
                        f"confirming retry -> "
                        f"{'refused' if _is_connection_refused(second) else 'still unresolved'}"
                        f" in {(time.monotonic() - retry_at) * 1000:.0f} ms"
                    )
                    raise
                retry_note = (
                    f"attempt 1 unresolved in {COEXIST_PROBE_TIMEOUT_MS} ms; "
                    f"confirming retry -> connected in "
                    f"{(time.monotonic() - retry_at) * 1000:.0f} ms"
                )
            connected_at = time.monotonic()
            marker = probe.version_ping(window_ms=COEXIST_PROBE_TIMEOUT_MS)
            if marker is None:
                # The port ACCEPTED us and then said nothing. Only the
                # coexistence listener binds this port, so silence here is far
                # more likely to be a slow link or a busy device than old
                # firmware. Give it one longer window before giving up.
                logger.info(
                    "WiCAN dedicated port accepted but stayed silent; retrying "
                    "the version ping with a longer window"
                )
                marker = probe.version_ping(window_ms=_COEXIST_PROBE_RETRY_MS)
            rev = _parse_fw_rev(marker)
            if rev is not None and rev >= COEXIST_MIN_FW_REV:
                verdict = ProbeVerdict.COEXIST
                self.progress.emit("No-reboot coexistence firmware detected…")
                logger.info(
                    "WiCAN coexistence firmware NCFRv%s on dedicated port %s",
                    rev,
                    WICAN_DEDICATED_SLCAN_PORT,
                )
            elif rev is not None:
                verdict = ProbeVerdict.OLD_FIRMWARE
                logger.info(
                    "WiCAN dedicated port answered NCFRv%s (< NCFRv%s); "
                    "legacy reboot path",
                    rev,
                    COEXIST_MIN_FW_REV,
                )
            else:
                logger.warning(
                    "WiCAN dedicated port %s accepted the connection but never "
                    "sent its version marker; capability UNKNOWN (refusing to "
                    "assume old firmware)",
                    WICAN_DEDICATED_SLCAN_PORT,
                )
        except Exception as exc:
            if _is_connection_refused(exc):
                verdict = ProbeVerdict.OLD_FIRMWARE
                logger.info(
                    "WiCAN dedicated port %s refused the connection; "
                    "pre-coexistence firmware, legacy reboot path",
                    WICAN_DEDICATED_SLCAN_PORT,
                )
            else:
                logger.warning(
                    "WiCAN coexist-port probe failed inconclusively (%s); "
                    "capability UNKNOWN",
                    exc,
                )
        finally:
            now = time.monotonic()
            # One line per probe carrying the verdict and where the time went, so
            # a field report is attributable to connect / ping instead of guessed
            # at. A probe that needed the confirming retry is logged at WARNING
            # with the measured refusal latency: that number is the only evidence
            # that would justify re-tuning _COEXIST_PROBE_RETRY_MS, and it varies
            # with the OS TCP retransmission settings, not machine speed.
            logger.log(
                logging.WARNING if retry_note else logging.INFO,
                "coexist probe: verdict=%s connect=%.2fs ping=%.2fs total=%.2fs%s",
                verdict.value,
                (connected_at - t0) if connected_at else (now - t0),
                (now - connected_at) if connected_at else 0.0,
                now - t0,
                f" [{retry_note}]" if retry_note else "",
            )

        if verdict is ProbeVerdict.COEXIST:
            return probe, verdict  # hand the OPEN transport to the caller
        if probe is not None:
            try:
                probe.close()
            except Exception:
                pass
        return None, verdict

    def _guard_inconclusive_probe(self, configurator):
        """Establish the right to write the stored mode, or refuse (#92).

        Reached only when the capability probe proved nothing. Rebooting the
        adapter into bench mode stops the datalogger, and if the session then
        dies the device stays that way — so this path needs evidence, not a
        guess. Order of preference:

          1. ``/host_caps`` — a small, secret-free capability reply. A rev at or
             above the threshold means coexistence firmware IS present and its
             port is simply not answering: there is nothing to connect to and no
             right to write. Below the threshold is conclusive old firmware.
          2. No ``/host_caps`` (every build in the field before it shipped) —
             fall back to the stored protocol. Already ``slcan`` means the
             legacy path performs NO write, so it is safe to continue; that also
             keeps a device this tool previously stranded reachable.

        :raises CoexistProbeInconclusive: when no evidence justifies the write.
        """
        from .exceptions import CoexistProbeInconclusive
        from .constants import COEXIST_MIN_FW_REV, WICAN_DEDICATED_SLCAN_PORT

        caps = configurator.host_caps()
        rev = (caps or {}).get("ncfr_rev")
        if isinstance(rev, int):
            if rev >= COEXIST_MIN_FW_REV:
                raise CoexistProbeInconclusive(
                    f"This adapter reports no-reboot firmware (NCFRv{rev}), but "
                    f"its port {WICAN_DEDICATED_SLCAN_PORT} did not answer. "
                    "Refusing to reboot it into bench mode — check the Wi-Fi "
                    "link and try again."
                )
            logger.info(
                "/host_caps reports NCFRv%s (< NCFRv%s); legacy mode write is "
                "justified",
                rev,
                COEXIST_MIN_FW_REV,
            )
            return

        try:
            current = configurator.current_protocol()
        except Exception as exc:
            raise CoexistProbeInconclusive(
                "Could not confirm whether this adapter supports no-reboot "
                f"flashing, and it did not answer over HTTP either ({exc}). "
                "Refusing to change its mode."
            ) from exc

        if current == "slcan":
            logger.info(
                "probe inconclusive but the adapter is already in slcan; "
                "continuing on the legacy path (no mode write will occur)"
            )
            return

        raise CoexistProbeInconclusive(
            f"Could not confirm whether this adapter supports no-reboot "
            f"flashing: port {WICAN_DEDICATED_SLCAN_PORT} did not answer, "
            f"though the device is reachable and reports {current!r}. Refusing "
            "to reboot it into bench mode — check the Wi-Fi link and try again."
        )

    @staticmethod
    def _enter_slcan_durable(configurator) -> str:
        """Enter SLCAN, persisting the TRUE original protocol to the crash-recovery
        sidecar BEFORE switching, and return that original.

        Mirrors ``WiCANConfigurator.slcan_session`` for this event-driven (non
        context-manager) lifecycle: if a prior run crashed mid-session it left a
        breadcrumb, so a recorded original is preferred over the device's current
        (possibly already-``slcan``) value. The breadcrumb is written before the
        switch so a hard kill during the multi-second reboot is recoverable.
        """
        recorded = configurator.read_recovery()
        current = configurator.current_protocol()
        true_prev = recorded if recorded is not None else current
        if true_prev != "slcan":
            configurator.write_recovery(true_prev)
        if current != "slcan":
            configurator.set_protocol("slcan")
        return true_prev

    def disconnect_ecu(self, restore_protocol: bool = True):
        """Close the transport.

        Args:
            restore_protocol: For WiCAN, restore the adapter's original HTTP
                protocol (a reboot). The internal auto-reconnect after a read
                passes ``False`` so the adapter stays in SLCAN across the
                reconnect; a user-initiated disconnect uses the default ``True``.
        """
        if self._state == ECUSessionState.DISCONNECTED:
            return
        if self._state == ECUSessionState.BUSY:
            # A flash/read worker is actively using the transport. Closing it now
            # (and rebooting the WiCAN protocol) would yank the link out from
            # under a running operation — a brick risk on a write. The caller
            # must release() first; refuse rather than tear down mid-operation.
            logger.warning("disconnect_ecu refused while BUSY; release() first")
            return
        self._teardown(restore_protocol=restore_protocol)
        self._set_state(ECUSessionState.DISCONNECTED)

    def acquire(self):
        """
        Acquire exclusive access to J2534 handles for flash operations.

        Returns (device, channel_id, filter_id, uds).
        Caller must call release() when done.
        """
        if self._state != ECUSessionState.CONNECTED:
            raise RuntimeError(f"Cannot acquire session in state {self._state.value}")
        self._set_state(ECUSessionState.BUSY)
        return (self._device, self._channel_id, self._filter_id, self._uds)

    def release(self, connection_dead: bool = False):
        """
        Release exclusive access after flash operation.

        Args:
            connection_dead: True if ECU was reset (connection is dead).
        """
        if self._state != ECUSessionState.BUSY:
            return
        if connection_dead:
            # ECU rebooted — tear down the dead connection. Keep the WiCAN
            # adapter in SLCAN (restore_protocol=False): the window always
            # auto-reconnects after a connection-dead release, and rebooting the
            # adapter's protocol on every read would be a needless reboot storm.
            self._teardown(restore_protocol=False)
            self._set_state(ECUSessionState.DISCONNECTED)
            logger.info("ECU session released (connection dead after reset)")
        else:
            self._set_state(ECUSessionState.CONNECTED)
            logger.info("ECU session released")

    def cleanup(self):
        """Shut down session and restore the adapter. Call on app exit / before
        discarding the session.

        Restores the WiCAN protocol even when the session is already
        DISCONNECTED but still holds an SLCAN switch — e.g. after a
        ``release(connection_dead=True)`` whose follow-up reconnect never
        happened (a failed flash/read). Without this, discarding such a session
        would strand the adapter in SLCAN and lose the original protocol.
        """
        if self._state != ECUSessionState.DISCONNECTED:
            self._teardown(restore_protocol=True)
            self._set_state(ECUSessionState.DISCONNECTED)
        else:
            self._restore_wican_protocol()

    # --- Internal ---

    def _set_state(self, state: ECUSessionState):
        if self._state != state:
            self._state = state
            self.state_changed.emit(state.value)
            logger.debug("ECU session state: %s", state.value)

    def _teardown(self, restore_protocol: bool = True):
        """Close the transport (error-tolerant); optionally restore WiCAN protocol."""
        if self._adapter_kind == "wican":
            self._teardown_wican(restore_protocol=restore_protocol)
        else:
            self._teardown_j2534()
        self._uds = None
        logger.info("ECU session disconnected")

    def _teardown_j2534(self):
        """Clean up J2534 resources (error-tolerant). Unchanged."""
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

    def _teardown_wican(self, restore_protocol: bool):
        """Close the WiCAN transport; restore the original protocol if asked.

        ``restore_protocol`` is ``False`` on the internal auto-reconnect (keep
        the adapter in SLCAN) and ``True`` on a user disconnect / app exit.
        """
        # Release the whole-session bus reservation FIRST (resume the datalogger)
        # while the transport is still up. Best-effort: a failed release just leaves
        # the firmware dead-man reaper to auto-resume the logger. The flash fence's
        # own ref is already dropped by the time any teardown runs (its context
        # manager is fully contained in flash_rom), so this is the last ref.
        if self._wican_datalog is not None:
            try:
                self._wican_datalog.release_bus()
            except Exception:
                pass
            self._wican_datalog = None

        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None

        if restore_protocol:
            self._restore_wican_protocol()

    def _restore_wican_protocol(self):
        """Restore the original WiCAN protocol and clear the recovery breadcrumb.

        Idempotent and adapter-agnostic: a no-op unless this session actually
        switched the adapter to SLCAN (``_slcan_switched``). Safe to call from
        any state, so :meth:`cleanup` can recover a session that was torn down
        without a protocol restore (``release(connection_dead=True)``).
        """
        if not (self._slcan_switched and self._configurator):
            return
        prev = self._slcan_prev_protocol
        try:
            if prev and prev != "slcan":
                self.progress.emit("Restoring adapter protocol (~6 s reboot)…")
                self._configurator.restore(prev)
        except Exception as exc:
            # KEEP the breadcrumb AND the switch state (#92). The device is still
            # in slcan and the sidecar is the only record of the user's real
            # mode; clearing it here strands the device permanently. Holding the
            # state also leaves cleanup() -- which runs at app exit and on
            # session replacement -- a free second attempt, and a reconnect still
            # works because the `not _slcan_switched` guard skips the re-switch.
            # If the restore only failed its verify while the write landed, the
            # retry's set_protocol no-ops and cleanly clears the sidecar.
            logger.warning(
                "WiCAN protocol restore failed: %s -- breadcrumb KEPT so a later "
                "run can un-strand the device",
                exc,
            )
            return
        try:
            self._configurator.clear_recovery()
        except Exception:
            pass
        self._slcan_switched = False
        self._slcan_prev_protocol = None
        self._configurator = None
