"""TCP proxy that reproduces the Bench SLCAN strand (#92) on real hardware.

The strand needs the coexistence-port probe to fail on a device that is
otherwise perfectly reachable. On the bench that never happens by itself --
measured 5/5 successful probes at ~0.45 s against a 1.5 s budget -- so the
failure has to be induced.

This proxy sits between NC Flash and the device:

    NC Flash  ->  127.0.0.1:80     ->  device:80      (always forwarded)
                  127.0.0.1:35000  ->  device:35000   (always forwarded)
                  127.0.0.1:35001  ->  device:35001   (mode-dependent)

Port 35001 modes:

    stall   accept the connection, then never forward or answer a byte.
            Reproduces the exact field signature: the SLCAN bring-up tolerates
            silence, so open() succeeds and the version ping window closes
            empty -> ``rev=None`` -> the legacy mode-write path.
    drop    do not listen at all, so the OS answers with a TCP RST. This is the
            CONCLUSIVE "nothing is bound to 35001" case, i.e. genuine
            pre-coexistence firmware. Used to prove the fix does not break
            legacy hardware.
    pass    forward normally -- the healthy control.

Deliberately dependency-free (stdlib only) so it can run from any shell.

    python tests/bench/slcan_strand_proxy.py --device 192.168.1.169 --mode stall

Ports 80 and 35000 are ALWAYS forwarded, in every mode. That is the whole
point: the device must look healthy to everything except the capability probe.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading

logger = logging.getLogger("slcan_strand_proxy")

#: Ports forwarded verbatim regardless of mode (HTTP config + legacy SLCAN).
ALWAYS_FORWARD = (80, 35000)
#: The coexistence capability port whose behaviour the experiment controls.
COEXIST_PORT = 35001


def _pump(src: socket.socket, dst: socket.socket) -> None:
    """Copy bytes one way until either end closes. Never raises."""
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _forward(client: socket.socket, device_host: str, port: int) -> None:
    """Splice one accepted client onto a fresh device connection."""
    upstream = socket.socket()
    try:
        upstream.settimeout(5.0)
        upstream.connect((device_host, port))
        upstream.settimeout(None)
    except OSError as exc:
        logger.warning("upstream connect to %s:%s failed: %s", device_host, port, exc)
        client.close()
        upstream.close()
        return
    threading.Thread(target=_pump, args=(client, upstream), daemon=True).start()
    threading.Thread(target=_pump, args=(upstream, client), daemon=True).start()


def _stall(client: socket.socket) -> None:
    """Accept and hold the connection open, sending nothing, ever.

    Holding a reference is the point -- letting the socket be garbage collected
    would close it and turn the stall into a refusal, which is a different (and
    conclusive) failure.
    """
    logger.info("stalling a coexist-port connection (no data will be sent)")
    try:
        while True:
            # Swallow whatever the client sends (the SLCAN bring-up commands and
            # the version ping) and answer NOTHING. Returning from this function
            # would close the socket, which the peer reads as an abort -- a
            # different, conclusive failure. The connection must stay open and
            # silent until the peer itself gives up.
            if not client.recv(65536):
                break
    except OSError:
        pass
    finally:
        client.close()


def _serve(port: int, device_host: str, mode: str, stop: threading.Event) -> None:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(8)
    srv.settimeout(0.5)
    logger.info(
        "listening on 127.0.0.1:%s -> %s:%s (%s)",
        port,
        device_host,
        port,
        mode if port == COEXIST_PORT else "forward",
    )
    while not stop.is_set():
        try:
            client, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        if port == COEXIST_PORT and mode == "stall":
            threading.Thread(target=_stall, args=(client,), daemon=True).start()
        else:
            threading.Thread(
                target=_forward, args=(client, device_host, port), daemon=True
            ).start()
    srv.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", required=True, help="real device IP, e.g. 192.168.1.169")
    ap.add_argument(
        "--mode",
        choices=("stall", "drop", "pass"),
        default="stall",
        help="behaviour of the coexistence port 35001",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s proxy: %(message)s")

    ports = list(ALWAYS_FORWARD)
    if args.mode != "drop":
        ports.append(COEXIST_PORT)
    else:
        logger.info(
            "mode=drop: NOT listening on %s, so the OS will refuse the connect "
            "(the conclusive old-firmware case)",
            COEXIST_PORT,
        )

    stop = threading.Event()
    threads = [
        threading.Thread(
            target=_serve, args=(p, args.device, args.mode, stop), daemon=True
        )
        for p in ports
    ]
    for t in threads:
        t.start()
    logger.info("proxy up (mode=%s). Ctrl-C to stop.", args.mode)
    try:
        while True:
            for t in threads:
                t.join(0.5)
    except KeyboardInterrupt:
        logger.info("stopping")
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
