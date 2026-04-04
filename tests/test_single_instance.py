"""
Tests for single-instance IPC and command-line file argument handling.
"""

import os
import uuid
import pytest
from unittest.mock import patch, MagicMock
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from PySide6.QtNetwork import QLocalServer, QLocalSocket


@pytest.fixture
def ipc_name():
    """Unique server name per test to avoid collisions."""
    name = f"NCFlash_test_{uuid.uuid4().hex[:8]}"
    yield name
    QLocalServer.removeServer(name)


class TestTrySendToRunningInstance:
    """Tests for _try_send_to_running_instance."""

    def test_returns_false_when_no_server(self, ipc_name):
        from main import _try_send_to_running_instance

        assert _try_send_to_running_instance("C:\\fake\\path.bin", ipc_name) is False

    def test_connects_to_running_server(self, ipc_name):
        from main import _try_send_to_running_instance

        server = QLocalServer()
        assert server.listen(ipc_name)

        result = _try_send_to_running_instance("C:\\some\\file.bin", ipc_name)
        assert result is True

        server.close()


class _IpcTestWidget(QWidget):
    """Lightweight stand-in for MainWindow — only the IPC server logic."""

    def __init__(self):
        super().__init__()
        self._ipc_server = None
        self._ipc_server_name = None
        self._open_rom_file = MagicMock()

    def start_ipc_server(self, server_name):
        self._ipc_server_name = server_name
        self._ipc_server = QLocalServer(self)
        self._ipc_server.newConnection.connect(self._on_ipc_connection)
        QLocalServer.removeServer(self._ipc_server_name)
        if not self._ipc_server.listen(self._ipc_server_name):
            raise RuntimeError(self._ipc_server.errorString())

    def _on_ipc_connection(self):
        conn = self._ipc_server.nextPendingConnection()
        if not conn:
            return
        conn.waitForReadyRead(1000)
        data = conn.readAll().data().decode("utf-8").strip()
        conn.disconnectFromServer()
        if data and os.path.isfile(data):
            self._open_rom_file(data)
            self.setWindowState(
                self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
            )
            self.raise_()
            self.activateWindow()


class TestIpcServer:
    """Tests for IPC server logic (start_ipc_server / _on_ipc_connection).

    Uses a lightweight widget instead of MainWindow to avoid heavy UI init.
    The IPC handler logic is duplicated here from MainWindow.start_ipc_server /
    _on_ipc_connection — if those methods change, these tests should be updated.
    """

    def test_server_starts_and_listens(self, qtbot, ipc_name):
        widget = _IpcTestWidget()
        qtbot.addWidget(widget)
        widget.start_ipc_server(server_name=ipc_name)

        assert widget._ipc_server is not None
        assert widget._ipc_server.isListening()

        widget.close()

    def test_server_receives_file(self, qtbot, sample_rom_path, ipc_name):
        widget = _IpcTestWidget()
        qtbot.addWidget(widget)
        widget.start_ipc_server(server_name=ipc_name)

        socket = QLocalSocket()
        socket.connectToServer(ipc_name)
        assert socket.waitForConnected(1000)

        file_path = str(sample_rom_path)
        socket.write(file_path.encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()

        qtbot.waitUntil(lambda: widget._open_rom_file.call_count == 1, timeout=2000)
        widget._open_rom_file.assert_called_once_with(file_path)

        widget.close()

    def test_server_ignores_nonexistent_file(self, qtbot, ipc_name):
        widget = _IpcTestWidget()
        qtbot.addWidget(widget)
        widget.start_ipc_server(server_name=ipc_name)

        socket = QLocalSocket()
        socket.connectToServer(ipc_name)
        assert socket.waitForConnected(1000)

        socket.write(b"C:\\nonexistent\\fake.bin")
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()

        # Give it time to process — should NOT call _open_rom_file
        qtbot.wait(500)
        widget._open_rom_file.assert_not_called()

        widget.close()

    def test_server_ignores_empty_message(self, qtbot, ipc_name):
        widget = _IpcTestWidget()
        qtbot.addWidget(widget)
        widget.start_ipc_server(server_name=ipc_name)

        socket = QLocalSocket()
        socket.connectToServer(ipc_name)
        assert socket.waitForConnected(1000)

        socket.write(b"")
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()

        qtbot.wait(500)
        widget._open_rom_file.assert_not_called()

        widget.close()

    # NOTE: Full round-trip test (_try_send_to_running_instance → MainWindow)
    # is not feasible in-process because the sender's QLocalSocket gets
    # garbage-collected before the server reads from it. The real scenario
    # (separate processes) was verified manually and works correctly.
    # Individual pieces are covered by TestTrySendToRunningInstance and
    # TestIpcServer above.
