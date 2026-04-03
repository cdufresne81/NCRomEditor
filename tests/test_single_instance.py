"""
Tests for single-instance IPC and command-line file argument handling.
"""

import os
import uuid
import pytest
from unittest.mock import patch
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


class TestMainWindowIpcServer:
    """Tests for MainWindow.start_ipc_server / _on_ipc_connection."""

    def test_server_starts_and_listens(self, qtbot, ipc_name):
        from main import MainWindow

        window = MainWindow()
        qtbot.addWidget(window)
        window.start_ipc_server(server_name=ipc_name)

        assert window._ipc_server is not None
        assert window._ipc_server.isListening()

        window.close()

    def test_server_receives_file(self, qtbot, sample_rom_path, ipc_name):
        from main import MainWindow

        window = MainWindow()
        qtbot.addWidget(window)
        window.start_ipc_server(server_name=ipc_name)

        with patch.object(window, "_open_rom_file") as mock_open:
            socket = QLocalSocket()
            socket.connectToServer(ipc_name)
            assert socket.waitForConnected(1000)

            file_path = str(sample_rom_path)
            socket.write(file_path.encode("utf-8"))
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()

            qtbot.waitUntil(lambda: mock_open.call_count == 1, timeout=2000)
            mock_open.assert_called_once_with(file_path)

        window.close()

    def test_server_ignores_nonexistent_file(self, qtbot, ipc_name):
        from main import MainWindow

        window = MainWindow()
        qtbot.addWidget(window)
        window.start_ipc_server(server_name=ipc_name)

        with patch.object(window, "_open_rom_file") as mock_open:
            socket = QLocalSocket()
            socket.connectToServer(ipc_name)
            assert socket.waitForConnected(1000)

            socket.write(b"C:\\nonexistent\\fake.bin")
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()

            # Give it time to process — should NOT call _open_rom_file
            qtbot.wait(500)
            mock_open.assert_not_called()

        window.close()

    def test_server_ignores_empty_message(self, qtbot, ipc_name):
        from main import MainWindow

        window = MainWindow()
        qtbot.addWidget(window)
        window.start_ipc_server(server_name=ipc_name)

        with patch.object(window, "_open_rom_file") as mock_open:
            socket = QLocalSocket()
            socket.connectToServer(ipc_name)
            assert socket.waitForConnected(1000)

            socket.write(b"")
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()

            qtbot.wait(500)
            mock_open.assert_not_called()

        window.close()

    # NOTE: Full round-trip test (_try_send_to_running_instance → MainWindow)
    # is not feasible in-process because the sender's QLocalSocket gets
    # garbage-collected before the server reads from it. The real scenario
    # (separate processes) was verified manually and works correctly.
    # Individual pieces are covered by TestTrySendToRunningInstance and
    # TestMainWindowIpcServer above.
