"""
CAN Bus Listener Window

Real-time CAN bus monitoring via Tactrix OpenPort 2.0 J2534 device.
Displays raw CAN frames in a scrollable table with optional DBC decoding.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTableView,
    QHeaderView,
    QMessageBox,
    QFileDialog,
    QAbstractItemView,
)
from PySide6.QtCore import (
    Qt,
    QThread,
    QObject,
    Signal,
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
)

from src.ecu.constants import DEFAULT_J2534_DLL
from src.ecu.can_listener import CANListener, CANFrame
from src.ecu.can_decoder import CANDecoder
from src.ecu.exceptions import J2534Error

logger = logging.getLogger(__name__)

# Maximum number of frames to keep in the model
MAX_FRAMES = 50_000

_COLUMNS = ["Timestamp", "CAN ID", "DLC", "Data", "Decoded"]


# ---------------------------------------------------------------------------
# Table model
# ---------------------------------------------------------------------------


class CANFrameModel(QAbstractTableModel):
    """Table model for CAN bus frames."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: list[CANFrame] = []
        self._decoded: list[str] = []

    # -- Qt model interface --

    def rowCount(self, parent=QModelIndex()):
        return len(self._frames)

    def columnCount(self, parent=QModelIndex()):
        return len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = index.row()
        col = index.column()
        frame = self._frames[row]
        if col == 0:
            return f"{frame.timestamp_us / 1_000_000:.6f}"
        if col == 1:
            return f"0x{frame.can_id:03X}"
        if col == 2:
            return str(frame.dlc)
        if col == 3:
            return " ".join(f"{b:02X}" for b in frame.data)
        if col == 4:
            return self._decoded[row]
        return None

    # -- Public API --

    def add_frames(
        self, frames: list[CANFrame], decoder: CANDecoder | None = None
    ) -> None:
        """Append frames to the model, dropping oldest when over MAX_FRAMES."""
        if not frames:
            return

        # Decode each frame
        decoded_strings: list[str] = []
        for f in frames:
            if decoder is not None:
                signals = decoder.decode(f)
                if signals:
                    decoded_strings.append(
                        ", ".join(f"{k}={v}" for k, v in signals.items())
                    )
                else:
                    decoded_strings.append("")
            else:
                decoded_strings.append("")

        # Insert new rows
        first = len(self._frames)
        last = first + len(frames) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._frames.extend(frames)
        self._decoded.extend(decoded_strings)
        self.endInsertRows()

        # Drop oldest if over limit
        overflow = len(self._frames) - MAX_FRAMES
        if overflow > 0:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            del self._frames[:overflow]
            del self._decoded[:overflow]
            self.endRemoveRows()

    def clear(self) -> None:
        """Remove all frames."""
        if not self._frames:
            return
        self.beginResetModel()
        self._frames.clear()
        self._decoded.clear()
        self.endResetModel()

    def export_csv(self, path: str) -> None:
        """Write all rows to a CSV file."""
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(_COLUMNS)
            for i in range(len(self._frames)):
                row = [
                    self.data(self.index(i, c), Qt.DisplayRole)
                    for c in range(len(_COLUMNS))
                ]
                writer.writerow(row)

    @property
    def frame_count(self) -> int:
        """Return the number of frames currently stored."""
        return len(self._frames)


# ---------------------------------------------------------------------------
# Worker (runs on QThread)
# ---------------------------------------------------------------------------


