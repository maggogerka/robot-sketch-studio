from __future__ import annotations

import socket

from robot_sketch_studio.__main__ import _port_available


def test_port_guard_detects_existing_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert not _port_available("127.0.0.1", port)


def test_port_guard_accepts_free_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    assert _port_available("127.0.0.1", port)
