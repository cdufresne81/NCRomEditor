"""Drive a single ECUSession connect against the strand proxy (#92 bench repro).

Runs headless in its OWN process so the strand can be produced deterministically
instead of by racing ``taskkill``. The window between "the mode write landed"
and "teardown restores it" is only a couple of seconds, so rather than trying to
kill from outside, ``--strand`` makes the process die from the inside at exactly
the right instant: ``UDSConnection.tester_present`` is patched to ``os._exit``,
which is the closest software equivalent of a power cut -- no ``finally``, no
``atexit``, no Qt teardown, no protocol restore.

Usage (always through the proxy, never straight at the device):

    python tests/bench/slcan_strand_driver.py            # connect and disconnect cleanly
    python tests/bench/slcan_strand_driver.py --strand   # connect, then die mid-session

Exit codes: 0 clean, 1 killed by --strand (expected), 2 connect failed.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Import from the repo root regardless of where this is invoked from.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

#: The proxy's loopback address. Everything the driver touches goes through it,
#: so the breadcrumb sidecar is keyed to 127_0_0_1 rather than the device IP.
PROXY_HOST = "127.0.0.1"
PROXY_LEGACY_PORT = 35000


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--strand",
        action="store_true",
        help="die inside the session, after any mode write, before any restore",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    from PySide6.QtWidgets import QApplication
    from src.ecu.session import ECUSession, ECUSessionState

    app = QApplication.instance() or QApplication([])  # noqa: F841 (Qt needs it alive)

    if args.strand:
        from src.ecu.protocol import UDSConnection

        def _die(self, *a, **kw):
            # We are past the protocol switch and inside the live session. This
            # is where a crash, a force-quit or a yanked power lead would land.
            logging.getLogger("driver").warning(
                "STRAND: killing the process mid-session (no restore will run)"
            )
            sys.stdout.flush()
            os._exit(1)

        UDSConnection.tester_present = _die

    session = ECUSession(
        adapter_config={
            "kind": "wican",
            "host": PROXY_HOST,
            "port": PROXY_LEGACY_PORT,
            "auto_config": True,
        }
    )
    session.progress.connect(
        lambda m: logging.getLogger("driver").info("progress: %s", m)
    )
    session.connection_lost.connect(
        lambda m: logging.getLogger("driver").warning("connection_lost: %s", m)
    )

    session.connect_ecu()

    if session.state != ECUSessionState.CONNECTED:
        logging.getLogger("driver").error("connect failed (state=%s)", session.state)
        return 2

    logging.getLogger("driver").info("connected; disconnecting cleanly")
    session.disconnect_ecu()
    return 0


if __name__ == "__main__":
    sys.exit(main())
