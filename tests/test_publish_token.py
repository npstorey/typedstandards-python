"""The GitHub token (typedstandards#141 P2, acceptance 1's token line, 2 and 4).

- A token comes from ``token=``, else ``TYPEDSTANDARDS_GITHUB_TOKEN``; one that does not start
  ``github_pat_``, or that holds whitespace, a quote or ``op://``, is refused before any request,
  and the refusal's text does not hold the value.
- No captured stdout, stderr, log record, warning or exception text holds the token's value on
  any publish path, and the scanner is itself driven over offending paths to show it fails there.
- No file is opened or written while publishing, and the host's ``repr`` names only the
  repository and the branch.

The token is visibly fake. Every test drives the fake API through ``httpx.MockTransport``.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import logging
import os
import pickle
import sys
import traceback
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from github_stub import FakeGitHub  # publish_support puts scripts/ on the path
from publish_support import HOST_MODES, TOKEN, Docs, github, host

import typedstandards as ts

#: The part of a fine-grained token after its public prefix: the secret itself.
SECRET_TAIL = TOKEN[len("github_pat_") :]


# --- the scanner ------------------------------------------------------------------------------


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))
        self.lines.append(repr(record.args))


def captured(call: Callable[[], Any]) -> list[tuple[str, str]]:
    """Run ``call`` with stdout, stderr, every logger at DEBUG and warnings captured. Returns
    ``(where, text)`` for each: the outputs, each log record (formatted, and its arguments), each
    warning, the returned value's ``repr``, and an exception's ``str``, ``repr`` and traceback,
    also with each frame's locals."""
    out, err = io.StringIO(), io.StringIO()
    handler = _Records()
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    texts: list[tuple[str, str]] = []
    try:
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            try:
                texts.append(("return value", repr(call())))
            except (Exception, KeyboardInterrupt) as error:  # every exception's text is scanned
                texts.append(("exception str", str(error)))
                texts.append(("exception repr", repr(error)))
                texts.append(("traceback", "".join(traceback.format_exception(error))))
                # What a verbose notebook traceback (IPython's %xmode Verbose) shows: each frame's locals.
                with_locals = traceback.TracebackException.from_exception(error, capture_locals=True)
                texts.append(("traceback with locals", "".join(with_locals.format())))
        texts += [("warning", str(w.message)) for w in caught]
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
    texts += [("stdout", out.getvalue()), ("stderr", err.getvalue())]
    texts += [("log record", line) for line in handler.lines]
    return texts


def leaks(token: str, texts: list[tuple[str, str]]) -> list[str]:
    """Where the token's value, or its secret part, appears in captured text."""
    tail = token[len("github_pat_") :] if token.startswith("github_pat_") else token
    return sorted({where for where, text in texts if token in text or (tail and tail in text)})


# --- every publish path, scanned -------------------------------------------------------------


def publish_paths(docs: Docs, mode: str = "transport") -> dict[str, Callable[[], Any]]:
    """Each path of acceptance 1 as a call, on a fresh fake host per call."""

    def run(listed: dict | None = None, setup: Callable[[FakeGitHub], None] | None = None, **kwargs: Any):
        def call() -> Any:
            gh = github(docs, listed=listed)
            if setup:
                setup(gh)
            target = kwargs.pop("_target", "publish")
            if target == "attestation":
                return ts.publish_attestation(docs.withdrawal, host=host(gh, mode), name="dog-licensing")
            return ts.publish(kwargs.pop("_signed", docs.first), host=host(gh, mode), **kwargs)

        return call

    first = {"dog-licensing": docs.first}
    return {
        "a new record": run(name="dog-licensing", title="T"),
        "the default name": run(notebook="dog-licensing.ipynb", title="T"),
        "a listed hash": run(first, name="dog-licensing", title="T"),
        "a listed name, refused": run(first, _signed=docs.second, name="dog-licensing", title="T"),
        "a listed name, revises": run(
            first, _signed=docs.second, name="dog-licensing", title="T", revises=docs.revises
        ),
        "a records segment": run(name="records/x", title="T"),
        "a name failing the rule": run(name="a b", title="T"),
        "a BlobRef output": run(_signed=docs.blobref, name="x", title="T"),
        "another signer": run(_signed=docs.foreign, name="x", title="T"),
        "a role no rule admits": run(name="x", title="T", role="claim"),
        "an empty title": run(name="x", title=""),
        "a non-fast-forward, retried": run(setup=lambda gh: setattr(gh, "concurrent_writes", 1), name="x", title="T"),
        "a non-fast-forward, twice": run(setup=lambda gh: setattr(gh, "concurrent_writes", 2), name="x", title="T"),
        "a ref update that landed": run(setup=lambda gh: setattr(gh, "landed_but_failed", [502]), name="x", title="T"),
        "an attestation": run(first, _target="attestation"),
        "an API error": run(setup=lambda gh: setattr(gh, "token", "github_pat_other"), name="x", title="T"),
    }


