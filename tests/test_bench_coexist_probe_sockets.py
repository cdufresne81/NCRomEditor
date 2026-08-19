"""Real-socket checks for the coexistence probe verdicts (#92).

These exist because a mocked exception cannot pin OS behaviour. The unit test
``test_connect_refused_is_conclusive_old_firmware`` sets ``__cause__`` to a
``ConnectionRefusedError`` and passes -- while the real thing FAILED on the
bench, because Windows does not deliver that error inside the probe's 1.5 s
budget. Winsock receives the RST for a closed port and deliberately ignores it,
retransmitting the SYN on its own schedule; the refusal only surfaces once that
schedule is exhausted, measured at ~2.0 s on default settings. So a genuinely
pre-coexistence adapter looked like a network fault and would have been refused
a connect -- exactly the "protect ourselves by breaking old hardware" outcome
the guard test was written to prevent, invisible to the guard test.

Real sockets are the only thing that can catch that class of drift, so this runs
against a genuinely closed local port. No device, no network, ~4 s.

    venv-windows\\Scripts\\python.exe -m pytest tests/test_bench_coexist_probe_sockets.py -m bench

Deselected from normal runs by the ``bench`` marker.
"""

import socket
import time

import pytest

from src.ecu.constants import WICAN_DEDICATED_SLCAN_PORT, COEXIST_PROBE_TIMEOUT_MS
from src.ecu.session import ECUSession, ProbeVerdict, _COEXIST_PROBE_RETRY_MS

pytestmark = pytest.mark.bench


@pytest.fixture
def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _port_is_free(port: int) -> bool:
    """True when nothing is listening on the loopback ``port``."""
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", port))
    except OSError:
        return True
    else:
        return False
    finally:
        probe.close()


def test_real_refused_port_is_conclusive_old_firmware(_qapp):
    """A really-closed port must reach OLD_FIRMWARE, not INCONCLUSIVE.

    This is the regression the bench caught. If it ever fails again, legacy
    adapters are being refused: either the OS refusal latency now exceeds
    ``_COEXIST_PROBE_RETRY_MS``, or the cause chain stopped carrying
    ``ConnectionRefusedError``.
    """
    if not _port_is_free(WICAN_DEDICATED_SLCAN_PORT):
        pytest.skip(
            f"something is listening on {WICAN_DEDICATED_SLCAN_PORT}; "
            "this check needs a genuinely closed port"
        )

    session = ECUSession(
        adapter_config={
            "kind": "wican",
            "host": "127.0.0.1",
            "port": 35000,
            "auto_config": True,
        }
    )

    started = time.monotonic()
    transport, verdict = session._try_open_coexist_port()
    elapsed_ms = (time.monotonic() - started) * 1000

    assert transport is None
    assert verdict is ProbeVerdict.OLD_FIRMWARE, (
        f"a closed port was classified {verdict.value!r} after {elapsed_ms:.0f} ms. "
        "Legacy adapters would now be refused a connect. If the refusal simply "
        "arrived late, raise _COEXIST_PROBE_RETRY_MS "
        f"(currently {_COEXIST_PROBE_RETRY_MS} ms)."
    )
    # It must also resolve within the budget we actually promise the user: the
    # first attempt, plus the one confirming retry, plus slack for scheduling.
    budget_ms = COEXIST_PROBE_TIMEOUT_MS + _COEXIST_PROBE_RETRY_MS + 2000
    assert elapsed_ms < budget_ms, (
        f"probe took {elapsed_ms:.0f} ms, over the {budget_ms} ms budget"
    )


def test_real_unreachable_host_is_inconclusive(_qapp):
    """A black-holed address must stay INCONCLUSIVE, so no mode write happens.

    The counterpart to the test above: a refusal is conclusive, silence is not.
    192.0.2.1 is TEST-NET-1 (RFC 5737) -- reserved for documentation and never
    routed, so packets are dropped rather than answered.
    """
    session = ECUSession(
        adapter_config={
            "kind": "wican",
            "host": "192.0.2.1",
            "port": 35000,
            "auto_config": True,
        }
    )

    transport, verdict = session._try_open_coexist_port()

    assert transport is None
    assert verdict is ProbeVerdict.INCONCLUSIVE, (
        f"an unroutable host was classified {verdict.value!r}; anything other "
        "than INCONCLUSIVE would authorise rewriting a device's stored mode on "
        "no evidence, which is the #92 defect"
    )
