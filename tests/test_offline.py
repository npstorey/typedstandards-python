"""Acceptance 6: no test opens a network connection or binds a port.

``conftest.py``'s autouse ``no_network`` fixture replaces ``socket.socket.connect``,
``connect_ex``, ``bind`` and ``socket.create_connection`` with functions that raise
:class:`support.NetworkBlocked`, for every test. These tests drive a real attempt of each kind,
so a guard that stops guarding fails here.
"""

from __future__ import annotations

import socket

import httpx
import pytest
from support import NetworkBlocked


def test_create_connection_is_blocked() -> None:
    with pytest.raises(NetworkBlocked, match="network"):
        socket.create_connection(("127.0.0.1", 9), timeout=1)


def test_connect_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        with pytest.raises(NetworkBlocked, match="network"):
            sock.connect(("127.0.0.1", 9))


def test_connect_ex_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlocked, match="network"):
            sock.connect_ex(("127.0.0.1", 9))


def test_bind_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlocked, match="port"):
            sock.bind(("127.0.0.1", 0))


def test_an_http_client_without_a_mock_transport_is_blocked() -> None:
    """httpx's real transport reaches the guard, so a helper test that forgot its mock fails."""
    with httpx.Client() as client, pytest.raises(NetworkBlocked):
        client.get("http://127.0.0.1:9/")