@pytest.mark.parametrize("mode", HOST_MODES)
def test_no_output_holds_the_token_on_any_publish_path(docs: Docs, mode: str) -> None:
    """Each path, with the client publish builds and with a client the caller gives."""
    found = {}
    for label, call in publish_paths(docs, mode).items():
        texts = captured(call)
        assert texts, label
        if leaks(TOKEN, texts):
            found[label] = leaks(TOKEN, texts)
    assert found == {}


def test_the_paths_raise_and_log_what_they_should(docs: Docs) -> None:
    """The scan above reads real text: refusals raise, and a write logs its requests."""
    texts = captured(publish_paths(docs)["a records segment"])
    assert any(where == "exception str" and "records" in text for where, text in texts)
    texts = captured(publish_paths(docs)["a new record"])
    assert any(where == "log record" and "git/refs/heads/main" in text for where, text in texts)


@pytest.mark.parametrize(
    "value",
    [
        "github_pat_TESTONLY with a space",
        "github_pat_TESTONLY_trailing_newline\n",
        "\tgithub_pat_TESTONLY_leading_tab",
        '"github_pat_TESTONLY_double_quoted"',
        "'github_pat_TESTONLY_single_quoted'",
        "op://Example Vault/example item/credential",
        "github_pat_TESTONLY_op://unresolved",
        "ghp_TESTONLYclassicshape",
        "TESTONLYnoprefixatall",
        "github_pat_",
    ],
)
def test_a_token_of_the_wrong_shape_is_refused_without_its_value(docs: Docs, value: str) -> None:
    gh = github(docs)
    bad = ts.GitHubPagesHost(gh.repository, token=value, transport=gh.transport())
    texts = captured(lambda: ts.publish(docs.first, host=bad, name="dog-licensing", title="T"))
    error = next(text for where, text in texts if where == "exception repr")
    assert error.startswith("PublishRefusedError(")
    if value != "github_pat_":  # the bare prefix is in the refusal's own words
        assert leaks(value, texts) == [] and leaks(value.strip("\"' \t\n"), texts) == []
    assert gh.requests == []


