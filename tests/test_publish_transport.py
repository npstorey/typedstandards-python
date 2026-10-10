"""The token on httpx's real transport (typedstandards#141 P5): ``httpx.HTTPTransport``, so each
request's head is written through httpcore and h11, as it is outside the tests.

httpcore's sync network backend is replaced, for one test at a time, by one whose ``connect_tcp``
returns a stream that opens no socket (the autouse offline guard stays on) and whose ``write``
fails. The rule checked: when an exception escapes a publish's request, with publish's own client
or a given one, no frame it carries holds the token, in the exception, its ``__cause__`` or its
``__context__``, and the formatted traceback with frame locals does not show it either.

Locked versions: httpx 0.28.1, httpcore 1.0.9, h11 0.16.0 (``uv.lock``).
"""

from __future__ import annotations

import traceback
from collections.abc import Iterator
from typing import Any

import httpcore
import httpx
import pytest
from httpcore._backends.base import NetworkStream
from httpcore._backends.sync import SyncBackend
from httpcore._exceptions import ReadError, WriteError, map_exceptions
from publish_support import TOKEN, Docs

import typedstandards as ts

SECRET_TAIL = TOKEN[len("github_pat_") :]


def _write_interrupted() -> None:
    raise KeyboardInterrupt


def _write_failed() -> None:
    raise RuntimeError("the stream failed while writing")


def _write_os_error() -> None:
    # As httpcore's own SyncStream.write maps a socket's OSError. httpcore's HTTP/1.1 connection
    # passes over a WriteError from the request head and reads the response, so the transport
    # error that escapes is the read's (_read_os_error).
    with map_exceptions({OSError: WriteError}):
        raise OSError("the connection was reset while writing")


def _read_os_error() -> bytes:
    with map_exceptions({OSError: ReadError}):
        raise OSError("the connection was reset while reading")


#: How the stream fails: (its write, its read). The read is reached only after a WriteError.
FAILURES = {
    "an interrupt": (_write_interrupted, None),
    "an error that is not a transport error": (_write_failed, None),
    "a transport error": (_write_os_error, _read_os_error),
}


class FailingStream(NetworkStream):
    """A stream with no socket: TLS is a no-op, and the first write fails one way."""

    def __init__(self, fail: Any) -> None:
        self.fail_write, self.fail_read = fail
        self.written = 0

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self.fail_read() if self.fail_read is not None else b""

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.written += len(buffer)
        self.fail_write()

    def close(self) -> None:
        pass

    def start_tls(self, ssl_context: Any, server_hostname: str | None = None, timeout: float | None = None) -> Any:
        return self

    def get_extra_info(self, info: str) -> Any:
        return None


@pytest.fixture
def failing_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    """Make httpcore's sync backend hand out a FailingStream; the test sets ``fail``."""
    state: dict[str, Any] = {"fail": None, "streams": []}

    def connect_tcp(self: SyncBackend, host: str, port: int, **kwargs: Any) -> NetworkStream:
        stream = FailingStream(state["fail"])
        state["streams"].append(stream)
        return stream

    monkeypatch.setattr(SyncBackend, "connect_tcp", connect_tcp)
    yield state


def _exceptions(error: BaseException) -> Iterator[BaseException]:
    """The exception and every exception chained to it, as ``__cause__`` or ``__context__``."""
    seen: set[int] = set()
    pending = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending += [e for e in (current.__cause__, current.__context__) if e is not None]


def _frame_texts(error: BaseException) -> list[tuple[str, str]]:
    """The repr of every local of every frame each chained exception's traceback carries, and each
    exception's traceback formatted with frame locals."""
    texts = []
    for current in _exceptions(error):
        tb = current.__traceback__
        while tb is not None:
            frame = tb.tb_frame
            where = f"{frame.f_code.co_filename.rsplit('/', 1)[-1]}:{tb.tb_lineno} {frame.f_code.co_name}"
            for name, value in frame.f_locals.items():
                try:
                    texts.append((f"{where} local {name}", repr(value)))
                except Exception:  # a repr that fails holds nothing to read
                    pass
            tb = tb.tb_next
        formatted = traceback.TracebackException.from_exception(current, capture_locals=True)
        texts.append((f"{type(current).__name__} formatted with locals", "".join(formatted.format())))
        texts.append((f"{type(current).__name__} str and repr", f"{current!s} {current!r}"))
    return texts


def _host(mode: str) -> ts.GitHubPagesHost:
    if mode == "client":
        return ts.GitHubPagesHost(
            "example-owner/example-host", token=TOKEN, client=httpx.Client(transport=httpx.HTTPTransport())
        )
    return ts.GitHubPagesHost("example-owner/example-host", token=TOKEN, transport=httpx.HTTPTransport())


@pytest.mark.parametrize("mode", ["transport", "client"])
@pytest.mark.parametrize("failure", FAILURES)
def test_no_frame_holds_the_token_when_the_real_transport_fails(
    docs: Docs, failing_network: dict[str, Any], mode: str, failure: str
) -> None:
    """With publish's own client and with a given one, whatever escapes the request head's write
    on httpx's real transport, no frame it carries holds the token."""
    failing_network["fail"] = FAILURES[failure]
    try:
        ts.publish(docs.first, host=_host(mode), name="dog-licensing", title="T")
    except BaseException as error:  # KeyboardInterrupt included: the test reads what escaped
        escaped = error
    else:
        pytest.fail("the publish did not fail")
    # The request head reached the stream, through httpcore and h11.
    assert failing_network["streams"] and failing_network["streams"][0].written > 0
    if failure == "an interrupt":
        assert type(escaped) is KeyboardInterrupt
    elif failure == "a transport error":
        assert isinstance(escaped, ts.PublishError)
        assert any(isinstance(e, httpcore.ReadError) for e in _exceptions(escaped))
    else:
        assert type(escaped) is RuntimeError
    texts = _frame_texts(escaped)
    found = sorted({where for where, text in texts if TOKEN in text or SECRET_TAIL in text})
    assert found == []


def test_the_frame_walk_finds_a_token_held_below_it(failing_network: dict[str, Any]) -> None:
    """The walk above reads httpcore's frames: a request whose header dict carries the token, sent
    without publish, shows it there."""
    failing_network["fail"] = (_write_failed, None)
    client = httpx.Client(transport=httpx.HTTPTransport())
    try:
        client.get("https://api.example.org/", headers={"Authorization": "Bearer " + TOKEN})
    except RuntimeError as error:
        escaped = error
    found = {where for where, text in _frame_texts(escaped) if SECRET_TAIL in text}
    assert any("http11.py" in where for where in found), sorted(found)
