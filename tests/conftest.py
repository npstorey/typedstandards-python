"""Fixtures: no network for any test, a test seed in the environment, and a recorder of the
wrapper's child processes."""

from __future__ import annotations

import os
import socket
import subprocess
from typing import Any

import pytest
from publish_support import Docs, make_docs
from support import SEED_VARIABLE, NetworkBlocked, fresh_seed_b64


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs offline: opening a connection or binding a port raises NetworkBlocked.

    The CLI makes no network request and the helpers' HTTP goes through an injected
    ``httpx.MockTransport``, so nothing a test does should reach a socket. Child processes (the
    CLI under Node) are outside this guard; the CLI's own contract is that it opens none.
    """

    def connect(self: socket.socket, address: Any) -> None:
        raise NetworkBlocked(f"a test opened a network connection to {address!r}")

    def connect_ex(self: socket.socket, address: Any) -> int:
        raise NetworkBlocked(f"a test opened a network connection to {address!r}")

    def bind(self: socket.socket, address: Any) -> None:
        raise NetworkBlocked(f"a test bound a port at {address!r}")

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        raise NetworkBlocked(f"a test opened a network connection to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket.socket, "bind", bind)
    monkeypatch.setattr(socket, "create_connection", create_connection)


@pytest.fixture
def seed(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set a fresh seed in the environment the wrapper's child inherits."""
    value = fresh_seed_b64()
    monkeypatch.setenv(SEED_VARIABLE, value)
    return value


#: The CLI flags whose value is an input document's path (or ``-`` for standard input).
INPUT_FLAGS = frozenset({"--input", "--signed", "--attestation"})


def _input_files(args: list[str]) -> dict[str, bytes]:
    """The bytes of every input file the argv names, read as the child starts: the wrapper
    removes its temporary files before it returns."""
    files = {}
    for flag, value in zip(args, args[1:], strict=False):
        if flag in INPUT_FLAGS and value != "-" and os.path.isfile(value):
            with open(value, "rb") as handle:
                files[value] = handle.read()
    return files


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every child process the wrapper starts: its argv, its keyword arguments, the
    stdin bytes it was given, the bytes of each input file its argv names (``files``, read at
    spawn), and os.environ at that moment. The call still runs."""
    calls: list[dict[str, Any]] = []
    real_popen = subprocess.Popen
    real_communicate = subprocess.Popen.communicate

    class RecordingPopen(real_popen):  # type: ignore[misc, valid-type]
        def __init__(self, args: Any, *rest: Any, **kwargs: Any) -> None:
            self._record = {
                "args": list(args),
                "kwargs": dict(kwargs),
                "environ": dict(os.environ),
                "stdin": None,
                "files": _input_files([str(a) for a in args]),
            }
            calls.append(self._record)
            super().__init__(args, *rest, **kwargs)

        def communicate(self, input: Any = None, timeout: Any = None) -> Any:
            self._record["stdin"] = input
            return real_communicate(self, input, timeout)

    monkeypatch.setattr(subprocess, "Popen", RecordingPopen)
    return calls


@pytest.fixture(scope="session")
def docs(tmp_path_factory: pytest.TempPathFactory) -> Docs:
    """The publish tests' records and attestations, signed once by the vendored CLI."""
    return make_docs(tmp_path_factory.mktemp("publish"))