def test_a_wrong_token_from_the_environment_is_refused_without_its_value(
    docs: Docs, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = "github_pat_TESTONLY from the environment"
    monkeypatch.setenv(ts.TOKEN_VARIABLE, value)
    gh = github(docs)
    texts = captured(
        lambda: ts.publish(
            docs.first, host=ts.GitHubPagesHost(gh.repository, transport=gh.transport()), name="x", title="T"
        )
    )
    assert any(where == "exception str" and ts.TOKEN_VARIABLE in text for where, text in texts)
    assert leaks(value, texts) == []
    assert gh.requests == []


def test_no_token_is_refused(docs: Docs, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ts.TOKEN_VARIABLE, raising=False)
    gh = github(docs)
    with pytest.raises(ts.PublishRefusedError, match="TYPEDSTANDARDS_GITHUB_TOKEN"):
        ts.publish(docs.first, host=ts.GitHubPagesHost(gh.repository, transport=gh.transport()), name="x", title="T")
    assert gh.requests == []


# --- the scanner fails on an offender ------------------------------------------------------------


def _offender(docs: Docs, how: str) -> Callable[[], Any]:
    """A publish whose transport leaks the Authorization header one way."""

    def call() -> Any:
        gh = github(docs)

        def leak(request: httpx.Request) -> None:
            value = request.headers["authorization"]
            if how == "stdout":
                print(value)
            elif how == "stderr":
                print(value, file=sys.stderr)
            elif how == "log record":
                logging.getLogger("typedstandards").debug("sent %s", value)
            elif how == "warning":
                warnings.warn(f"sent {value}", stacklevel=1)
            elif how == "exception":
                raise RuntimeError(f"sent {value}")
            elif how == "frame local":
                raise RuntimeError("a frame holding the header as a local raised")
            return None

        gh.hook = leak
        return ts.publish(docs.first, host=host(gh), name="dog-licensing", title="T")

    return call


@pytest.mark.parametrize("how", ["stdout", "stderr", "log record", "warning", "exception", "frame local"])
def test_the_scanner_fails_on_an_offender(docs: Docs, how: str) -> None:
    found = leaks(TOKEN, captured(_offender(docs, how)))
    expected = {"exception": "exception str", "frame local": "traceback with locals"}.get(how, how)
    assert expected in found


def test_the_scanner_finds_the_secret_part_alone() -> None:
    assert leaks(TOKEN, [("stdout", f"…{SECRET_TAIL}")]) == ["stdout"]
    assert leaks(TOKEN, [("stdout", "github_pat_ and nothing else")]) == []


# --- acceptance 4 -------------------------------------------------------------------------------


def test_the_token_comes_from_the_argument_else_the_environment(docs: Docs, monkeypatch: pytest.MonkeyPatch) -> None:
    gh = github(docs)
    monkeypatch.setenv(ts.TOKEN_VARIABLE, TOKEN)
    from_env = ts.GitHubPagesHost(gh.repository, transport=gh.transport())
    assert ts.publish(docs.first, host=from_env, name="a", title="T")["written"] is True

    monkeypatch.setenv(ts.TOKEN_VARIABLE, "github_pat_TESTONLY_the_environments")
    assert ts.publish(docs.second, host=host(gh), name="b", title="T")["written"] is True  # token= wins
    with pytest.raises(ts.PublishError, match="401"):
        ts.publish(docs.third, host=ts.GitHubPagesHost(gh.repository, transport=gh.transport()), name="c", title="T")


def test_the_environment_is_read_when_publishing(docs: Docs, monkeypatch: pytest.MonkeyPatch) -> None:
    """A host made before the variable is set (a notebook's first cell) still finds it."""
    monkeypatch.delenv(ts.TOKEN_VARIABLE, raising=False)
    gh = github(docs)
    made_first = ts.GitHubPagesHost(gh.repository, transport=gh.transport())
    monkeypatch.setenv(ts.TOKEN_VARIABLE, TOKEN)
    assert ts.publish(docs.first, host=made_first, name="a", title="T")["written"] is True


def test_publishing_opens_and_writes_no_file(docs: Docs, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real_open, real_os_open = builtins.open, os.open

    def recording_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(f"open {file}")
        return real_open(file, *args, **kwargs)

    def recording_os_open(path: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(f"os.open {path}")
        return real_os_open(path, *args, **kwargs)

    gh = github(docs, listed={"dog-licensing": docs.first})
    target = host(gh)
    monkeypatch.setattr(builtins, "open", recording_open)
    monkeypatch.setattr(os, "open", recording_os_open)
    for method in ("write_text", "write_bytes", "touch", "open"):
        monkeypatch.setattr(Path, method, lambda self, *a, _m=method, **k: opened.append(f"Path.{_m} {self}"))
    ts.publish(docs.second, host=target, name="dog-licensing", title="T", revises=docs.revises)
    ts.publish_attestation(docs.withdrawal, host=target, name="dog-licensing")
    assert opened == []


def test_the_hosts_repr_shows_the_repository_and_branch_only() -> None:
    made = ts.GitHubPagesHost("example-owner/example-host", token=TOKEN)
    assert repr(made) == "GitHubPagesHost('example-owner/example-host', branch='main')"
    assert str(made) == repr(made)
    other = ts.GitHubPagesHost("example-owner/example-host", branch="pages", token=TOKEN)
    assert repr(other) == "GitHubPagesHost('example-owner/example-host', branch='pages')"


def test_the_host_does_not_expose_the_token() -> None:
    made = ts.GitHubPagesHost("example-owner/example-host", token=TOKEN)
    with pytest.raises(TypeError):
        vars(made)
    with pytest.raises(TypeError):
        pickle.dumps(made)
    texts = [repr(getattr(made, name, None)) for name in dir(made)]
    assert leaks(TOKEN, [("attribute", text) for text in texts]) == []
    assert TOKEN not in json.dumps(texts)


@pytest.mark.parametrize("repository", ["", "example-owner", "a/b/c", "https://github.com/a/b", "a b/c"])
def test_a_repository_that_is_not_owner_slash_name_is_refused(repository: str) -> None:
    with pytest.raises(ValueError, match="owner/name"):
        ts.GitHubPagesHost(repository, token=TOKEN)


def test_publishing_reads_the_token_variable_and_never_the_whole_environment(
    docs: Docs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client a call builds (no transport given) does not iterate os.environ, which holds the
    seed, for proxy settings. The autouse guard stops the request at the socket."""
    from support import SEED_VARIABLE
    from test_guards import RecordingEnviron

    monkeypatch.setenv(ts.TOKEN_VARIABLE, TOKEN)
    monkeypatch.setenv(SEED_VARIABLE, "not-a-seed")
    recorder = RecordingEnviron(os.environ)
    monkeypatch.setattr(os, "environ", recorder)
    with pytest.raises(Exception, match="network connection"):
        ts.publish(docs.first, host=ts.GitHubPagesHost("example-owner/example-host"), name="x", title="T")
    assert ts.TOKEN_VARIABLE in recorder.keys_read
    assert SEED_VARIABLE not in recorder.keys_read
    assert recorder.read_all is False


# --- an exception that escapes the HTTP client, with either client ------------------------------


def _raises_inside(request: httpx.Request) -> httpx.Response:
    raise RuntimeError("a transport failed with an error that is not a transport error")


def _interrupted(request: httpx.Request) -> httpx.Response:
    raise KeyboardInterrupt


def _undecodable(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"not gzip data")


def _failing_hook(request: httpx.Request) -> None:
    raise RuntimeError("an event hook failed")


ESCAPES = {
    "an error raised inside the transport": (_raises_inside, None),
    "an interrupt inside the transport": (_interrupted, None),
    "a body that does not decode": (_undecodable, None),
    "an error raised by an event hook": (None, _failing_hook),
}


@pytest.mark.parametrize("mode", HOST_MODES)
@pytest.mark.parametrize("escape", ESCAPES)
def test_no_frame_holds_the_token_when_an_exception_escapes_the_client(docs: Docs, mode: str, escape: str) -> None:
    """No frame a traceback shows, publish's or httpx's, holds the token as a plain value, with a
    given client or publish's own, whatever escapes the request."""
    handler, hook = ESCAPES[escape]
    if hook is not None and mode == "transport":
        pytest.skip("an event hook belongs to a client the caller gives")

    def call() -> Any:
        gh = github(docs)
        if handler is not None:
            gh.hook = handler
        kwargs = {"event_hooks": {"request": [hook]}} if hook is not None else {}
        return ts.publish(docs.first, host=host(gh, mode, **kwargs), name="dog-licensing", title="T")

    texts = captured(call)
    assert any(where == "traceback with locals" for where, _ in texts), texts
    assert leaks(TOKEN, texts) == []


# --- GitHubPagesHost's own errors -----------------------------------------------------------------


#: A token-shaped value given as the wrong argument. Module constants, so the calls below hold no
#: local of their own that a traceback with frame locals would print: only the package's frames
#: are under test.
WRONG_ARGUMENT = "github_pat_TESTONLY_given_as_the_wrong_argument"
MISPLACED = {
    "repository": lambda: ts.GitHubPagesHost(WRONG_ARGUMENT, token=TOKEN),
    "branch": lambda: ts.GitHubPagesHost("example-owner/example-host", branch=WRONG_ARGUMENT, token=TOKEN),
    "api_url": lambda: ts.GitHubPagesHost("example-owner/example-host", api_url=WRONG_ARGUMENT, token=TOKEN),
}


@pytest.mark.parametrize("argument", MISPLACED)
def test_the_hosts_errors_never_quote_their_argument(argument: str) -> None:
    """A token-shaped value given as the wrong argument stays out of the error's str, repr and
    traceback with locals, and so does the token= given beside it."""
    texts = captured(MISPLACED[argument])
    assert any(where == "exception repr" and text.startswith("ValueError(") for where, text in texts), texts
    assert leaks(WRONG_ARGUMENT, texts) == []
    assert leaks(TOKEN, texts) == []


#: A token-shaped part: a token prefix and a run of token characters as long as a token's. Built at
#: run time, so this file holds no literal of a token's shape.
TOKEN_SHAPED = "ghp_" + "TESTONLY" * 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repository": "example-owner/ghp_notes"},
        {"repository": "example-owner/gho_tools"},
        {"repository": "example-owner/github_pat_docs"},
        {"repository": "example-owner/example-host", "branch": "ghs_release-notes"},
    ],
    ids=["a ghp_ repository", "a gho_ repository", "a github_pat_ repository", "a ghs_ branch"],
)
def test_a_name_that_starts_with_a_token_prefix_is_accepted(kwargs: dict[str, str]) -> None:
    """Only a token-shaped part is refused: a short name with a token prefix is a name."""
    made = ts.GitHubPagesHost(**kwargs)
    assert made.repository == kwargs["repository"]


@pytest.mark.parametrize("argument", ["repository", "branch"])
def test_a_token_shaped_repository_or_branch_is_refused(argument: str) -> None:
    kwargs = {"repository": "example-owner/example-host", argument: f"example-owner/{TOKEN_SHAPED}"}
    if argument == "branch":
        kwargs["branch"] = TOKEN_SHAPED
    with pytest.raises(ValueError, match="looks like a GitHub token") as caught:
        ts.GitHubPagesHost(**kwargs)
    assert TOKEN_SHAPED not in str(caught.value) and TOKEN_SHAPED not in repr(caught.value)
