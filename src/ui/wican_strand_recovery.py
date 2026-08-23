"""Start-up recovery for a WiCAN adapter left in bench (slcan) mode (#92).

Flashing over WiFi on pre-coexistence firmware means rebooting the adapter into
``slcan``, and putting it back afterwards. If that session dies first -- a crash,
a force-quit, a closed laptop -- the adapter stays in bench mode: it stops
datalogging, and nothing puts it right. Until now the only cure was reconnecting
to that exact device, which is the last thing someone whose logger just died
tends to do.

This runs one scan at start-up instead. Two phases, both driven by the same
:func:`~src.ecu.wican_config.recover_stranded_protocols` used by the tests:

  1. **Scan (read-only).** Declines every restore, so it only reports which
     devices are genuinely stranded -- reachable, stored mode is ``slcan``, and
     no flash or host bus-claim in progress. Nothing is written.
  2. **Restore (after the user agrees).** Re-runs the sweep, approving only the
     hosts the user accepted.

Both phases run on a worker thread: the scan does network I/O and a restore
blocks for the device's reboot, neither of which may sit on the UI thread.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


class _StrandScanWorker(QObject):
    """Read-only scan for stranded adapters (see phase 1 above)."""

    finished = Signal(list)  # [{"host", "previous_protocol", ...}, ...]

    def __init__(self, busy_hosts=frozenset()):
        super().__init__()
        self._busy_hosts = busy_hosts

    def run(self):
        candidates = []
        try:
            from src.ecu.wican_config import recover_stranded_protocols

            # confirm=False everywhere: this pass may not write anything. The
            # sweep still does all the safety checks, so a host that comes back
            # "declined" is one that IS stranded and IS safe to restore.
            for record in recover_stranded_protocols(
                confirm=lambda host, prev: False,
                should_skip=self._busy_hosts.__contains__,
            ):
                if record.get("action") == "declined":
                    candidates.append(record)
        except Exception:  # never let start-up break on this
            logger.exception("WiCAN strand scan failed")
        self.finished.emit(candidates)


class _StrandRestoreWorker(QObject):
    """Restore the approved hosts (phase 2)."""

    finished = Signal(list)

    def __init__(self, approved, busy_hosts=frozenset()):
        super().__init__()
        self._approved = set(approved)
        self._busy_hosts = busy_hosts

    def run(self):
        records = []
        try:
            from src.ecu.wican_config import recover_stranded_protocols

            records = recover_stranded_protocols(
                confirm=lambda host, prev: host in self._approved,
                should_skip=self._busy_hosts.__contains__,
            )
        except Exception:
            logger.exception("WiCAN strand restore failed")
        self.finished.emit(records)


class WiCANStrandRecovery(QObject):
    """Owns the start-up scan, its dialog, and the restore that may follow.

    Held by the caller for the life of the app so the worker threads are not
    garbage collected mid-run.
    """

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self._window = parent_window
        self._threads = []

    def start(self):
        """Kick the read-only scan. Returns immediately."""
        self._run(_StrandScanWorker(self._busy_hosts()), self._on_scan_done)

    def _busy_hosts(self) -> frozenset:
        """Adapters this app is already using, as a plain frozen set.

        Restoring an adapter we are actively using would reboot it out from
        under our own session. On coexistence firmware the sweep catches that
        anyway (our session holds the bus claim, so it reports ``busy``); on
        older firmware there is no such signal, and this is the only check.

        MUST be called on the UI thread -- it reads window/session state, which
        the workers may not touch. The workers get this immutable snapshot
        instead of a callback into live objects. It is taken fresh for each
        phase, so the dialog sitting unanswered does not stale it.

        Deliberately tolerant: an unexpected window layout yields an empty set
        rather than disabling recovery; the sweep's flash/claim guard is what
        actually protects a device mid-flash.
        """
        try:
            ecu_window = getattr(self._window, "ecu_window", None)
            session = getattr(ecu_window, "_session", None)
            if session is None or not session.is_connected:
                return frozenset()
            host = session.wican_host
            return frozenset([host]) if host else frozenset()
        except Exception:
            logger.debug("could not check for live WiCAN sessions", exc_info=True)
            return frozenset()

    # -- internals ---------------------------------------------------------

    def _run(self, worker, on_finished):
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        # Keep both alive; a collected QThread mid-run crashes the app.
        self._threads.append((thread, worker))
        thread.start()

    def _on_scan_done(self, candidates):
        if not candidates:
            logger.debug("WiCAN strand scan: nothing stranded")
            return

        from PySide6.QtWidgets import QMessageBox

        hosts = [c["host"] for c in candidates]
        listed = "\n".join(
            f"  • {c['host']}  (was {c['previous_protocol']})" for c in candidates
        )
        logger.warning("WiCAN strand scan found stranded adapter(s): %s", hosts)

        answer = QMessageBox.question(
            self._window,
            "WiCAN adapter left in bench mode",
            "An earlier session left this adapter in bench (SLCAN) mode, so it "
            "is not datalogging:\n\n"
            f"{listed}\n\n"
            "Put it back now? The adapter will reboot, which takes a few "
            "seconds.\n\n"
            "Do NOT do this if another computer is flashing an ECU through it.",
            QMessageBox.Yes | QMessageBox.No,
            # Default to No. On pre-coexistence firmware there is no /datalog to
            # ask, so this Yes is the ONLY thing standing between the sweep and
            # rebooting a device that might be mid-ECU-write -- which can leave
            # the car's PCM half-written. An absent-minded Enter must land on
            # the side that does nothing.
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            logger.info("User declined WiCAN strand recovery for %s", hosts)
            return
        self._run(
            _StrandRestoreWorker(hosts, self._busy_hosts()), self._on_restore_done
        )

    def _on_restore_done(self, records):
        restored = [r["host"] for r in records if r.get("action") == "restored"]
        failed = [r["host"] for r in records if r.get("action") == "failed"]
        logger.info("WiCAN strand recovery: restored=%s failed=%s", restored, failed)
        if not failed:
            return

        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            self._window,
            "Could not restore the adapter",
            "The adapter could not be put back into its normal mode:\n\n"
            + "\n".join(f"  • {h}" for h in failed)
            + "\n\nIt is still in bench mode and will not datalog. NC Flash will "
            "try again next time it starts.",
        )