class _CANListenerWorker(QObject):
    """Background worker that runs the CAN listener poll loop."""

    frames_received = Signal(list)
    error = Signal(str)
    started = Signal()
    stopped = Signal()

    def __init__(self, listener: CANListener):
        super().__init__()
        self._listener = listener

    def run(self):
        try:
            self._listener.start()
            self.started.emit()
            self._listener.poll_loop(self._on_frames)
        except J2534Error as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.stopped.emit()

    def _on_frames(self, frames: list[CANFrame]):
        self.frames_received.emit(frames)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class CANListenerWindow(QMainWindow):
    """CAN Bus Listener window with real-time frame display."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._decoder = CANDecoder()
        self._listener: CANListener | None = None
        self._thread: QThread | None = None
        self._worker: _CANListenerWorker | None = None
        self._paused = False
        self._auto_scroll = True
        self._listening = False

        self.setWindowTitle("CAN Bus Listener")
        self.setMinimumSize(800, 500)
        self.resize(900, 600)

        self._build_ui()

    # -- UI construction --

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Connection bar ---
        conn_frame = QWidget()
        conn_frame.setStyleSheet(
            "background: #333; border: 1px solid #555; border-radius: 6px; "
            "padding: 6px;"
        )
        conn_layout = QHBoxLayout(conn_frame)
        conn_layout.setContentsMargins(8, 4, 8, 4)
        conn_layout.setSpacing(8)

        self._btn_start = QPushButton("\u25b6 Start")
        self._btn_start.setFixedWidth(80)
        self._btn_start.clicked.connect(self._on_start)
        conn_layout.addWidget(self._btn_start)

        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setFixedWidth(60)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        conn_layout.addWidget(self._btn_stop)

        sep = QLabel("|")
        sep.setStyleSheet("color: #666; border: none;")
        conn_layout.addWidget(sep)

        lbl = QLabel("DBC:")
        lbl.setStyleSheet("color: #bbb; border: none;")
        conn_layout.addWidget(lbl)

        self._dbc_label = QLabel("(none)")
        self._dbc_label.setStyleSheet("color: #aaa; border: none;")
        conn_layout.addWidget(self._dbc_label)

        self._btn_load_dbc = QPushButton("Load...")
        self._btn_load_dbc.setFixedWidth(60)
        self._btn_load_dbc.clicked.connect(self._on_load_dbc)
        conn_layout.addWidget(self._btn_load_dbc)

        conn_layout.addStretch()

        sep2 = QLabel("|")
        sep2.setStyleSheet("color: #666; border: none;")
        conn_layout.addWidget(sep2)

        status_lbl = QLabel("Status:")
        status_lbl.setStyleSheet("color: #bbb; border: none;")
        conn_layout.addWidget(status_lbl)

        self._status_label = QLabel("Stopped")
        self._status_label.setStyleSheet(
            "font-weight: bold; color: gray; border: none;"
        )
        conn_layout.addWidget(self._status_label)

        root.addWidget(conn_frame)

        # --- Filter bar ---
        filter_frame = QWidget()
        filter_frame.setStyleSheet(
            "background: #2a2a2a; border: 1px solid #444; border-radius: 6px; "
            "padding: 4px;"
        )
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(8, 2, 8, 2)
        filter_layout.setSpacing(8)

        flbl = QLabel("Filter CAN ID:")
        flbl.setStyleSheet("color: #bbb; border: none;")
        filter_layout.addWidget(flbl)

        self._filter_edit = QLineEdit()
        self._filter_edit.setFixedWidth(120)
        self._filter_edit.setPlaceholderText("e.g. 0x7E0")
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._filter_edit)

        filter_layout.addStretch()

        sep3 = QLabel("|")
        sep3.setStyleSheet("color: #666; border: none;")
        filter_layout.addWidget(sep3)

        frames_lbl = QLabel("Frames:")
        frames_lbl.setStyleSheet("color: #bbb; border: none;")
        filter_layout.addWidget(frames_lbl)

        self._frame_count_label = QLabel("0")
        self._frame_count_label.setStyleSheet(
            "color: white; font-weight: bold; border: none;"
        )
        filter_layout.addWidget(self._frame_count_label)

        root.addWidget(filter_frame)

        # --- Table ---
        self._model = CANFrameModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterKeyColumn(1)  # Filter on CAN ID column
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            "QTableView { background: #1e1e1e; alternate-background-color: #252525; "
            "gridline-color: #333; border: 1px solid #444; }"
            "QHeaderView::section { background: #333; color: #ccc; "
            "border: 1px solid #444; padding: 4px; }"
        )

        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Interactive)

        root.addWidget(self._table, stretch=1)

        # --- Bottom bar ---
        bottom_frame = QWidget()
        bottom_frame.setStyleSheet(
            "background: #2a2a2a; border: 1px solid #444; border-radius: 6px; "
            "padding: 4px;"
        )
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(8, 4, 8, 4)
        bottom_layout.setSpacing(8)

        self._btn_clear = QPushButton("Clear")
        self._btn_clear.setFixedWidth(60)
        self._btn_clear.clicked.connect(self._on_clear)
        bottom_layout.addWidget(self._btn_clear)

        self._btn_pause = QPushButton("Pause")
        self._btn_pause.setFixedWidth(70)
        self._btn_pause.clicked.connect(self._on_toggle_pause)
        bottom_layout.addWidget(self._btn_pause)

        self._btn_export = QPushButton("Export CSV...")
        self._btn_export.setFixedWidth(100)
        self._btn_export.clicked.connect(self._on_export_csv)
        bottom_layout.addWidget(self._btn_export)

        bottom_layout.addStretch()

        self._btn_autoscroll = QPushButton("Auto-scroll: ON")
        self._btn_autoscroll.setFixedWidth(120)
        self._btn_autoscroll.clicked.connect(self._on_toggle_autoscroll)
        bottom_layout.addWidget(self._btn_autoscroll)

        root.addWidget(bottom_frame)

    # -- Start / Stop --

    def _on_start(self):
        # Mutual exclusion: check if ECU programming is connected
        if (
            hasattr(self._main_window, "ecu_window")
            and self._main_window.ecu_window
            and hasattr(self._main_window.ecu_window, "_session")
            and self._main_window.ecu_window._session
            and self._main_window.ecu_window._session.is_connected
        ):
            QMessageBox.warning(
                self,
                "Device Busy",
                "Cannot start CAN Bus Listener while connected to ECU.\n\n"
                "Disconnect from ECU Programming first.",
            )
            return

        dll_path = self._main_window.settings.get_j2534_dll_path() or DEFAULT_J2534_DLL
        self._listener = CANListener(dll_path)

        self._worker = _CANListenerWorker(self._listener)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.started.connect(self._on_listener_started)
        self._worker.stopped.connect(self._on_listener_stopped)
        self._worker.error.connect(self._on_listener_error)
        self._worker.frames_received.connect(self._on_frames_received)
        self._worker.stopped.connect(self._thread.quit)

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._status_label.setText("Connecting...")
        self._status_label.setStyleSheet(
            "font-weight: bold; color: #ccaa44; border: none;"
        )

        self._thread.start()

    def _on_stop(self):
        if self._listener:
            self._listener.stop()
        # Thread will finish via the stopped signal -> quit connection

    def _on_listener_started(self):
        self._listening = True
        self._status_label.setText("Listening")
        self._status_label.setStyleSheet(
            "font-weight: bold; color: #44aa44; border: none;"
        )
        logger.info("CAN Bus Listener started")

    def _on_listener_stopped(self):
        self._listening = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status_label.setText("Stopped")
        self._status_label.setStyleSheet(
            "font-weight: bold; color: gray; border: none;"
        )
        logger.info("CAN Bus Listener stopped")

    def _on_listener_error(self, msg: str):
        self._listening = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status_label.setText("Error")
        self._status_label.setStyleSheet(
            "font-weight: bold; color: #cc4444; border: none;"
        )
        QMessageBox.critical(self, "CAN Listener Error", msg)
        logger.error("CAN Bus Listener error: %s", msg)

    # -- Frame handling --

    def _on_frames_received(self, frames: list[CANFrame]):
        if self._paused:
            return
        self._model.add_frames(frames, self._decoder)
        self._frame_count_label.setText(str(self._model.frame_count))
        if self._auto_scroll:
            self._table.scrollToBottom()

    # -- Controls --

    def _on_toggle_pause(self):
        self._paused = not self._paused
        self._btn_pause.setText("Resume" if self._paused else "Pause")

    def _on_clear(self):
        self._model.clear()
        self._frame_count_label.setText("0")

    def _on_export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CAN Frames", "", "CSV Files (*.csv)"
        )
        if path:
            try:
                self._model.export_csv(path)
                logger.info("Exported %d frames to %s", self._model.frame_count, path)
            except Exception as exc:
                QMessageBox.critical(self, "Export Error", str(exc))

    def _on_load_dbc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load DBC File", "", "DBC Files (*.dbc)"
        )
        if path:
            self._decoder.load(path)
            if self._decoder.is_loaded:
                self._dbc_label.setText(Path(path).name)
            else:
                self._dbc_label.setText("(load failed)")

    def _on_toggle_autoscroll(self):
        self._auto_scroll = not self._auto_scroll
        self._btn_autoscroll.setText(
            "Auto-scroll: ON" if self._auto_scroll else "Auto-scroll: OFF"
        )

    def _on_filter_changed(self, text: str):
        self._proxy.setFilterRegularExpression(text)

    # -- Window lifecycle --

    def closeEvent(self, event):
        if self._listening and self._listener:
            self._listener.stop()
            if self._thread and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(2000)
        super().closeEvent(event)

    @property
    def is_listening(self) -> bool:
        """Return True if the listener is actively running."""
        return self._listening
